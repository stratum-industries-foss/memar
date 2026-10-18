"""Regression tests for the adversarial-audit leftovers (docs/internal/AUDIT_20261016_firstrun.md)."""

import pytest

from app import auth
from app.onboarding_routes import _clean_remote_name


# #6 — names supplied by another device are text only, capped at 64 characters.
@pytest.mark.parametrize("raw,expected", [
    ("Ender 3", "Ender 3"),
    ("  padded  ", "padded"),
    ("bad\x00name\x07\x1b[31m", "badname[31m"),  # control characters removed; visible text kept
    ("A" * 500, "A" * 64),
    (None, ""),
    (12345, ""),
    ("<img src=x onerror=alert(1)>", "<img src=x onerror=alert(1)>"),  # kept as text; React escapes it
])
def test_remote_names_are_cleaned(raw, expected):
    assert _clean_remote_name(raw) == expected


# #8 — a password bcrypt would truncate is refused, not silently weakened.
def test_password_longer_than_72_bytes_is_refused():
    with pytest.raises(auth.PasswordTooLong):
        auth.hash_password("A" * 72 + "x")


def test_password_of_72_bytes_is_accepted_and_verifies():
    pw = "B" * 72
    assert auth.verify_password(pw, auth.hash_password(pw))


def test_multibyte_password_counts_bytes_not_characters():
    # 25 snowmen = 75 bytes: over the limit even though it is 25 characters.
    with pytest.raises(auth.PasswordTooLong):
        auth.hash_password("\u2603" * 25)


# #7 — a second scan while one is running is refused with 429.
@pytest.mark.asyncio
async def test_second_scan_is_refused_while_one_runs(monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from app import onboarding_routes as orr

    ran = []

    async def _body(subnet):
        ran.append(subnet)
        await asyncio.sleep(0.2)
        return None

    monkeypatch.setattr(orr, "_scan_network_locked", _body)
    first = asyncio.create_task(orr.scan_network(subnet=None))
    await asyncio.sleep(0.01)
    with pytest.raises(HTTPException) as err:
        await orr.scan_network(subnet=None)
    assert err.value.status_code == 429
    await first
    assert ran == [None]


# #15 — billing's expiring_soon uses the same window as the banner.
def test_billing_window_constants_match_the_banner():
    from app import billing
    assert billing.RENEWAL_WARNING_DAYS_ONLINE == 7
    assert billing.RENEWAL_WARNING_DAYS_AIRGAP == 30
