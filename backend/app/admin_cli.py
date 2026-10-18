"""`memar` command-line helpers for the owner.

    python -m app.admin_cli status        claimed?, mode, address
    python -m app.admin_cli setup-link    print the setup link (exit 3 if already set up)
    python -m app.admin_cli reset-admin   remove all accounts, reopen browser setup

Run with the same environment as the server (MEMAR_DATA_DIR, MEMAR_DB_PATH).
The `memar` wrapper script does this for Docker and native installs.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

logging.disable(logging.WARNING)  # keep CLI output clean; errors still raise


async def _claimed() -> bool:
    from .auth import is_claimed
    from .db import AsyncSessionLocal, init_db

    await init_db()
    async with AsyncSessionLocal() as db:
        return await is_claimed(db)


def cmd_status() -> int:
    from . import firstrun

    claimed = asyncio.run(_claimed())
    print(f"claimed: {'yes' if claimed else 'no'}")
    print(f"setup mode: {firstrun.setup_mode()}")
    for label, url in firstrun.setup_links("XXXXXXXX"):
        print(f"{label.lower()}: {url.split('/setup')[0]}")
    return 0


def cmd_setup_link() -> int:
    from . import firstrun

    if asyncio.run(_claimed()):
        print("MEMAR is already set up. Sign in with your account.")
        print("Forgot the password? Run: memar reset-admin")
        return 3
    firstrun.print_setup_banner(firstrun.get_or_create_setup_code())
    return 0


async def _reset() -> None:
    from sqlalchemy import delete

    from .db import AsyncSessionLocal, init_db
    from .models_db import RefreshToken, User, WsTicket

    await init_db()
    async with AsyncSessionLocal() as db:
        await db.execute(delete(RefreshToken))
        await db.execute(delete(WsTicket))
        try:
            from .models_db import PasswordResetToken
            await db.execute(delete(PasswordResetToken))
        except ImportError:
            pass
        await db.execute(delete(User))
        await db.commit()


def cmd_reset_admin(assume_yes: bool) -> int:
    from . import firstrun

    if not assume_yes:
        if not sys.stdin.isatty():
            print("Refusing without confirmation. Re-run with --yes.", file=sys.stderr)
            return 2
        answer = input(
            "This removes ALL user accounts (devices and history are kept) and reopens "
            "browser setup. Continue? [y/N] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 1
    asyncio.run(_reset())
    code = firstrun.new_setup_code()
    print("All accounts removed. Devices and history are kept.")
    firstrun.print_setup_banner(code)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="memar", description="MEMAR owner commands")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="show whether setup is finished and where MEMAR is")
    sub.add_parser("setup-link", help="print the link that finishes setup in the browser")
    r = sub.add_parser("reset-admin", help="remove all accounts and reopen browser setup")
    r.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    a = p.parse_args(argv)
    if a.cmd == "status":
        return cmd_status()
    if a.cmd == "setup-link":
        return cmd_setup_link()
    return cmd_reset_admin(a.yes)


if __name__ == "__main__":
    sys.exit(main())
