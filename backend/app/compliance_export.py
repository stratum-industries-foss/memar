"""Compliance export: the audit trail as a file an auditor can check.

GET /api/admin/audit/export?format=csv|json&limit=N
Admin only, and requires the audit_logs feature (Pro and above).

Each row carries its chain fields, and the file header states the chain head and
whether the chain verified when it was produced. An auditor can recompute the
row hashes from the exported fields (see the canonical form in audit_chain.py)
and compare the head with a copy kept elsewhere. The export contains only real
audit rows; nothing is generated or sample data.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from fastapi import Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import audit_router
from .audit_chain import verify_chain
from .db import get_db
from .deps import require_feature, require_role
from .models_db import AuditLog

FIELDS = [
    "id", "created_at", "user_id", "username", "action", "resource",
    "detail", "ip_address", "prev_hash", "row_hash",
]


@audit_router.get("/audit/export")
async def export_audit(
    format: str = Query("csv", pattern="^(csv|json)$"),
    limit: int = Query(10000, ge=1, le=100000),
    _: dict = Depends(require_role("admin")),
    __: None = Depends(require_feature("compliance_export")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    report = await verify_chain(db)
    rows = (await db.execute(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    )).scalars().all()
    rows = list(reversed(rows))
    generated = datetime.now(timezone.utc).isoformat()
    header = {
        "generated_at": generated,
        "total_rows": report.total,
        "chained_rows": report.chained,
        "unchained_rows": report.unchained,
        "chain_intact": report.intact,
        "first_break_id": report.first_break_id,
        "chain_head": report.head,
        "rows_in_export": len(rows),
    }
    records = [
        {
            "id": r.id,
            "created_at": r.created_at.replace(microsecond=0).isoformat() if r.created_at else None,
            "user_id": r.user_id,
            "username": r.username,
            "action": r.action,
            "resource": r.resource,
            "detail": r.detail,
            "ip_address": r.ip_address,
            "prev_hash": r.prev_hash,
            "row_hash": r.row_hash,
        }
        for r in rows
    ]
    stamp = generated[:19].replace(":", "")
    if format == "json":
        body = json.dumps({"header": header, "records": records}, indent=2, ensure_ascii=False)
        return Response(
            body, media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="memar-audit-{stamp}.json"'},
        )
    buf = io.StringIO()
    buf.write("# " + json.dumps(header, ensure_ascii=False) + "\n")
    writer = csv.DictWriter(buf, fieldnames=FIELDS)
    writer.writeheader()
    for rec in records:
        writer.writerow(rec)
    return Response(
        buf.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="memar-audit-{stamp}.csv"'},
    )
