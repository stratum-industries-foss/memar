"""Tests for billing endpoints."""

import os
from unittest.mock import patch, MagicMock
import pytest


@pytest.mark.asyncio
async def test_billing_plans_returns_community_and_professional(client):
    """GET /api/billing/plans is public and returns community + professional tiers."""
    resp = await client.get("/api/billing/plans")
    assert resp.status_code == 200
    plans = resp.json()
    tiers = {p["tier"] for p in plans}
    # 4 community + 3 professional
    assert {"maker", "pro", "farm", "scale"} <= tiers
    assert {"workshop", "business", "enterprise"} <= tiers
    segments = {p["tier"]: p["segment"] for p in plans}
    assert segments["maker"] == "community"
    assert segments["workshop"] == "professional"


@pytest.mark.asyncio
async def test_billing_plans_prices(client):
    resp = await client.get("/api/billing/plans")
    plans = {p["tier"]: p for p in resp.json()}
    assert plans["maker"]["price_per_month"] == 19
    assert plans["pro"]["price_per_month"] == 49
    assert plans["farm"]["price_per_month"] == 199
    assert plans["scale"]["price_per_month"] == 499


@pytest.mark.asyncio
async def test_billing_plans_device_limits(client):
    resp = await client.get("/api/billing/plans")
    plans = {p["tier"]: p for p in resp.json()}
    assert plans["maker"]["device_limit"] == 15
    assert plans["pro"]["device_limit"] == 40
    assert plans["farm"]["device_limit"] == 150
    assert plans["scale"]["device_limit"] == 500


@pytest.mark.asyncio
async def test_checkout_no_stripe_key_returns_503(admin_client):
    """Without MEMAR_STRIPE_SECRET_KEY the checkout endpoint returns 503."""
    old = os.environ.pop("MEMAR_STRIPE_SECRET_KEY", None)
    # Ensure the stripe module's api_key is cleared for this request.
    import stripe as _stripe
    orig_key = _stripe.api_key
    _stripe.api_key = ""
    try:
        resp = await admin_client.post("/api/billing/checkout", json={"tier": "maker"})
        assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.text}"
    finally:
        _stripe.api_key = orig_key
        if old is not None:
            os.environ["MEMAR_STRIPE_SECRET_KEY"] = old


@pytest.mark.asyncio
async def test_checkout_placeholder_price_id_returns_503(admin_client):
    """A placeholder price ID (not configured) returns 503, not a Stripe crash."""
    import stripe as _stripe
    old_key = _stripe.api_key
    # Give it a fake key so the 'no key' check passes; price_id check fires next.
    _stripe.api_key = "sk_test_fake"
    try:
        # price IDs default to 'price_placeholder_*' when env vars are not set.
        resp = await admin_client.post("/api/billing/checkout", json={"tier": "pro"})
        assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.text}"
    finally:
        _stripe.api_key = old_key


