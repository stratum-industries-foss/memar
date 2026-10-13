"""Audit log — records security-relevant events for compliance.

Writes to the AuditLog table (defined in models_db) and exposes an admin,
audit_logs-gated read endpoint. Writes are best-effort: an audit failure is
logged but never propagates into (or rolls back) the caller's request, so the
audited action itself is never blocked by audit bookkeeping.
"""
import json
import logging

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_db
from .deps import require_feature, require_role
from .models_db import AuditLog
from ._limiter import _client_key

logger = logging.getLogger(__name__)


def client_ip(request: Request | None) -> str | None:
    """Client IP using the rate-limiter's trusted-proxy logic.
    
    Delegates to _client_key which only trusts X-Forwarded-For when the socket
    peer is a trusted proxy, and takes the rightmost hop (proxy-appended, not
    client-forgeable) rather than the leftmost (spoofable).
    """
    if request is None:
        return None
    return _client_key(request)


async def record_audit(
    db: AsyncSession,
    *,
    action: str,
    user: dict | None = None,
    resource: str | None = None,
    detail=None,
    request: Request | None = None,
) -> None:
    """Record one audit event. Call AFTER the audited action has committed.

    Best-effort: swallows and logs any error so audit bookkeeping can never
    fail the request it is recording.
    """
    try:
        db.add(
            AuditLog(
                user_id=(user or {}).get("id"),
                username=(user or {}).get("username"),
                action=action,
                resource=resource,
                detail=json.dumps(detail) if isinstance(detail, (dict, list)) else detail,
                ip_address=client_ip(request),
            )
        )
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("audit write failed for action=%s: %s", action, e)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


async def record_audit_batch(db: AsyncSession, entries: list[dict]) -> None:
    """Record multiple audit events in a single commit.

    Each entry accepts the same keys as record_audit's kwargs (action, user,
    resource, detail, request). For batch dispatches (e.g. a fleet-wide
    action) this avoids N sequential add()+commit() round-trips. Trade-off
    vs. record_audit: a write failure here loses the whole batch together,
    not just one row — acceptable for the latency this saves on the
    already-concurrent batch-dispatch hot path.
    """
    try:
        for entry in entries:
            user = entry.get("user")
            detail = entry.get("detail")
            db.add(
                AuditLog(
                    user_id=(user or {}).get("id"),
                    username=(user or {}).get("username"),
                    action=entry["action"],
                    resource=entry.get("resource"),
                    detail=json.dumps(detail) if isinstance(detail, (dict, list)) else detail,
                    ip_address=client_ip(entry.get("request")),
                )
            )
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("audit batch write failed (%d entries): %s", len(entries), e)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass


audit_router = APIRouter(prefix="/api/admin", tags=["audit"])


@audit_router.get("/audit")
async def list_audit(
    _: dict = Depends(require_role("admin")),
    __: None = Depends(require_feature("audit_logs")),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    action: str | None = Query(None, max_length=255),
) -> list[dict]:
    """Most-recent audit events (admin + audit_logs tier). Optional ?action= filter."""
    q = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
    if action:
        q = q.where(AuditLog.action == action)
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "username": r.username,
            "action": r.action,
            "resource": r.resource,
            "detail": r.detail,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
