"""License / billing / feature-gate fortress.

Full-parameter coverage of the tier->feature enforcement matrix plus adversarial
license-key tests (forged signatures, tampered payloads, expiry hard-cutoff) and
the Stripe webhook lifecycle (idempotency, renewal re-issue). These lock down the
revenue-critical chain fixed in P1.

The license public key is verified against MEMAR_LICENSE_PUBLIC_KEY when set, so
we install a throwaway test keypair and forge keys with it.
"""

import base64
import json
import os
from datetime import date, datetime, timedelta, timezone

import nacl.signing
import pytest

import app.license as licmod
from app.license import _tier_to_features, get_license, load_license_from_env, LicenseState


# --- Test keypair installed for the whole module --------------------------------
_SIGNING_KEY = nacl.signing.SigningKey.generate()
_PUB_B64 = base64.b64encode(bytes(_SIGNING_KEY.verify_key)).decode()
_PRIV_B64 = base64.b64encode(bytes(_SIGNING_KEY)).decode()


@pytest.fixture(autouse=True)
def _clean_license_env():
    """Install the test public key, reset the license singleton around each test."""
    prev = {k: os.environ.get(k) for k in
            ("MEMAR_LICENSE_PUBLIC_KEY", "MEMAR_LICENSE_PRIVATE_KEY", "MEMAR_LICENSE_KEY")}
    os.environ["MEMAR_LICENSE_PUBLIC_KEY"] = _PUB_B64
    os.environ["MEMAR_LICENSE_PRIVATE_KEY"] = _PRIV_B64
    os.environ.pop("MEMAR_LICENSE_KEY", None)
    licmod._state = None
    yield
    for k, v in prev.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    licmod._state = None


def _make_key(tier: str, device_limit: int, expires_on: date, customer_id="cus_test",
              signing_key: nacl.signing.SigningKey = _SIGNING_KEY) -> str:
    """Forge a license key the way the real issuer does (sig[64] + json payload)."""
    payload = {
        "customer_id": customer_id,
        "device_limit": device_limit,
        "tier": tier,
        "expires_at": expires_on.isoformat(),
        "issued_at": date.today().isoformat(),
    }
    payload_bytes = json.dumps(payload).encode()
    sig = signing_key.sign(payload_bytes).signature
    return base64.b64encode(sig + payload_bytes).decode()


def _apply(key: str) -> LicenseState:
    os.environ["MEMAR_LICENSE_KEY"] = key
    licmod._state = None
    load_license_from_env()
    return get_license()


# --- PARAMETER MATRIX: tier -> features -----------------------------------------

ALL_PAID_TIERS = ["maker", "pro", "farm", "scale", "workshop", "business", "enterprise"]


@pytest.mark.parametrize("tier", ALL_PAID_TIERS)
def test_every_paid_tier_has_features(tier):
    """Regression: workshop/business were absent -> [] -> paying customers 402'd."""
    feats = _tier_to_features(tier)
    assert feats, f"tier {tier} maps to no features — paying customers would be locked out"


# (tier, feature, should_be_allowed) — the enforced access matrix.
# Product model: any PAID tier unlocks the full feature set; device count is
# the only differentiator between paid tiers. Free is the exception — it gets
# none of these, which is the actual reason to upgrade.
_MATRIX = [
    ("free", "floor_plan", False), ("free", "webhooks", False), ("free", "oee", False),
    ("maker", "webhooks", True), ("maker", "oee", True), ("maker", "floor_plan", True),
    ("pro", "oee", True), ("pro", "floor_plan", True), ("pro", "webhooks", True),
    ("farm", "floor_plan", True), ("farm", "oee", True),
    ("scale", "sso", True), ("scale", "audit_logs", True),
    ("workshop", "oee", True), ("workshop", "sso", True),
    ("business", "custom_branding", True), ("business", "sso", True),
    ("enterprise", "custom_branding", True),
]


@pytest.mark.parametrize("tier,feature,allowed", _MATRIX)
def test_feature_matrix(tier, feature, allowed):
    assert (feature in _tier_to_features(tier)) is allowed


