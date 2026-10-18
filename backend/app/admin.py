"""Admin API endpoints — all require admin role."""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import record_audit
from .auth import hash_password
from .db import get_db
from .deps import require_feature, require_role
from .email_service import send_license_email
from .models_db import User, StripeCustomer, IssuedLicense, SpoolLog, PasswordResetToken, RefreshToken
from .firstrun import public_base_url as _public_base_url


admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── GET /api/admin/users ──────────────────────────────────────────────────────

@admin_router.get("/users")
async def list_users(
    _: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all users: id, username, role, created_at."""
    result = await db.execute(
        select(User.id, User.username, User.role, User.created_at, User.is_active)
        .order_by(User.id)
    )
    rows = result.all()
    return [
        {
            "id": row.id,
            "username": row.username,
            "role": row.role,
            "is_active": row.is_active,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


# ── GET /api/admin/usage ─────────────────────────────────────────────────────

@admin_router.get("/usage")
async def get_usage(
    _: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Per-printer job counts from spool_log in the last 7 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    result = await db.execute(
        select(SpoolLog.printer_id, func.count(SpoolLog.id).label("job_count"))
        .where(SpoolLog.created_at >= cutoff)
        .group_by(SpoolLog.printer_id)
        .order_by(func.count(SpoolLog.id).desc())
    )
    rows = result.all()
    return [{"printer_id": row.printer_id, "job_count": row.job_count} for row in rows]


# ── GET /api/admin/subscriptions ─────────────────────────────────────────────

@admin_router.get("/subscriptions")
async def list_subscriptions(
    _: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """List all IssuedLicense records joined with StripeCustomer email."""
    result = await db.execute(
        select(
            IssuedLicense.id,
            IssuedLicense.email,
            IssuedLicense.tier,
            IssuedLicense.activated,
            IssuedLicense.expires_at,
            IssuedLicense.issued_at,
            IssuedLicense.stripe_customer_id,
            IssuedLicense.device_limit,
        ).order_by(IssuedLicense.issued_at.desc())
    )
    rows = result.all()
    return [
        {
            "id": row.id,
            "email": row.email,
            "tier": row.tier,
            "activated": row.activated,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "issued_at": row.issued_at.isoformat() if row.issued_at else None,
            "stripe_customer_id": row.stripe_customer_id,
            "device_limit": row.device_limit,
        }
        for row in rows
    ]


# ── POST /api/admin/users/{user_id}/role ─────────────────────────────────────

VALID_ROLES = {"admin", "operator", "viewer"}


class RoleUpdateRequest(BaseModel):
    role: str


@admin_router.post("/users/{user_id}/role")
async def update_user_role(
    user_id: int,
    body: RoleUpdateRequest,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's role. Body: {"role": "admin"|"operator"|"viewer"}."""
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    old_role = user.role

    # M2 BUG FIX: Atomic update with guard condition. The original code counted
    # active admins, then updated the user outside the atomic section. Two concurrent
    # requests for different admins could both see count >= 2, then both demote,
    # leaving zero admins. Fixed by using an atomic UPDATE with a WHERE clause that
    # includes the guard condition: the update only succeeds if it wouldn't leave zero
    # active admins. Verify rowcount to detect race failure.
    if old_role == "admin" and body.role != "admin":
        # Atomic: only update if there's at least one other active admin
        from sqlalchemy import and_ as sql_and
        from sqlalchemy.orm import aliased
        AdminCheck = aliased(User)
        result = await db.execute(
            update(User).where(
                sql_and(
                    User.id == user_id,
                    # Guard: count other active admins. Uses an ALIASED User table
                    # (AdminCheck) so the subquery has its own independent FROM
                    # reference — .correlate(User) here would incorrectly bind the
                    # subquery's User to the UPDATE statement's target table,
                    # collapsing "other admins" down to the same single row and
                    # making the guard always evaluate to 0 (always blocked).
                    select(func.count()).select_from(AdminCheck).where(
                        AdminCheck.role == "admin",
                        AdminCheck.is_active == True,  # noqa: E712
                        AdminCheck.id != user_id,
                    ).scalar_subquery() > 0,
                )
            ).values(role=body.role)
        )
        if result.rowcount == 0:
            # The guard condition failed: this is the last active admin, can't demote
            raise HTTPException(status_code=400, detail="Cannot demote the last admin")
    else:
        # Not a demotion from admin, no guard needed
        user.role = body.role
        await db.commit()

    await db.commit()
    # Reload user to get updated role from DB
    await db.refresh(user)
    await record_audit(db, action="user_role_change", user=current_user, resource=f"user:{user.id}",
                       detail={"username": user.username, "from": old_role, "to": user.role}, request=request)
    return {"id": user.id, "username": user.username, "role": user.role}


# ── POST /api/admin/users  (create) ──────────────────────────────────────────

class CreateUserRequest(BaseModel):
    username: str = Field(max_length=255, min_length=1)
    password: str = Field(min_length=8, max_length=1024)
    role: str = "viewer"


@admin_router.post("/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    __: None = Depends(require_feature("multi_user")),
    db: AsyncSession = Depends(get_db),
):
    """Create a user with a role. Admin + multi_user tier."""
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {', '.join(sorted(VALID_ROLES))}")
    existing = await db.execute(select(User).where(User.username == body.username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Username already exists")

    if len(body.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=422, detail="Password must be at most 72 bytes (about 72 ASCII characters).")
    user = User(username=body.username, password_hash=hash_password(body.password), role=body.role,
                is_active=True, auth_provider="local")
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        # ADMIN-CREATEUSER-RACE-01: the existence check above and this commit
        # aren't atomic — two concurrent requests for the same username can
        # both pass the check, and the second commit's unique-constraint
        # violation would otherwise surface as an unhandled 500 instead of
        # the same 409 the pre-check already reports for the common case.
        await db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists")
    await db.refresh(user)
    await record_audit(db, action="user_create", user=current_user, resource=f"user:{user.id}",
                       detail={"username": user.username, "role": user.role}, request=request)
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active}


# ── DELETE /api/admin/users/{user_id} ────────────────────────────────────────

@admin_router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a user. Admin only. Cannot delete yourself or the last admin.
    Audit rows for the deleted user are preserved (user_id nulled, username kept)."""
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    username = user.username

    # BUG-HIGH-FK-01: SQLite runs with foreign_keys OFF (pragma not enabled — see the
    # scaffold NOTE for why we do NOT enable it globally), so ondelete="CASCADE" is
    # inert and these child rows would DANGLE after the user is deleted. With SQLite
    # rowid reuse, a dangling messaging_identities row (bot identity + role) or reset
    # token could then silently re-attach to the next user that reuses this id. Prune
    # them explicitly here — the only place a user is deleted. (refresh_tokens +
    # webhooks are ORM delete-orphan cascaded; audit_log is ORM-nulled, username kept.)
    # Stripe rows are UNLINKED, not deleted, to preserve billing history.
    from sqlalchemy import delete as _delete, update as _update, and_ as sql_and
    from .models_db import MessagingIdentity, AlphaControlAck, WebAuthnCredential
    await db.execute(_delete(MessagingIdentity).where(MessagingIdentity.user_id == user_id))
    await db.execute(_delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
    await db.execute(_delete(AlphaControlAck).where(AlphaControlAck.user_id == user_id))
    await db.execute(_delete(WebAuthnCredential).where(WebAuthnCredential.user_id == user_id))
    await db.execute(_update(StripeCustomer).where(StripeCustomer.user_id == user_id).values(user_id=None))

    # M2 BUG FIX: Atomic delete with guard condition. The original code counted
    # active admins, then deleted the user outside the atomic section. Two concurrent
    # requests for different admins could both see count >= 2, then both delete,
    # leaving zero admins. Fixed by using an atomic DELETE with a WHERE clause that
    # includes the guard condition: the delete only succeeds if it wouldn't leave zero
    # active admins. Verify rowcount to detect race failure.
    if user.role == "admin":
        # Atomic: only delete if there's at least one other active admin
        from sqlalchemy.orm import aliased
        AdminCheck = aliased(User)
        result = await db.execute(
            _delete(User).where(
                sql_and(
                    User.id == user_id,
                    # Guard: count other active admins. Uses an ALIASED User table
                    # (AdminCheck) — see rationale in the role-update guard above.
                    select(func.count()).select_from(AdminCheck).where(
                        AdminCheck.role == "admin",
                        AdminCheck.is_active == True,  # noqa: E712
                        AdminCheck.id != user_id,
                    ).scalar_subquery() > 0,
                )
            )
        )
        if result.rowcount == 0:
            # The guard condition failed: this is the last active admin, can't delete
            await db.rollback()
            raise HTTPException(status_code=400, detail="Cannot delete the last active admin")
    else:
        # Not an admin, no guard needed
        await db.delete(user)

    await db.commit()
    await record_audit(db, action="user_delete", user=current_user, resource=f"user:{user_id}",
                       detail={"username": username}, request=request)
    return {"deleted": user_id, "username": username}


# ── POST /api/admin/users/{user_id}/suspend ───────────────────────────────────

@admin_router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a user. They cannot log in but their data is preserved."""
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="Cannot suspend yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # M2 BUG FIX: Atomic suspend with guard condition. The original code counted
    # active admins, then updated the user outside the atomic section. Two concurrent
    # requests for different admins could both see count >= 2, then both suspend,
    # leaving zero active admins. Fixed by using an atomic UPDATE with a WHERE clause
    # that includes the guard condition: the update only succeeds if it wouldn't leave
    # zero active admins. Verify rowcount to detect race failure.
    if user.role == "admin":
        # Atomic: only suspend if there's at least one other active admin
        from sqlalchemy import and_ as sql_and
        from sqlalchemy.orm import aliased
        AdminCheck = aliased(User)
        result = await db.execute(
            update(User).where(
                sql_and(
                    User.id == user_id,
                    # Guard: count other active admins. Uses an ALIASED User table
                    # (AdminCheck) — see rationale in the role-update guard above.
                    select(func.count()).select_from(AdminCheck).where(
                        AdminCheck.role == "admin",
                        AdminCheck.is_active == True,  # noqa: E712
                        AdminCheck.id != user_id,
                    ).scalar_subquery() > 0,
                )
            ).values(is_active=False)
        )
        if result.rowcount == 0:
            # The guard condition failed: this is the last active admin, can't suspend
            raise HTTPException(status_code=400, detail="Cannot suspend the last active admin")
    else:
        # Not an admin, no guard needed
        user.is_active = False

    # Cut existing sessions immediately: revoke the user's refresh tokens so a
    # live session can't keep refreshing (defense-in-depth with the refresh-time
    # is_active check in auth.refresh_access_token).
    from sqlalchemy import delete as _delete
    await db.execute(_delete(RefreshToken).where(RefreshToken.user_id == user_id))
    await db.commit()
    await record_audit(db, action="user_suspend", user=current_user, resource=f"user:{user_id}",
                       detail={"username": user.username}, request=request)
    return {"id": user_id, "username": user.username, "is_active": False}


# ── POST /api/admin/users/{user_id}/unsuspend ────────────────────────────────

@admin_router.post("/users/{user_id}/unsuspend")
async def unsuspend_user(
    user_id: int,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Reactivate a suspended user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = True
    await db.commit()
    await record_audit(db, action="user_unsuspend", user=current_user, resource=f"user:{user_id}",
                       detail={"username": user.username}, request=request)
    return {"id": user_id, "username": user.username, "is_active": True}


# ── POST /api/admin/users/{user_id}/reset-password ───────────────────────────

@admin_router.post("/users/{user_id}/reset-password")
async def admin_reset_password(
    user_id: int,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Force a password reset on next login by setting must_change_password=True.

    Generates a time-limited reset token and returns it so the admin can share
    the link directly (useful when SMTP is not configured).
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    user.must_change_password = True
    # Also generate a reset token so the admin can hand it to the user directly
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    # Prune old tokens first
    from sqlalchemy import delete as _delete
    await db.execute(_delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
    db.add(PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at))
    await db.commit()

    public_url = _public_base_url()
    reset_url = f"{public_url}/?reset_token={token}"
    await record_audit(db, action="user_reset_password", user=current_user, resource=f"user:{user_id}",
                       detail={"username": user.username}, request=request)
    return {"id": user_id, "username": user.username, "reset_url": reset_url}


# ── POST /api/admin/licenses/{license_id}/reissue ────────────────────────────

@admin_router.post("/licenses/{license_id}/reissue")
async def reissue_license(
    license_id: int,
    request: Request,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Re-generate and re-email a license key without a new Stripe charge.

    Useful when a customer loses their key or the original email bounced.
    """
    from .stripe_webhook import _generate_license_key
    from sqlalchemy import desc

    result = await db.execute(select(IssuedLicense).where(IssuedLicense.id == license_id))
    lic = result.scalar_one_or_none()
    if lic is None:
        raise HTTPException(status_code=404, detail="License not found")

    try:
        new_key = _generate_license_key(
            customer_id=lic.stripe_customer_id,
            device_limit=lic.device_limit,
            tier=lic.tier,
            expires_on=lic.expires_at.date() if lic.expires_at else None,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    lic.license_key = new_key
    await db.commit()

    email_ok = await send_license_email(email=lic.email, tier=lic.tier, license_key=new_key)
    await record_audit(db, action="license_reissue", user=current_user, resource=f"license:{license_id}",
                       detail={"email": lic.email, "tier": lic.tier, "email_sent": email_ok}, request=request)
    return {"id": license_id, "email": lic.email, "tier": lic.tier, "email_sent": email_ok}
