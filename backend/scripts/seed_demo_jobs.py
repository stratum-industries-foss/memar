"""Seed clearly-synthetic demo jobs into JobLog so the analytics trends
(throughput / error-rate / OEE 7-day) show realistic data for demos & marketing
without waiting on real prints.

Every row's job_name is prefixed with "[demo] " — a cleanup marker only (JobLog
job_name is never shown in the analytics UI, which renders aggregates). The seed
is idempotent: it removes prior "[demo]" rows before inserting, and can be wiped
with --clear. The live "Fleet OEE" headline still comes from Moonraker history;
this only fills the DB-backed trend/throughput/error widgets.

Run with the service env so it hits the live DB, e.g. on the host:
    sudo -u memar env MEMAR_DB_PATH=/var/lib/memar/memar.db \
        ../.venv/bin/python3 scripts/seed_demo_jobs.py            # clear + reseed
    sudo -u memar env MEMAR_DB_PATH=/var/lib/memar/memar.db \
        ../.venv/bin/python3 scripts/seed_demo_jobs.py --clear    # remove seed only
"""
import argparse
import asyncio
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TAG = "[demo] "
PARTS = [
    "hull_bracket_v3", "exhaust_manifold", "nozzle_spacer_x4", "gimbal_mount",
    "sensor_housing", "cable_clip_v2", "drone_arm_L", "vent_duct_90",
    "battery_tray", "tool_holder", "pump_impeller", "hinge_block",
]
FAIL_REASONS = [
    "thermal runaway", "filament runout", "first-layer adhesion",
    "layer shift", "nozzle clog", "power loss",
]


async def _clear_seed() -> int:
    from sqlalchemy import delete
    from app.db import AsyncSessionLocal
    from app.models_db import JobLog
    async with AsyncSessionLocal() as db:
        # SQLite LIKE treats '[' literally, so this matches only the "[demo] " prefix.
        r = await db.execute(delete(JobLog).where(JobLog.job_name.like(TAG.strip() + "%")))
        await db.commit()
        return r.rowcount or 0


async def seed(days: int, per_day: int, rng_seed: int) -> tuple[int, int]:
    from app.config import get_config
    from app.db import AsyncSessionLocal
    from app.models_db import JobLog

    rng = random.Random(rng_seed)
    pids = [p.id for p in get_config().printers if p.enabled] or ["printer-1"]
    now = datetime.utcnow()

    rows = []
    for d in range(days):
        day_base = now - timedelta(days=d)
        # Slightly improving OEE toward the present (older days a touch lower).
        base_oee = 0.86 + (days - 1 - d) / max(1, days - 1) * 0.05  # ~0.86 -> ~0.91
        n = max(1, per_day + rng.randint(-2, 2))
        for _ in range(n):
            ts = day_base - timedelta(seconds=rng.randint(0, 86_000))
            roll = rng.random()
            if roll < 0.07:
                status, oee, reason = "failed", 0.0, rng.choice(FAIL_REASONS)
            elif roll < 0.12:
                status, oee, reason = "cancelled", None, None
            else:
                status = "completed"
                oee = round(min(0.97, max(0.62, rng.gauss(base_oee, 0.04))), 4)
                reason = None
            rows.append(JobLog(
                device_id=rng.choice(pids),
                job_name=TAG + rng.choice(PARTS) + ".gcode",
                status=status,
                failure_reason=reason,
                oee=oee,
                created_at=ts,
                ended_at=ts,
                duration_s=rng.randint(1200, 21_600),
            ))

    cleared = await _clear_seed()
    async with AsyncSessionLocal() as db:
        db.add_all(rows)
        await db.commit()
    return cleared, len(rows)


async def _main() -> None:
    ap = argparse.ArgumentParser(description="Seed/clear synthetic demo JobLog rows.")
    ap.add_argument("--clear", action="store_true", help="remove seed rows and exit")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--per-day", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    if args.clear:
        n = await _clear_seed()
        print(f"cleared {n} '[demo]' job rows")
        return
    cleared, inserted = await seed(args.days, args.per_day, args.seed)
    print(f"cleared {cleared} stale seed rows; inserted {inserted} '[demo]' jobs over {args.days}d")


if __name__ == "__main__":
    asyncio.run(_main())