def test_all_paid_tiers_share_full_feature_set():
    """Every PAID tier unlocks the full set — device count is the only gate between them."""
    full = _tier_to_features("scale")
    assert {"sso", "custom_branding", "oee", "floor_plan", "audit_logs"} <= set(full)
    for tier in ALL_PAID_TIERS:
        assert _tier_to_features(tier) == full, f"{tier} should have the full feature set"


def test_free_tier_has_no_gated_features():
    """Free tier is the one exception — it gets none of the gated features."""
    assert _tier_to_features("free") == []


def test_unknown_tier_is_empty():
    assert _tier_to_features("nonsense") == []


# --- ADVERSARIAL: license key crypto --------------------------------------------

def test_valid_key_grants_tier():
    st = _apply(_make_key("farm", 150, date.today() + timedelta(days=30)))
    assert st.tier == "farm" and st.active is True
    assert st.device_limit == 150
    assert "oee" in st.features and "floor_plan" in st.features


def test_tampered_payload_falls_back_to_free():
    key = _make_key("scale", 500, date.today() + timedelta(days=30))
    raw = bytearray(base64.b64decode(key))
    raw[-1] ^= 0x01  # flip a byte in the payload — signature no longer matches
    st = _apply(base64.b64encode(bytes(raw)).decode())
    assert st.tier == "free" and st.device_limit == 5


def test_forged_key_with_wrong_private_key_rejected():
    attacker = nacl.signing.SigningKey.generate()
    st = _apply(_make_key("enterprise", 9999, date.today() + timedelta(days=365), signing_key=attacker))
    assert st.tier == "free"
    # A forged key buys nothing: it collapses to the free tier's 5-device cap.
    # (Features are free at every tier; the device cap is the paid moat.)
    assert st.device_limit == 5


def test_garbage_key_falls_back_to_free():
    st = _apply("this-is-not-a-valid-key")
    assert st.tier == "free"


def test_truncated_key_falls_back_to_free():
    key = _make_key("farm", 150, date.today() + timedelta(days=30))
    st = _apply(key[:40])
    assert st.tier == "free"


def test_expired_key_hard_cutoff_to_free():
    """Hard cutoff: an expired (but validly signed) key drops to the free tier
    with active=False. Under the all-features model the free feature LIST is the
    full set, so the lockout is enforced by active=False (require_feature fails
    closed on inactive) plus reverting to the free 5-device cap — NOT by stripping
    the list. Expired reverts to the free tier exactly (5 devices), matching the
    published 'up to 5 devices free' pricing; the paid 500-device cap is revoked."""
    st = _apply(_make_key("scale", 500, date.today() - timedelta(days=1)))
    assert st.active is False              # the real cutoff: every gate checks active
    assert st.tier == "free"
    assert st.device_limit == 5            # paid cap revoked; reverts to free tier (5)
    assert st.features == _tier_to_features("free")


def test_no_key_is_free():
    os.environ.pop("MEMAR_LICENSE_KEY", None)
    licmod._state = None
    load_license_from_env()
    assert get_license().tier == "free"


def test_perpetual_key_never_expires():
    """Air-gap SKU: a key with NO expires_at is active forever with full features
    (and the heartbeat skips it — see test_heartbeat_client)."""
    payload = {"customer_id": "cus_air", "device_limit": 100000, "tier": "enterprise",
               "issued_at": date.today().isoformat()}  # note: no expires_at
    payload_bytes = json.dumps(payload).encode()
    sig = _SIGNING_KEY.sign(payload_bytes).signature
    st = _apply(base64.b64encode(sig + payload_bytes).decode())
    assert st.active is True and st.tier == "enterprise"
    assert st.expires_at is None
    assert "custom_branding" in st.features and "sso" in st.features


# --- require_feature must also check `active` -----------------------------------

