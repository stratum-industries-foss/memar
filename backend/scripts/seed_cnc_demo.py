"""Keep the demo CNC device (cnc-demo-1) showing realistic, live-looking metrics.

The CNC metrics panel aggregates the last N minutes of cnc_metrics_log. A one-off
seed ages out of that window within ~1h, so a systemd timer re-runs this on a
schedule to keep the public demo populated. Idempotent: clears cnc-demo-1 rows
then inserts a fresh rolling ~55-minute window (UTC, matching the endpoint's
lookback). Demo-only: no-ops unless MEMAR_DEMO_MODE is set (override with --force).

Run with the service env so it hits the live DB:
    sudo -u memar env MEMAR_DB_PATH=/var/lib/memar/memar.db MEMAR_DEMO_MODE=1 \
        python3 scripts/seed_cnc_demo.py            # clear + reseed
    sudo -u memar env MEMAR_DB_PATH=/var/lib/memar/memar.db \
        python3 scripts/seed_cnc_demo.py --clear    # remove the demo rows only
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEVICE_ID = "cnc-demo-1"
SAMPLES = 110          # 110 × 30s ≈ 55 min, sits inside the 60-min aggregation window
INTERVAL_S = 30


async def _clear() -> int:
    from sqlalchemy import delete
    from app.db import AsyncSessionLocal
    from app.models_db import CNCMetricsLog
    async with AsyncSessionLocal() as db:
        r = await db.execute(delete(CNCMetricsLog).where(CNCMetricsLog.device_id == DEVICE_ID))
        await db.commit()
        return r.rowcount or 0


async def seed() -> int:
    from app.db import AsyncSessionLocal
    from app.models_db import CNCMetricsLog
    await _clear()
    now = datetime.utcnow()
    rows = []
    for i in range(SAMPLES):
        ts = now - timedelta(seconds=(SAMPLES - i) * INTERVAL_S)
        phase = i % 18
        if phase < 11:        # cutting
            state, spindle, feed, coolant = "printing", 16000 + (i % 5) * 900, 1800.0 + (i % 7) * 110, True
        elif phase < 14:      # rapid / reposition (spindle on, no cut feed)
            state, spindle, feed, coolant = "printing", 18000, 0.0, True
        else:                 # idle between ops
            state, spindle, feed, coolant = "ready", 0, 0.0, False
        tool_id = "T%02d" % (1 + (i // 37))   # T01 -> T02 -> T03 (2 tool changes)
        rows.append(CNCMetricsLog(
            device_id=DEVICE_ID, timestamp=ts, coolant_psi=None,
            coolant_active=coolant, spindle_rpm=spindle,
            feed_rate_mm_min=feed, machine_state=state, tool_id=tool_id,
        ))
    async with AsyncSessionLocal() as db:
        db.add_all(rows)
        await db.commit()
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed/refresh demo CNC telemetry for cnc-demo-1.")
    ap.add_argument("--clear", action="store_true", help="remove the demo rows and exit")
    ap.add_argument("--force", action="store_true", help="seed even when MEMAR_DEMO_MODE is unset")
    args = ap.parse_args()

    if args.clear:
        n = asyncio.run(_clear())
        print(f"cleared {n} cnc-demo rows")
        return

    demo = os.getenv("MEMAR_DEMO_MODE", "").lower() in ("1", "true", "yes")
    if not demo and not args.force:
        print("MEMAR_DEMO_MODE not set — skipping demo seed (use --force to override)")
        return

    n = asyncio.run(seed())
    print(f"seeded {n} cnc-demo rows for {DEVICE_ID}")


if __name__ == "__main__":
    main()
