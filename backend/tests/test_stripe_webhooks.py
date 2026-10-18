"""Tests for P2 Stripe webhook handlers:
charge.refunded, charge.dispute.created,
invoice.payment_action_required, customer.subscription.paused.
"""

from app.timeutil import utcnow as _utcnow
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from app.db import AsyncSessionLocal
from app.models_db import IssuedLicense


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(event_type: str, obj: dict) -> dict:
    return {
        "id": f"evt_test_{event_type.replace('.', '_')}",
        "type": event_type,
        "data": {"object": obj},
    }


async def _post_webhook(client, event_type: str, obj: dict):
    """POST a fake signed webhook (signature check is mocked out)."""
    evt = _make_event(event_type, obj)
    with patch("app.stripe_webhook.stripe.Webhook.construct_event", return_value=evt), \
         patch.dict(os.environ, {"MEMAR_STRIPE_WEBHOOK_SECRET": "whsec_test"}):
        return await client.post(
            "/stripe/webhook",
            content=b"{}",
            headers={"stripe-signature": "t=0,v1=fake"},
        )


async def _seed_license(
    stripe_customer_id: str = "cus_test",
    email: str = "test@example.com",
    tier: str = "pro",
    days_remaining: int = 30,
) -> IssuedLicense:
    """Insert an IssuedLicense row into the test DB."""
    async with AsyncSessionLocal() as db:
        lic = IssuedLicense(
            stripe_customer_id=stripe_customer_id,
            email=email,
            tier=tier,
            device_limit=40,
            license_key="test-key-placeholder",
            stripe_session_id=f"cs_{stripe_customer_id}_seed",
            expires_at=datetime.now(timezone.utc) + timedelta(days=days_remaining),
        )
        db.add(lic)
        await db.commit()
        await db.refresh(lic)
        return lic


# ---------------------------------------------------------------------------
# charge.refunded
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_charge_refunded_full_expires_license(client):
    """Full refund marks the license expires_at to now."""
    await _seed_license(stripe_customer_id="cus_refund_full")

    charge = {
        "customer": "cus_refund_full",
        "amount": 4900,
        "amount_refunded": 4900,
        "refunded": True,
    }
    with patch("app.stripe_webhook.send_cancellation_email", new_callable=AsyncMock) as mock_cancel, \
         patch("app.stripe_webhook.send_alert", new_callable=AsyncMock):
        resp = await _post_webhook(client, "charge.refunded", charge)

    assert resp.status_code == 200

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(IssuedLicense).where(IssuedLicense.stripe_customer_id == "cus_refund_full")
        )
        lic = result.scalar_one()

    now = _utcnow()
    assert lic.expires_at <= now, "License should be expired after full refund"
    mock_cancel.assert_awaited_once()


@pytest.mark.asyncio
async def test_charge_refunded_partial_leaves_license_active(client):
    """Partial refund sends owner alert but does not touch expires_at."""
    await _seed_license(stripe_customer_id="cus_refund_partial")

    original_expiry = datetime.now(timezone.utc) + timedelta(days=30)

    charge = {
        "customer": "cus_refund_partial",
        "amount": 4900,
        "amount_refunded": 1000,
        "refunded": False,
    }
    with patch("app.stripe_webhook.send_cancellation_email", new_callable=AsyncMock) as mock_cancel, \
         patch("app.stripe_webhook.send_alert", new_callable=AsyncMock) as mock_alert:
        resp = await _post_webhook(client, "charge.refunded", charge)

    assert resp.status_code == 200
    mock_cancel.assert_not_awaited()
    mock_alert.assert_awaited_once()

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(IssuedLicense).where(IssuedLicense.stripe_customer_id == "cus_refund_partial")
        )
        lic = result.scalar_one()

    assert lic.expires_at > _utcnow(), "License should still be active after partial refund"


@pytest.mark.asyncio
async def test_charge_refunded_no_customer_is_noop(client):
    """charge.refunded with no customer field is silently ignored."""
    charge = {"amount": 1000, "amount_refunded": 1000, "refunded": True}
    with patch("app.stripe_webhook.send_alert", new_callable=AsyncMock) as mock_alert:
        resp = await _post_webhook(client, "charge.refunded", charge)
    assert resp.status_code == 200
    mock_alert.assert_not_awaited()


