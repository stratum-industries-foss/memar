"""Command router for bidirectional messaging adapters.

Handles slash commands from any platform and dispatches to the appropriate
handler. Authorization is performed against the MessagingIdentity table.
"""

from __future__ import annotations
from ..timeutil import utcnow as _utcnow

import logging
from datetime import datetime, timedelta
from typing import Callable, Awaitable

from sqlalchemy import select

logger = logging.getLogger(__name__)

# Minimum role required per command.
_ROLE_REQUIREMENTS: dict[str, str] = {
    "status": "viewer",
    "machines": "viewer",
    "machine": "viewer",
    "jobs": "viewer",
    "alerts": "viewer",
    "help": "viewer",
    "ack": "operator",
}

_ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2}


def _role_ok(user_role: str, required: str) -> bool:
    return _ROLE_ORDER.get(user_role, -1) >= _ROLE_ORDER.get(required, 99)


class CommandRouter:
    """Routes incoming text commands to handler functions."""

    def __init__(self, db_factory: Callable):
        self._db = db_factory

    async def dispatch(
        self,
        cmd: str,
        args: list[str],
        sender_id: str,
        platform: str,
    ) -> str:
        """Look up the sender's MEMAR identity, enforce role, call handler."""
        async with self._db() as db:
            from ..models_db import MessagingIdentity, User

            row = (
                await db.execute(
                    select(MessagingIdentity)
                    .where(
                        MessagingIdentity.platform == platform,
                        MessagingIdentity.platform_user_id == sender_id,
                    )
                )
            ).scalar_one_or_none()

            if row is None:
                return (
                    "Your identity is not linked to a MEMAR account.\n"
                    "Ask your admin to run:\n"
                    "  POST /api/admin/messaging/identities\n"
                    '  {"platform": "' + platform + '", '
                    '"platform_user_id": "' + sender_id + '", "username": "..."}'
                )

            user = (
                await db.execute(select(User).where(User.id == row.user_id))
            ).scalar_one_or_none()
            if user is None or not user.is_active:
                return "Your linked MEMAR account is inactive."

            required = _ROLE_REQUIREMENTS.get(cmd, "admin")
            if not _role_ok(user.role, required):
                return f"Permission denied. '{cmd}' requires {required} role (you have {user.role})."

            try:
                handler = _HANDLERS.get(cmd)
                if handler is None:
                    return f"Unknown command /{cmd}. Try /help."
                return await handler(args, db)
            except Exception as exc:
                logger.exception("Command handler /%s failed", cmd)
                return f"Error executing /{cmd}: {exc}"


# ---------------------------------------------------------------------------
# Handlers — each receives (args: list[str], db: AsyncSession) → str
# ---------------------------------------------------------------------------


async def _handle_status(args: list[str], db) -> str:
    from ..models_db import FleetStatusLog

    cutoff = _utcnow() - timedelta(minutes=5)
    # The sampler writes ~1 row/device/minute, so grouping-and-counting raw rows
    # over the window ~5x-overcounts devices. Reduce to the latest row per device
    # first (order device_id, timestamp desc → first seen is newest), then count.
    rows = (
        await db.execute(
            select(FleetStatusLog.device_id, FleetStatusLog.state)
            .where(FleetStatusLog.timestamp >= cutoff)
            .order_by(FleetStatusLog.device_id, FleetStatusLog.timestamp.desc())
        )
    ).fetchall()

    seen: set[str] = set()
    counts: dict[str, int] = {}
    for r in rows:
        if r[0] in seen:
            continue
        seen.add(r[0])
        counts[r[1]] = counts.get(r[1], 0) + 1

    online = counts.get("idle", 0) + counts.get("printing", 0) + counts.get("running", 0)
    error = counts.get("error", 0)
    offline = counts.get("offline", 0)
    total = online + error + offline or 1

    return (
        f"Fleet status (last 5 min)\n"
        f"  Online : {online}\n"
        f"  Error  : {error}\n"
        f"  Offline: {offline}\n"
        f"  Total  : {total}"
    )