@pytest.mark.asyncio
async def test_inactive_license_blocks_gated_route_even_if_feature_listed(auth_client):
    """Belt-and-suspenders: even if the features list still names 'webhooks',
    an inactive license must 402 at the gate."""
    licmod._state = LicenseState(
        tier="farm", device_limit=150, expires_at="2020-01-01",
        features=["webhooks", "oee", "floor_plan"],  # stale list naming the feature
        customer_id="cus_x", active=False,
    )
    try:
        resp = await auth_client.get("/api/alerts/webhooks/")
        assert resp.status_code == 402
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_active_license_opens_gated_route(auth_client):
    licmod._state = LicenseState(
        tier="farm", device_limit=150, expires_at="2099-01-01",
        features=["webhooks", "oee", "floor_plan"],
        customer_id="cus_x", active=True,
    )
    try:
        resp = await auth_client.get("/api/alerts/webhooks/")
        assert resp.status_code == 200
    finally:
        licmod._state = None


@pytest.mark.parametrize("tier", ["airgap_standard", "airgap_enterprise"])
def test_tier_to_features_covers_real_airgap_billing_tiers(tier):
    """Regression: the real Stripe checkout/webhook flow (billing.py) only ever
    produces 'airgap_standard'/'airgap_enterprise', never bare 'airgap'. A prior
    bug had _tier_to_features() only recognize the literal 'airgap' string, so
    every real air-gap purchase got features=[] — every gated feature 402'd for
    paying customers, unconditionally. This must return the same full feature
    set as every other paid tier."""
    assert _tier_to_features(tier) == _tier_to_features("enterprise")
    assert _tier_to_features(tier) != []


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["airgap_standard", "airgap_enterprise"])
async def test_active_airgap_license_opens_gated_route(auth_client, tier):
    """Integration-level version of the above: an active air-gap license,
    built the same way load_license_from_env() would build one (features
    derived via _tier_to_features, not hand-listed), must open a gated route."""
    licmod._state = LicenseState(
        tier=tier, device_limit=9999, expires_at="2099-01-01",
        features=_tier_to_features(tier),
        customer_id="cus_airgap", active=True,
    )
    try:
        resp = await auth_client.get("/api/alerts/webhooks/")
        assert resp.status_code == 200
    finally:
        licmod._state = None


# --- STRIPE WEBHOOK lifecycle ----------------------------------------------------

def _stripe_event(event_id, event_type, obj):
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


@pytest.mark.asyncio
async def test_webhook_rejected_without_secret(client, monkeypatch):
    monkeypatch.delenv("MEMAR_STRIPE_WEBHOOK_SECRET", raising=False)
    resp = await client.post("/stripe/webhook", content=b"{}",
                             headers={"stripe-signature": "x"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_webhook_idempotency_duplicate_event(client, monkeypatch):
    """A repeated Stripe event id must be a no-op (already_processed)."""
    import app.stripe_webhook as sw
    monkeypatch.setenv("MEMAR_STRIPE_WEBHOOK_SECRET", "whsec_test")
    evt = _stripe_event("evt_dupe_1", "checkout.session.completed", {
        "id": "cs_1", "customer": "cus_1",
        "customer_details": {"email": "buyer@test.com"},
        "metadata": {"tier": "maker", "device_limit": "15", "billing_period": "monthly"},
    })
    monkeypatch.setattr(sw.stripe.Webhook, "construct_event", staticmethod(lambda *a, **k: evt))
    # First delivery processes; second short-circuits.
    r1 = await client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "x"})
    r2 = await client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "x"})
    assert r1.status_code == 200
    assert r2.json().get("status") == "already_processed"


