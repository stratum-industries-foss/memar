"""White-label branding — proves the Scale 'White-label' claim is real and that
branding can NEVER leak after a downgrade (defaults unless custom_branding is live)."""
import pytest

import app.license as licmod
from app.license import LicenseState, _tier_to_features


def _set_tier(tier: str) -> None:
    licmod._state = LicenseState(tier=tier, device_limit=150, expires_at="2099-01-01",
                                 features=_tier_to_features(tier), customer_id="c", active=True)


@pytest.mark.asyncio
async def test_branding_defaults_without_license(admin_client):
    try:
        licmod._state = None  # free
        b = (await admin_client.get("/api/branding")).json()
        assert b["company_name"] == "MEMAR" and b["custom"] is False
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_branding_put_gated_by_inactive_license(admin_client):
    try:
        # custom_branding is on every tier now — an INACTIVE license must still 402.
        licmod._state = LicenseState(tier="scale", device_limit=500, expires_at="2099-01-01",
                                     features=_tier_to_features("scale"), customer_id="c", active=False)
        r = await admin_client.put("/api/admin/branding", json={"company_name": "Acme"})
        assert r.status_code == 402
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_branding_set_and_get_with_license(admin_client):
    try:
        _set_tier("scale")  # custom_branding present
        r = await admin_client.put("/api/admin/branding",
                                   json={"company_name": "Acme Mfg", "primary_color": "#ff0000"})
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["company_name"] == "Acme Mfg" and b["primary_color"] == "#ff0000" and b["custom"] is True
        g = (await admin_client.get("/api/branding")).json()
        assert g["company_name"] == "Acme Mfg"
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_branding_hidden_when_license_inactive(admin_client):
    """A brand set while licensed must fall back to MEMAR once the license lapses —
    never a half-rebranded instance. (get_effective_branding gates on lic.active.)"""
    try:
        _set_tier("scale")
        await admin_client.put("/api/admin/branding", json={"company_name": "Acme Mfg"})
        # license lapses (expired/revoked) — branding must disappear immediately.
        licmod._state = LicenseState(tier="scale", device_limit=500, expires_at="2099-01-01",
                                     features=_tier_to_features("scale"), customer_id="c", active=False)
        g = (await admin_client.get("/api/branding")).json()
        assert g["company_name"] == "MEMAR" and g["custom"] is False
    finally:
        licmod._state = None
