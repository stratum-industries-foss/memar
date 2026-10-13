"""BACKEND-CORE-BLOCKING-02: billing routes previously called the synchronous
Stripe SDK directly inside async route handlers — blocking the WHOLE event
loop (every other concurrent request on this process) for the duration of
the Stripe HTTP round-trip. asyncio.to_thread offloads that call to a worker
thread instead.

This can't be verified by an output-equality test (the response is identical
either way) — the only observable difference is whether the event loop stays
responsive during the call. Fire TWO concurrent requests that each need one
"Stripe" round-trip: if the call blocks the loop, the two round-trips can't
overlap and total wall time is ~2x a single call's duration; if it's
offloaded to a worker thread, both overlap and total wall time stays close
to 1x.
"""
import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import stripe as _stripe

BLOCK_SECONDS = 0.3


async def _seed_active_license():
    from app.db import AsyncSessionLocal
    from app.models_db import IssuedLicense, StripeCustomer

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(StripeCustomer(stripe_customer_id="cus_evloop_test", email="admin", user_id=None))
        db.add(IssuedLicense(
            stripe_customer_id="cus_evloop_test", email="admin", tier="pro",
            device_limit=40, license_key="evloop-test-key",
            stripe_session_id="cs_evloop_test_seed",
            expires_at=now + timedelta(days=30), activated=False,
        ))
        await db.commit()


@pytest.mark.asyncio
async def test_my_subscription_does_not_block_event_loop(admin_client):
    await _seed_active_license()

    def slow_list(*args, **kwargs):
        time.sleep(BLOCK_SECONDS)  # simulates Stripe API latency; must run off the loop
        fake = MagicMock()
        fake.data = []
        return fake

    old_key = _stripe.api_key
    _stripe.api_key = "sk_test_fake"
    try:
        with patch("app.billing.stripe.Subscription.list", side_effect=slow_list):
            start = time.monotonic()
            r1, r2 = await asyncio.gather(
                admin_client.get("/api/billing/my-subscription"),
                admin_client.get("/api/billing/my-subscription"),
            )
            elapsed = time.monotonic() - start
    finally:
        _stripe.api_key = old_key

    assert r1.status_code == 200 and r2.status_code == 200
    # Pre-fix: each request's blocking call monopolizes the event loop, so two
    # concurrent requests run effectively back-to-back (~2x BLOCK_SECONDS).
    # Post-fix: both blocking calls run concurrently in worker threads, so
    # total wall time stays close to a SINGLE call's duration.
    assert elapsed < BLOCK_SECONDS * 1.7, (
        f"two concurrent requests took {elapsed:.2f}s (~{elapsed / BLOCK_SECONDS:.1f}x a single "
        f"call) — looks sequential/blocking, not concurrent"
    )


@pytest.mark.asyncio
async def test_checkout_does_not_block_event_loop(admin_client):
    def slow_create(*args, **kwargs):
        time.sleep(BLOCK_SECONDS)
        fake = MagicMock()
        fake.url = "https://checkout.stripe.com/fake-session"
        return fake

    old_key = _stripe.api_key
    _stripe.api_key = "sk_test_fake"
    try:
        with (
            patch("app.billing.stripe.checkout.Session.create", side_effect=slow_create),
            patch("app.billing.PRICE_IDS", {"pro": "price_real_pro"}),
        ):
            start = time.monotonic()
            r1, r2 = await asyncio.gather(
                admin_client.post("/api/billing/checkout", json={"tier": "pro"}),
                admin_client.post("/api/billing/checkout", json={"tier": "pro"}),
            )
            elapsed = time.monotonic() - start
    finally:
        _stripe.api_key = old_key

    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert elapsed < BLOCK_SECONDS * 1.7, (
        f"two concurrent requests took {elapsed:.2f}s (~{elapsed / BLOCK_SECONDS:.1f}x a single "
        f"call) — looks sequential/blocking, not concurrent"
    )


@pytest.mark.asyncio
async def test_invoices_does_not_block_event_loop(admin_client):
    await _seed_active_license()

    def slow_list(*args, **kwargs):
        time.sleep(BLOCK_SECONDS)
        fake = MagicMock()
        fake.__iter__ = lambda self: iter([])
        return fake

    old_key = _stripe.api_key
    _stripe.api_key = "sk_test_fake"
    try:
        with patch("app.billing.stripe.Invoice.list", side_effect=slow_list):
            start = time.monotonic()
            r1, r2 = await asyncio.gather(
                admin_client.get("/api/billing/invoices"),
                admin_client.get("/api/billing/invoices"),
            )
            elapsed = time.monotonic() - start
    finally:
        _stripe.api_key = old_key

    assert r1.status_code == 200 and r2.status_code == 200
    assert elapsed < BLOCK_SECONDS * 1.7, (
        f"two concurrent requests took {elapsed:.2f}s (~{elapsed / BLOCK_SECONDS:.1f}x a single "
        f"call) — looks sequential/blocking, not concurrent"
    )
