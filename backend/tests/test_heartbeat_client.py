"""License heartbeat client — proves auto-refresh while active, HOLD when
inactive/unreachable, and that air-gap (perpetual) licenses never phone home."""
from datetime import date, timedelta

import pytest

import app.license as licmod
import app.license_client as lc
from app.license import LicenseState, _run_license_heartbeat, _tier_to_features


def _paid_state(expires_at=None):
    # Relative expiry: a hard-coded date silently turns this into an EXPIRED
    # license once it passes (get_license() demotes to free and the heartbeat
    # returns before fetching — which also made the HOLD tests pass vacuously).
    if expires_at is None:
        expires_at = (date.today() + timedelta(days=60)).isoformat()
    licmod._state = LicenseState(tier="pro", device_limit=40, expires_at=expires_at,
                                 features=_tier_to_features("pro"), customer_id="cus_x", active=True)


@pytest.mark.asyncio
async def test_active_applies_and_persists_fresh_key(monkeypatch):
    _paid_state()
    monkeypatch.setenv("MEMAR_LICENSE_KEY", "current-key")
    seen = {}

    async def fake_fetch(url, key, timeout=10.0):
        seen["sent_key"] = key
        return {"active": True, "license_key": "FRESH", "expires_at": "2026-08-01"}

    def fake_apply(k):
        seen["applied"] = k
        return True

    async def fake_persist(k):
        seen["persisted"] = k

    monkeypatch.setattr(lc, "fetch_license_status", fake_fetch)
    monkeypatch.setattr(licmod, "apply_license", fake_apply)
    monkeypatch.setattr(licmod, "_persist_refreshed_key", fake_persist)
    try:
        await _run_license_heartbeat("http://hb")
        assert seen["sent_key"] == "current-key"
        assert seen["applied"] == "FRESH" and seen["persisted"] == "FRESH"
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_inactive_holds_current_key(monkeypatch):
    _paid_state()
    monkeypatch.setenv("MEMAR_LICENSE_KEY", "current-key")
    applied = []

    async def fake_fetch(url, key, timeout=10.0):
        return {"active": False, "reason": "no_active_subscription"}

    monkeypatch.setattr(lc, "fetch_license_status", fake_fetch)
    monkeypatch.setattr(licmod, "apply_license", lambda k: applied.append(k) or True)
    try:
        await _run_license_heartbeat("http://hb")
        assert applied == []  # held — the key lapses on its own embedded expiry
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_unreachable_holds_current_key(monkeypatch):
    _paid_state()
    monkeypatch.setenv("MEMAR_LICENSE_KEY", "current-key")
    applied = []

    async def fake_fetch(url, key, timeout=10.0):
        return None  # network/HTTP failure

    monkeypatch.setattr(lc, "fetch_license_status", fake_fetch)
    monkeypatch.setattr(licmod, "apply_license", lambda k: applied.append(k) or True)
    try:
        await _run_license_heartbeat("http://hb")
        assert applied == []  # never downgrades a payer on our outage
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_airgap_perpetual_never_phones_home(monkeypatch):
    # expires_at=None → air-gap perpetual license
    licmod._state = LicenseState(tier="enterprise", device_limit=100000, expires_at=None,
                                 features=_tier_to_features("enterprise"), customer_id="cus_air", active=True)
    fetched = []
    monkeypatch.setattr(lc, "fetch_license_status",
                        lambda *a, **k: fetched.append(1))
    try:
        await _run_license_heartbeat("http://hb")
        assert fetched == []  # air-gap → no outbound call at all
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_airgap_timeboxed_never_phones_home(monkeypatch):
    """Air-gap keys are sold time-boxed (12-month expiry), so expires_at is NOT
    None — they must still make zero egress (renewal is a new key file handed
    over out-of-band). This is the claim the /security page makes; if the skip
    only fired on perpetual keys, a default air-gap deploy would phone home."""
    licmod._state = LicenseState(tier="airgap", device_limit=500, expires_at="2027-06-29",
                                 features=_tier_to_features("airgap"), customer_id="cus_defense", active=True)
    monkeypatch.setenv("MEMAR_LICENSE_KEY", "airgap-key")
    fetched = []
    monkeypatch.setattr(lc, "fetch_license_status",
                        lambda *a, **k: fetched.append(1))
    try:
        await _run_license_heartbeat("http://hb")
        assert fetched == []  # tier == airgap → no outbound call, expiry notwithstanding
    finally:
        licmod._state = None


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["airgap_standard", "airgap_enterprise"])
async def test_real_airgap_billing_tiers_never_phone_home(monkeypatch, tier):
    """Regression: the skip-check previously compared state.tier == 'airgap'
    literally, but real purchases (billing.py) only ever produce
    'airgap_standard'/'airgap_enterprise' — the check never matched a real
    air-gap license, so if MEMAR_LICENSE_HEARTBEAT_URL were ever set, a real
    paying air-gap customer's key would phone home despite the documented
    'never phone home' guarantee."""
    licmod._state = LicenseState(tier=tier, device_limit=9999, expires_at="2027-06-29",
                                 features=_tier_to_features(tier), customer_id="cus_defense", active=True)
    monkeypatch.setenv("MEMAR_LICENSE_KEY", "airgap-key")
    fetched = []
    monkeypatch.setattr(lc, "fetch_license_status",
                        lambda *a, **k: fetched.append(1))
    try:
        await _run_license_heartbeat("http://hb")
        assert fetched == []
    finally:
        licmod._state = None
