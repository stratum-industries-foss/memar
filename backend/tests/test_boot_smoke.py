"""Boot smoke test — the guard that was missing.

The whole audit started because the backend did not even import (main.py imported
a nonexistent `Printer`), yet was reported "green" off a frontend build. These
tests fail loudly if the app stops importing, a router stops mounting, or the
OpenAPI schema can't be generated — the cheapest possible insurance against a
silent boot breakage.
"""

import pytest

from app.main import app


def test_app_imports_and_has_routes():
    assert len(app.routes) > 0


def test_openapi_schema_generates():
    """If any route's models/signatures are broken, this raises."""
    schema = app.openapi()
    assert schema["openapi"]
    assert "paths" in schema and len(schema["paths"]) > 0


@pytest.mark.parametrize("path", [
    "/api/auth/login",
    "/api/printers",
    "/api/printers/add",
    "/api/license/status",
    "/api/license/upgrade-hint",
    "/api/billing/plans",
    "/api/billing/checkout",
    "/api/analytics/kpi",
    "/api/analytics/coolant-depletion",
    "/api/alerts/webhooks/",
    "/stripe/webhook",
])
def test_critical_route_is_registered(path):
    registered = {getattr(r, "path", None) for r in app.routes}
    assert path in registered, f"critical route {path} is not mounted"


@pytest.mark.asyncio
async def test_healthz_ok(client):
    resp = await client.get("/api/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_analytics_router_mounted_and_authed(auth_client, monkeypatch):
    """The analytics router (previously skipped due to a broken import) is mounted
    and its endpoints are auth-gated, license-gated ('oee', paid tiers only), and
    return data."""
    import app.license as licmod
    from app.license import LicenseState, _tier_to_features

    resp = await auth_client.get("/api/analytics/kpi")
    assert resp.status_code == 402  # free tier: feature-gated, not missing

    monkeypatch.setattr(licmod, "_state", LicenseState(
        tier="pro", device_limit=40, expires_at="2099-01-01",
        features=_tier_to_features("pro"), customer_id="c", active=True,
    ))
    resp = await auth_client.get("/api/analytics/kpi")
    assert resp.status_code == 200
    body = resp.json()
    assert "utilization" in body and "oee_trend" in body and "coolant" in body