async def _handle_machines(args: list[str], db) -> str:
    from sqlalchemy import func as sqlfunc
    from ..models_db import FleetStatusLog

    cutoff = _utcnow() - timedelta(minutes=5)
    # DISTINCT ON is Postgres-only (CompileError on SQLite). Order by
    # device_id, timestamp desc and dedupe in Python — the first row seen per
    # device is its latest status. Dialect-portable.
    rows = (
        await db.execute(
            select(
                FleetStatusLog.device_id,
                FleetStatusLog.state,
                FleetStatusLog.online,
            )
            .where(FleetStatusLog.timestamp >= cutoff)
            .order_by(FleetStatusLog.device_id, FleetStatusLog.timestamp.desc())
        )
    ).fetchall()

    seen: set[str] = set()
    latest = []
    for r in rows:
        if r[0] in seen:
            continue
        seen.add(r[0])
        latest.append(r)

    if not latest:
        return "No device data available."

    lines = ["Device status:"]
    for r in latest:
        status = "✅" if r[2] else "❌"
        lines.append(f"  {status} {r[0]}  [{r[1]}]")
    return "\n".join(lines)


async def _handle_machine(args: list[str], db) -> str:
    if not args:
        return "Usage: /machine <device_id>"

    device_id = args[0]
    from ..models_db import FleetStatusLog, JobLog, AnomalyAck

    cutoff = _utcnow() - timedelta(minutes=10)
    latest = (
        await db.execute(
            select(FleetStatusLog)
            .where(
                FleetStatusLog.device_id == device_id,
                FleetStatusLog.timestamp >= cutoff,
            )
            .order_by(FleetStatusLog.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest is None:
        return f"No recent data for device '{device_id}'."

    last_job = (
        await db.execute(
            select(JobLog)
            .where(JobLog.device_id == device_id)
            .order_by(JobLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    acks = (
        await db.execute(
            select(AnomalyAck).where(AnomalyAck.device_id == device_id)
        )
    ).scalars().all()

    lines = [
        f"Device: {device_id}",
        f"  State : {latest.state}",
        f"  Online: {'yes' if latest.online else 'no'}",
        f"  Seen  : {latest.timestamp.isoformat(timespec='seconds')}Z",
    ]
    if last_job:
        lines.append(f"  Last job: {last_job.job_name or 'N/A'} [{last_job.status}]")
        if last_job.oee is not None:
            lines.append(f"  OEE: {last_job.oee * 100:.1f}%")
    if acks:
        lines.append(f"  Acked anomalies: {', '.join(a.code for a in acks)}")
    return "\n".join(lines)


async def _handle_jobs(args: list[str], db) -> str:
    from ..models_db import JobLog

    device_filter = args[0] if args else None
    stmt = select(JobLog).order_by(JobLog.created_at.desc()).limit(10)
    if device_filter:
        stmt = stmt.where(JobLog.device_id == device_filter)

    rows = (await db.execute(stmt)).scalars().all()

    if not rows:
        return "No job history found."

    lines = ["Recent jobs:"]
    for r in rows:
        oee_str = f" OEE={r.oee * 100:.0f}%" if r.oee else ""
        lines.append(f"  [{r.status}] {r.device_id} — {r.job_name or 'N/A'}{oee_str}")
    return "\n".join(lines)


async def _handle_alerts(args: list[str], db) -> str:
    from ..models_db import AnomalyAck

    acks = (await db.execute(select(AnomalyAck))).scalars().all()

    if not acks:
        return "No active acknowledged anomalies."

    lines = ["Active anomalies (acked):"]
    for a in acks:
        lines.append(f"  {a.device_id}: {a.code} (acked {a.acked_at.isoformat(timespec='seconds')}Z)")
    return "\n".join(lines)


async def _handle_ack(args: list[str], db) -> str:
    if len(args) < 2:
        return "Usage: /ack <device_id> <anomaly_code>"

    device_id, code = args[0], args[1]
    from ..models_db import AnomalyAck
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    existing = (
        await db.execute(
            select(AnomalyAck).where(
                AnomalyAck.device_id == device_id,
                AnomalyAck.code == code,
            )
        )
    ).scalar_one_or_none()

    if existing:
        return f"Already acked: {device_id}/{code}"

    db.add(AnomalyAck(device_id=device_id, code=code))
    await db.commit()
    return f"Acked anomaly '{code}' on {device_id}."


async def _handle_help(args: list[str], db) -> str:
    return (
        "MEMAR commands:\n"
        "  /status           — Fleet summary\n"
        "  /machines         — All device states\n"
        "  /machine <id>     — Device detail\n"
        "  /jobs [device]    — Last 10 jobs\n"
        "  /alerts           — Active anomalies\n"
        "  /ack <id> <code>  — Acknowledge anomaly (operator+)\n"
        "  /help             — This message"
    )


_HANDLERS: dict[str, object] = {
    "status": _handle_status,
    "machines": _handle_machines,
    "machine": _handle_machine,
    "jobs": _handle_jobs,
    "alerts": _handle_alerts,
    "ack": _handle_ack,
    "help": _handle_help,
}