@pytest.mark.asyncio
async def test_invoice_paid_reissues_key(client, monkeypatch):
    """Renewal must mint a NEW signed key (offline hard-cutoff => extending a DB
    column is invisible to the customer). Verify a fresh IssuedLicense row with a
    later expiry is created and a key email is attempted."""
    import app.stripe_webhook as sw
    from app.models_db import IssuedLicense
    from sqlalchemy import select
    from app.db import AsyncSessionLocal

    monkeypatch.setenv("MEMAR_STRIPE_WEBHOOK_SECRET", "whsec_test")

    # Seed an initial license for the customer.
    async with AsyncSessionLocal() as db:
        db.add(IssuedLicense(
            stripe_customer_id="cus_renew", email="r@test.com", tier="pro",
            device_limit=40, license_key="seedkey",
            stripe_session_id="cs_seed",
            expires_at=datetime.now(timezone.utc) + timedelta(days=2),
            activated=False,
        ))
        await db.commit()

    new_period_end = int((datetime.now(timezone.utc) + timedelta(days=32)).timestamp())
    monkeypatch.setattr(sw.stripe.Subscription, "retrieve",
                        staticmethod(lambda sid: {"current_period_end": new_period_end}))
    sent = {}
    async def _fake_email(email, tier, license_key):
        sent["email"], sent["tier"] = email, tier
        return True
    monkeypatch.setattr(sw, "send_license_email", _fake_email)

    evt = _stripe_event("evt_inv_1", "invoice.paid", {
        "id": "in_1", "customer": "cus_renew", "subscription": "sub_1",
        "billing_reason": "subscription_cycle",
    })
    monkeypatch.setattr(sw.stripe.Webhook, "construct_event", staticmethod(lambda *a, **k: evt))

    resp = await client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "x"})
    assert resp.status_code == 200

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(IssuedLicense).where(IssuedLicense.stripe_customer_id == "cus_renew")
        )).scalars().all()
    assert len(rows) == 2, "renewal should create a second license row"
    assert sent.get("email") == "r@test.com"
    assert max(r.expires_at for r in rows) > min(r.expires_at for r in rows)


@pytest.mark.asyncio
async def test_invoice_paid_skips_initial_subscription_create(client, monkeypatch):
    """The signup invoice (billing_reason=subscription_create) must NOT double-email
    a key — checkout.session.completed already issued one."""
    import app.stripe_webhook as sw
    monkeypatch.setenv("MEMAR_STRIPE_WEBHOOK_SECRET", "whsec_test")
    called = {"email": 0}
    async def _fake_email(**k):
        called["email"] += 1
        return True
    monkeypatch.setattr(sw, "send_license_email", _fake_email)
    evt = _stripe_event("evt_inv_create", "invoice.paid", {
        "id": "in_2", "customer": "cus_new", "subscription": "sub_2",
        "billing_reason": "subscription_create",
    })
    monkeypatch.setattr(sw.stripe.Webhook, "construct_event", staticmethod(lambda *a, **k: evt))
    resp = await client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "x"})
    assert resp.status_code == 200
    assert called["email"] == 0


