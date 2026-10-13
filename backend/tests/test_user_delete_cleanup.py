"""BUG-HIGH-FK-01: deleting a user must not leave dangling rows that (with SQLite rowid
reuse) could re-attach to a future user — messaging_identities (bot identity + role),
password-reset tokens, alpha-control acks. Stripe rows are UNLINKED, not deleted
(billing history preserved)."""
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.auth import hash_password
from app.db import AsyncSessionLocal
from app.models_db import (User, MessagingIdentity, PasswordResetToken,
                           AlphaControlAck, StripeCustomer)


@pytest.mark.asyncio
async def test_delete_user_prunes_dangling_child_rows(admin_client):
    # Seed a viewer user with every user-linked child row.
    async with AsyncSessionLocal() as db:
        u = User(username="ghost", password_hash=hash_password("secret123"),
                 role="viewer", is_active=True)
        db.add(u)
        await db.commit()
        await db.refresh(u)
        uid = u.id
        db.add(MessagingIdentity(user_id=uid, platform="matrix", platform_user_id="@ghost:hs"))
        db.add(PasswordResetToken(user_id=uid, token_hash="ghosthash",
                                  expires_at=datetime.now(timezone.utc) + timedelta(minutes=15)))
        db.add(AlphaControlAck(user_id=uid, device_id="cnc-1"))
        db.add(StripeCustomer(user_id=uid, stripe_customer_id="cus_ghost", email="ghost@x.io"))
        await db.commit()

    resp = await admin_client.delete(f"/api/admin/users/{uid}")
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        mi = (await db.execute(select(MessagingIdentity).where(MessagingIdentity.user_id == uid))).scalars().all()
        pr = (await db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == uid))).scalars().all()
        ack = (await db.execute(select(AlphaControlAck).where(AlphaControlAck.user_id == uid))).scalars().all()
        sc = (await db.execute(select(StripeCustomer).where(StripeCustomer.stripe_customer_id == "cus_ghost"))).scalar_one_or_none()

    assert mi == [], "messaging_identities must be pruned on user delete (re-attach vector)"
    assert pr == [], "password-reset tokens must be pruned on user delete"
    assert ack == [], "alpha-control acks must be pruned on user delete"
    assert sc is not None and sc.user_id is None, "stripe row must be UNLINKED (kept for billing), not deleted"