# ---------------------------------------------------------------------------
# charge.dispute.created
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_charge_dispute_sends_owner_alert(client):
    """Dispute event triggers an alert to the owner (no access change)."""
    await _seed_license(stripe_customer_id="cus_dispute")

    fake_charge = MagicMock()
    fake_charge.get = lambda key, default=None: {"customer": "cus_dispute"}.get(key, default)

    dispute = {
        "charge": "ch_test_dispute",
        "reason": "fraudulent",
        "amount": 4900,
    }
    with patch("app.stripe_webhook.stripe.Charge.retrieve", return_value=fake_charge), \
         patch("app.stripe_webhook.send_alert", new_callable=AsyncMock) as mock_alert:
        resp = await _post_webhook(client, "charge.dispute.created", dispute)

    assert resp.status_code == 200
    mock_alert.assert_awaited_once()
    alert_subject = mock_alert.call_args.kwargs.get("subject", mock_alert.call_args.args[0] if mock_alert.call_args.args else "")
    assert "Dispute" in alert_subject or "dispute" in alert_subject.lower()


@pytest.mark.asyncio
async def test_charge_dispute_charge_retrieve_failure_is_nonfatal(client):
    """If Stripe charge retrieval fails, dispute handler still sends alert."""
    dispute = {
        "charge": "ch_unreachable",
        "reason": "unrecognized",
        "amount": 1000,
    }
    with patch("app.stripe_webhook.stripe.Charge.retrieve", side_effect=Exception("network error")), \
         patch("app.stripe_webhook.send_alert", new_callable=AsyncMock) as mock_alert:
        resp = await _post_webhook(client, "charge.dispute.created", dispute)

    assert resp.status_code == 200
    mock_alert.assert_awaited_once()


# ---------------------------------------------------------------------------
# invoice.payment_action_required
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invoice_action_required_emails_customer(client):
    """Action required event sends email to the customer's address."""
    invoice = {
        "customer": "cus_action",
        "customer_email": "customer@example.com",
        "hosted_invoice_url": "https://invoice.stripe.com/i/test",
    }
    with patch("app.stripe_webhook.send_alert", new_callable=AsyncMock) as mock_alert:
        resp = await _post_webhook(client, "invoice.payment_action_required", invoice)

    assert resp.status_code == 200
    mock_alert.assert_awaited_once()
    call_kwargs = mock_alert.call_args.kwargs
    assert call_kwargs.get("to") == "customer@example.com"


@pytest.mark.asyncio
async def test_invoice_action_required_falls_back_to_license_email(client):
    """If invoice lacks customer_email, falls back to license record email."""
    await _seed_license(stripe_customer_id="cus_action_fallback", email="license@example.com")

    invoice = {
        "customer": "cus_action_fallback",
        # no customer_email field
        "hosted_invoice_url": "https://invoice.stripe.com/i/test",
    }
    with patch("app.stripe_webhook.send_alert", new_callable=AsyncMock) as mock_alert:
        resp = await _post_webhook(client, "invoice.payment_action_required", invoice)

    assert resp.status_code == 200
    mock_alert.assert_awaited_once()
    call_kwargs = mock_alert.call_args.kwargs
    assert call_kwargs.get("to") == "license@example.com"


# ---------------------------------------------------------------------------
# customer.subscription.paused
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_paused_expires_license(client):
    """Paused subscription marks license(s) expired and sends cancellation email."""
    await _seed_license(stripe_customer_id="cus_paused", days_remaining=20)

    subscription = {"customer": "cus_paused"}

    with patch("app.stripe_webhook.send_cancellation_email", new_callable=AsyncMock) as mock_cancel:
        resp = await _post_webhook(client, "customer.subscription.paused", subscription)

    assert resp.status_code == 200
    mock_cancel.assert_awaited_once()

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(IssuedLicense).where(IssuedLicense.stripe_customer_id == "cus_paused")
        )
        lic = result.scalar_one()

    assert lic.expires_at <= _utcnow(), "License should be expired after subscription pause"


@pytest.mark.asyncio
async def test_subscription_paused_no_license_is_noop(client):
    """Paused subscription for unknown customer is idempotent (no crash)."""
    subscription = {"customer": "cus_nobody"}
    with patch("app.stripe_webhook.send_cancellation_email", new_callable=AsyncMock) as mock_cancel:
        resp = await _post_webhook(client, "customer.subscription.paused", subscription)
    assert resp.status_code == 200
    mock_cancel.assert_not_awaited()
