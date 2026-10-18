"""Tamper evidence for the audit log.

Every audit row carries row_hash = SHA-256 over its own fields and the previous
row's hash (prev_hash). Changing or deleting any chained row changes its hash,
which no longer matches the next row's prev_hash, so verify_chain() reports the
first break. Rows written before the chain existed have NULL hashes and are
reported as "unchained"; they are not treated as tampering.

Limits (stated plainly): the chain shows that rows were altered or removed
after they were written. It does not stop someone with database access from
rewriting the whole chain from the first row, unless the head hash is anchored
somewhere that user cannot write (see the head endpoint and the export, which
carries the head so an external copy can be compared).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models_db import AuditLog

GENESIS = "0" * 64
_chain_lock = asyncio.Lock()


def _canonical(row: AuditLog) -> str:
    """Stable text form of a row's content. Timestamps are stored at second
    precision so the value survives the database round-trip unchanged."""
    created = row.created_at.replace(microsecond=0).isoformat() if row.created_at else ""
    payload = {
        "user_id": row.user_id,
        "username": row.username,
        "action": row.action,
        "resource": row.resource,
        "detail": row.detail,
        "ip_address": row.ip_address,
        "created_at": created,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(row: AuditLog, prev_hash: str) -> str:
    return hashlib.sha256((prev_hash + "|" + _canonical(row)).encode("utf-8")).hexdigest()


async def append_chained(db: AsyncSession, row: AuditLog) -> None:
    """Add row to the session with its chain fields set. Caller commits.
    Serialized so two concurrent events cannot both take the same prev_hash."""
    async with _chain_lock:
        last = (await db.execute(
            select(AuditLog.row_hash)
            .where(AuditLog.row_hash.isnot(None))
            .order_by(AuditLog.id.desc())
            .limit(1)
        )).scalar_one_or_none()
        prev = last or GENESIS
        row.prev_hash = prev
        db.add(row)
        await db.flush()  # assign created_at/id before hashing
        row.row_hash = compute_hash(row, prev)


@dataclass
class ChainReport:
    total: int
    chained: int
    unchained: int
    intact: bool
    first_break_id: int | None
    head: str | None

    def as_dict(self) -> dict:
        return {
            "total_rows": self.total,
            "chained_rows": self.chained,
            "unchained_rows": self.unchained,
            "intact": self.intact,
            "first_break_id": self.first_break_id,
            "head_hash": self.head,
        }


async def verify_chain(db: AsyncSession) -> ChainReport:
    rows = (await db.execute(select(AuditLog).order_by(AuditLog.id.asc()))).scalars().all()
    total = len(rows)
    chained = 0
    expected_prev: str | None = None
    head = None
    for row in rows:
        if row.row_hash is None:
            # Pre-chain rows: allowed only before the first chained row.
            if expected_prev is not None:
                return ChainReport(total, chained, total - chained, False, row.id, head)
            continue
        if expected_prev is None:
            expected_prev = GENESIS  # first chained row must chain from genesis
        if row.prev_hash != expected_prev or compute_hash(row, row.prev_hash) != row.row_hash:
            return ChainReport(total, chained, total - chained, False, row.id, head)
        chained += 1
        expected_prev = row.row_hash
        head = row.row_hash
    return ChainReport(total, chained, total - chained, True, None, head)