# ── Renewal warning loop ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_renewal_warning_sends_email_and_marks_warned(client, monkeypatch):
    """_check_renewal_warnings sends one email for an expiring license and sets renewal_warning_sent_at."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.db import AsyncSessionLocal
    from app.models_db import IssuedLicense
    import app.license as licmod
    import app.email_service as esvc

    now = datetime.now(timezone.utc)
    sent = {}

    async def _fake_warn(email, tier, days_left, expires_at):
        sent["email"] = email
        sent["tier"] = tier
        sent["days_left"] = days_left
        return True

    monkeypatch.setattr(esvc, "send_renewal_warning_email", _fake_warn)

    async with AsyncSessionLocal() as db:
        lic = IssuedLicense(
            stripe_customer_id="cus_warn_1",
            email="warn@test.com",
            tier="pro",
            device_limit=40,
            license_key="fakekeywarn1",
            stripe_session_id="cs_warn_1",
            expires_at=now + timedelta(days=20),
            activated=True,
            activated_at=now,
            renewal_warning_sent_at=None,
        )
        db.add(lic)
        await db.commit()

    await licmod._check_renewal_warnings()

    assert sent.get("email") == "warn@test.com"
    assert sent.get("tier") == "pro"
    assert sent.get("days_left") == 20

    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(IssuedLicense).where(IssuedLicense.stripe_customer_id == "cus_warn_1")
        )).scalar_one()
    assert row.renewal_warning_sent_at is not None


@pytest.mark.asyncio
async def test_renewal_warning_skips_already_warned(client, monkeypatch):
    """_check_renewal_warnings must not re-send if renewal_warning_sent_at is already set."""
    from datetime import datetime, timedelta, timezone
    from app.db import AsyncSessionLocal
    from app.models_db import IssuedLicense
    import app.license as licmod
    import app.email_service as esvc

    now = datetime.now(timezone.utc)
    call_count = {"n": 0}

    async def _fake_warn(**k):
        call_count["n"] += 1
        return True

    monkeypatch.setattr(esvc, "send_renewal_warning_email", _fake_warn)

    async with AsyncSessionLocal() as db:
        lic = IssuedLicense(
            stripe_customer_id="cus_warn_2",
            email="warn2@test.com",
            tier="maker",
            device_limit=15,
            license_key="fakekeywarn2",
            stripe_session_id="cs_warn_2",
            expires_at=now + timedelta(days=10),
            activated=True,
            activated_at=now,
            renewal_warning_sent_at=now - timedelta(days=1),
        )
        db.add(lic)
        await db.commit()

    await licmod._check_renewal_warnings()
    assert call_count["n"] == 0


@pytest.mark.asyncio
async def test_invoice_paid_email_failure_acks_and_persists_renewal(client, monkeypatch):
    """T41: a renewal-email delivery failure must NOT 500 — that turned every
    transient SMTP outage into a Stripe retry storm. The event is ACKed (200,
    marked processed) and the freshly minted renewal key is persisted, so the
    payment is never lost even though delivery has to be retried out-of-band."""
    import app.stripe_webhook as sw
    from app.models_db import IssuedLicense, StripeEventLog
    from sqlalchemy import select
    from app.db import AsyncSessionLocal
    monkeypatch.setenv("MEMAR_STRIPE_WEBHOOK_SECRET", "whsec_test")

    async with AsyncSessionLocal() as db:
        db.add(IssuedLicense(
            stripe_customer_id="cus_renew_fail", email="rf@test.com", tier="pro",
            device_limit=40, license_key="seedkey",
            stripe_session_id="cs_seed_renew_fail",
            expires_at=datetime.now(timezone.utc) + timedelta(days=2), activated=False,
        ))
        await db.commit()

    new_period_end = int((datetime.now(timezone.utc) + timedelta(days=32)).timestamp())
    monkeypatch.setattr(sw.stripe.Subscription, "retrieve",
                        staticmethod(lambda sid: {"current_period_end": new_period_end}))

    async def _failing_email(email, tier, license_key):
        return False
    monkeypatch.setattr(sw, "send_license_email", _failing_email)

    evt = _stripe_event("evt_inv_fail", "invoice.paid", {
        "id": "in_fail", "customer": "cus_renew_fail", "subscription": "sub_fail",
        "billing_reason": "subscription_cycle",
    })
    monkeypatch.setattr(sw.stripe.Webhook, "construct_event", staticmethod(lambda *a, **k: evt))

    resp = await client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "x"})
    assert resp.status_code == 200, (
        f"renewal email failure must still ACK the event (T41), got {resp.status_code}"
    )

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(IssuedLicense).where(IssuedLicense.stripe_customer_id == "cus_renew_fail")
        )).scalars().all()
        processed = (await db.execute(
            select(StripeEventLog.processed).where(StripeEventLog.stripe_event_id == "evt_inv_fail")
        )).scalar_one()
    renewal = [r for r in rows if r.stripe_session_id == "renewal_in_fail"]
    assert len(rows) == 2 and len(renewal) == 1, (
        f"renewal row must be persisted next to the seed despite the email failure; found {len(rows)}"
    )
    assert renewal[0].license_key and renewal[0].license_key != "seedkey"
    assert processed is True


@pytest.mark.asyncio
async def test_subscription_updated_repeat_tier_change_no_collision(client, monkeypatch):
    """A tier transition whose deterministic synthetic session-id was already used by
    an earlier transition to the SAME tier must not collide (stripe_session_id is
    unique=True). Regression: id was change_{sub}_{tier}, so a repeat pro->farm 500s
    permanently. The fix appends the unique Stripe event id."""
    import app.stripe_webhook as sw
    from app.models_db import IssuedLicense
    from sqlalchemy import select
    from app.db import AsyncSessionLocal
    monkeypatch.setenv("MEMAR_STRIPE_WEBHOOK_SECRET", "whsec_test")

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        # An earlier farm transition already minted the deterministic id the buggy
        # code reuses for EVERY farm transition on this subscription (the collision target).
        db.add(IssuedLicense(
            stripe_customer_id="cus_tierchg", email="tc@test.com", tier="farm",
            device_limit=150, license_key="k_farm_old",
            stripe_session_id="change_sub_tc_farm",
            expires_at=now + timedelta(days=15),
            issued_at=now - timedelta(hours=2), activated=False,
        ))
        # A newer PRO row makes the customer's LATEST license 'pro', so a farm
        # transition is a real change (handler does not early-return). Distinct
        # issued_at makes "latest" deterministic despite second-resolution now().
        db.add(IssuedLicense(
            stripe_customer_id="cus_tierchg", email="tc@test.com", tier="pro",
            device_limit=40, license_key="k_pro_new",
            stripe_session_id="change_sub_tc_pro_prev",
            expires_at=now + timedelta(days=15),
            issued_at=now - timedelta(hours=1), activated=False,
        ))
        await db.commit()

    async def _fake_email(email, tier, license_key):
        return True
    monkeypatch.setattr(sw, "send_license_email", _fake_email)

    evt = _stripe_event("evt_tc_c", "customer.subscription.updated", {
        "id": "sub_tc", "customer": "cus_tierchg",
        "metadata": {"tier": "farm", "device_limit": "150"},
        "current_period_end": int((now + timedelta(days=30)).timestamp()),
    })
    monkeypatch.setattr(sw.stripe.Webhook, "construct_event", staticmethod(lambda *a, **k: evt))

    resp = await client.post("/stripe/webhook", content=b"{}", headers={"stripe-signature": "x"})
    assert resp.status_code == 200, (
        f"repeat farm transition must not 500 on a stripe_session_id collision; got {resp.status_code}"
    )

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(IssuedLicense).where(IssuedLicense.stripe_customer_id == "cus_tierchg")
        )).scalars().all()
    assert any(r.tier == "farm" and r.stripe_session_id.endswith("evt_tc_c") for r in rows), (
        "the new farm license for this event must be persisted with a per-event unique id"
    )


# ── GET /api/license/renewal-warning ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_renewal_warning_endpoint_ignores_stale_expired_row(admin_client):
    """The renewal-warning endpoint must not let an old EXPIRED activated license
    (e.g. left over from a prior tier change) permanently win 'soonest expiring'
    over a fresh, valid one. Without an explicit not-yet-expired check, ordering
    by expires_at ascending always returns the expired row first."""
    from datetime import datetime, timedelta, timezone
    from app.db import AsyncSessionLocal
    from app.models_db import IssuedLicense

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        # Expired months ago — sorts first under a plain ascending order, but
        # must be skipped since it's no longer a real "soonest expiring" license.
        db.add(IssuedLicense(
            stripe_customer_id="cus_renew_stale", email="admin", tier="maker",
            device_limit=15, license_key="renew-stale-key",
            stripe_session_id="cs_renew_stale",
            expires_at=now - timedelta(days=200), activated=True, activated_at=now,
        ))
        # Fresh, valid, expiring in 10 days — this is the one the banner should
        # actually warn about.
        db.add(IssuedLicense(
            stripe_customer_id="cus_renew_fresh", email="admin", tier="pro",
            device_limit=40, license_key="renew-fresh-key",
            stripe_session_id="cs_renew_fresh",
            expires_at=now + timedelta(days=10), activated=True, activated_at=now,
        ))
        await db.commit()

    resp = await admin_client.get("/api/license/renewal-warning")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["warning"] is True
    assert data["tier"] == "pro", f"expected the fresh 'pro' license, got: {data}"
    assert 0 <= data["days_remaining"] <= 10


@pytest.mark.asyncio
async def test_renewal_warning_endpoint_no_active_license_within_30d(admin_client):
    """A license expiring well beyond the 30-day window must not trigger a warning."""
    from datetime import datetime, timedelta, timezone
    from app.db import AsyncSessionLocal
    from app.models_db import IssuedLicense

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(IssuedLicense(
            stripe_customer_id="cus_renew_far", email="admin", tier="farm",
            device_limit=150, license_key="renew-far-key",
            stripe_session_id="cs_renew_far",
            expires_at=now + timedelta(days=200), activated=True, activated_at=now,
        ))
        await db.commit()

    resp = await admin_client.get("/api/license/renewal-warning")
    assert resp.status_code == 200, resp.text
    assert resp.json()["warning"] is False