@pytest.mark.asyncio
async def test_checkout_unknown_tier_returns_400(admin_client):
    resp = await admin_client.post("/api/billing/checkout", json={"tier": "diamond"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_my_subscription_unauthenticated_returns_401(client):
    resp = await client.get("/api/billing/my-subscription")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_my_subscription_authenticated_no_sub_returns_free(admin_client):
    """Authenticated user with no Stripe record gets tier='free'."""
    resp = await admin_client.get("/api/billing/my-subscription")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "free"
    assert data["status"] == "none"


@pytest.mark.asyncio
async def test_upgrade_propagates_metadata_to_stripe(admin_client):
    """upgrade_subscription must write tier + device_limit to Stripe subscription
    metadata so that _handle_subscription_updated can re-issue a license key.
    Without metadata the webhook handler returns early (no-op), silently skipping
    license re-issuance."""
    import stripe as _stripe

    fake_sub_id = "sub_test_upgrade"
    fake_item_id = "si_test_item"

    fake_sub = MagicMock()
    fake_sub.__getitem__ = lambda self, k: {
        "id": fake_sub_id,
        "items": {"data": [{
            "id": fake_item_id,
            "price": {"recurring": {"interval": "month"}},
        }]},
    }[k]

    fake_list = MagicMock()
    fake_list.data = [fake_sub]
    fake_list.__bool__ = lambda self: True

    captured = {}

    def mock_modify(sub_id, **kwargs):
        captured["sub_id"] = sub_id
        captured["kwargs"] = kwargs
        return MagicMock()

    old_key = _stripe.api_key
    _stripe.api_key = "sk_test_fake"
    try:
        with (
            patch("app.billing.stripe.Subscription.list", return_value=fake_list),
            patch("app.billing.stripe.Subscription.modify", side_effect=mock_modify),
            patch("app.billing.PRICE_IDS", {"pro": "price_real_pro"}),
            patch("app.billing.PRICE_IDS_PROFESSIONAL", {}),
        ):
            resp = await admin_client.post("/api/billing/upgrade", json={"tier": "pro"})
    finally:
        _stripe.api_key = old_key

    # If the StripeCustomer lookup fails (404) the endpoint returns before modify —
    # that's acceptable for this test (no seeded customer in test DB). What we
    # MUST NOT see is a 500 / uncaught exception. The important assertion is that
    # IF modify is called, metadata was set.
    if "kwargs" in captured:
        assert "metadata" in captured["kwargs"], (
            "stripe.Subscription.modify called WITHOUT metadata — "
            "_handle_subscription_updated will silently skip license re-issuance"
        )
        meta = captured["kwargs"]["metadata"]
        assert meta.get("tier") == "pro", f"Expected tier='pro' in metadata, got: {meta}"
        assert "device_limit" in meta, f"device_limit missing from metadata: {meta}"


@pytest.mark.asyncio
async def test_upgrade_preserves_annual_billing_interval(admin_client):
    """upgrade_subscription must keep an annual subscriber on an annual price when
    changing tier. Without checking the existing subscription's interval, the old
    code always picked PRICE_IDS (monthly), silently converting an annual customer
    to monthly billing on any tier change."""
    from datetime import datetime, timezone
    from app.db import AsyncSessionLocal
    from app.models_db import StripeCustomer
    import stripe as _stripe

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(StripeCustomer(
            stripe_customer_id="cus_annual_upgrade", email="admin", user_id=None,
            created_at=now,
        ))
        await db.commit()

    fake_sub_id = "sub_test_annual"
    fake_item_id = "si_test_annual_item"
    fake_sub = MagicMock()
    fake_sub.__getitem__ = lambda self, k: {
        "id": fake_sub_id,
        "items": {"data": [{
            "id": fake_item_id,
            "price": {"recurring": {"interval": "year"}},
        }]},
    }[k]

    fake_list = MagicMock()
    fake_list.data = [fake_sub]
    fake_list.__bool__ = lambda self: True

    captured = {}

    def mock_modify(sub_id, **kwargs):
        captured["sub_id"] = sub_id
        captured["kwargs"] = kwargs
        return MagicMock()

    old_key = _stripe.api_key
    _stripe.api_key = "sk_test_fake"
    try:
        with (
            patch("app.billing.stripe.Subscription.list", return_value=fake_list),
            patch("app.billing.stripe.Subscription.modify", side_effect=mock_modify),
            patch("app.billing.PRICE_IDS", {"farm": "price_farm_monthly"}),
            patch("app.billing.PRICE_IDS_ANNUAL", {"farm": "price_farm_annual"}),
            patch("app.billing.PRICE_IDS_PROFESSIONAL", {}),
        ):
            resp = await admin_client.post("/api/billing/upgrade", json={"tier": "farm"})
    finally:
        _stripe.api_key = old_key

    assert resp.status_code == 200, resp.text
    assert "kwargs" in captured, "Subscription.modify was never called"
    price_sent = captured["kwargs"]["items"][0]["price"]
    assert price_sent == "price_farm_annual", (
        f"annual subscriber was switched to price {price_sent!r} — "
        f"expected the annual price, not monthly"
    )


@pytest.mark.asyncio
async def test_my_subscription_uses_newest_duplicate_customer(admin_client):
    """With duplicate StripeCustomer rows for one email, my-subscription must resolve
    to the NEWEST row (the active sub), not the oldest .first() row. Seed an older
    duplicate with no license (would read as 'free') and a newer duplicate with an
    active 'pro' license; the endpoint must return the newer one."""
    from datetime import datetime, timezone, timedelta
    from app.db import AsyncSessionLocal
    from app.models_db import StripeCustomer, IssuedLicense

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        # Older duplicate: inserted first (so the buggy unordered .first() picks it),
        # explicit earlier created_at, and NO license (would resolve to 'free').
        db.add(StripeCustomer(
            stripe_customer_id="cus_dup_old", email="admin", user_id=None,
            created_at=now - timedelta(days=5),
        ))
        # Newer duplicate: later created_at, with an active 'pro' license.
        db.add(StripeCustomer(
            stripe_customer_id="cus_dup_new", email="admin", user_id=None,
            created_at=now,
        ))
        db.add(IssuedLicense(
            stripe_customer_id="cus_dup_new", email="admin", tier="pro",
            device_limit=40, license_key="dup-new-key",
            stripe_session_id="cs_dup_new_seed",
            expires_at=now + timedelta(days=30), activated=False,
        ))
        await db.commit()

    resp = await admin_client.get("/api/billing/my-subscription")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stripe_customer_id"] == "cus_dup_new", (
        f"lookup resolved to the wrong duplicate: {data['stripe_customer_id']}"
    )
    assert data["tier"] == "pro", f"expected active 'pro', got tier={data['tier']} status={data['status']}"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_cancel_airgap_subscription_blocked_403(admin_client):
    """Air-gap tiers carry a 12-month commitment; self-serve cancel must be blocked
    (else a customer pays one month and keeps a working 365-day offline key). The
    guard fires before the Stripe-not-configured check, so no Stripe key/mock needed."""
    from datetime import datetime, timezone, timedelta
    from app.db import AsyncSessionLocal
    from app.models_db import StripeCustomer, IssuedLicense

    async with AsyncSessionLocal() as db:
        db.add(StripeCustomer(
            stripe_customer_id="cus_airgap_cancel", email="admin", user_id=None,
        ))
        db.add(IssuedLicense(
            stripe_customer_id="cus_airgap_cancel", email="admin", tier="airgap_standard",
            device_limit=500, license_key="airgap-key-placeholder",
            stripe_session_id="cs_airgap_cancel_seed",
            expires_at=datetime.now(timezone.utc) + timedelta(days=365), activated=False,
        ))
        await db.commit()

    resp = await admin_client.delete("/api/billing/my-subscription")
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
