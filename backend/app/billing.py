"""Stripe billing and checkout."""

import asyncio
import os
import logging
from typing import Optional
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .deps import get_current_user, get_db, require_role
from .models_db import IssuedLicense, StripeCustomer
from .firstrun import public_base_url as _public_base_url


logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = os.getenv("MEMAR_STRIPE_SECRET_KEY", "")

# Community tier monthly price IDs (Stripe)
PRICE_IDS = {
    "maker": os.getenv("MEMAR_STRIPE_PRICE_MAKER", "price_placeholder_maker"),
    "pro":   os.getenv("MEMAR_STRIPE_PRICE_PRO",   "price_placeholder_pro"),
    "farm":  os.getenv("MEMAR_STRIPE_PRICE_FARM",  "price_placeholder_farm"),
    "scale": os.getenv("MEMAR_STRIPE_PRICE_SCALE", "price_placeholder_scale"),
}

# Community tier annual price IDs (Stripe) — ~17% savings vs monthly
PRICE_IDS_ANNUAL = {
    "maker": os.getenv("MEMAR_STRIPE_PRICE_MAKER_ANNUAL", "price_placeholder_maker_annual"),
    "pro":   os.getenv("MEMAR_STRIPE_PRICE_PRO_ANNUAL",   "price_placeholder_pro_annual"),
    "farm":  os.getenv("MEMAR_STRIPE_PRICE_FARM_ANNUAL",  "price_placeholder_farm_annual"),
    "scale": os.getenv("MEMAR_STRIPE_PRICE_SCALE_ANNUAL", "price_placeholder_scale_annual"),
}

# Professional (B2B) tier monthly price IDs (Stripe)
PRICE_IDS_PROFESSIONAL = {
    "workshop":   os.getenv("MEMAR_STRIPE_PRICE_WORKSHOP",   "price_placeholder_workshop"),
    "business":   os.getenv("MEMAR_STRIPE_PRICE_BUSINESS",   "price_placeholder_business"),
    "enterprise": os.getenv("MEMAR_STRIPE_PRICE_ENTERPRISE", "price_placeholder_enterprise"),
}

# Flat-rate device limits — community tiers
DEVICE_LIMITS = {
    "maker": 15,
    "pro":   40,
    "farm":  150,
    "scale": 500,
}

# Flat-rate device limits — professional tiers
PROFESSIONAL_DEVICE_LIMITS = {
    "workshop":   500,
    "business":   2000,
    "enterprise": 10000,
}

# Air-gap tiers (recurring monthly subscription with 12-month commitment)
PRICE_IDS_AIRGAP = {
    "airgap_standard":  os.getenv("MEMAR_STRIPE_PRICE_AIRGAP_STANDARD",  "price_placeholder_airgap_standard"),
    "airgap_enterprise": os.getenv("MEMAR_STRIPE_PRICE_AIRGAP_ENTERPRISE", "price_placeholder_airgap_enterprise"),
}
AIRGAP_DEVICE_LIMITS = {
    "airgap_standard":  500,
    "airgap_enterprise": 9999,  # unlimited
}
AIRGAP_PRICES = {
    "airgap_standard":  1999,   # $1,999/month, 12-month minimum
    "airgap_enterprise": 4999,  # $4,999/month, 12-month minimum, unlimited devices
}

# Monthly prices ($USD) — matches stratum.industries/memar pricing tiers
TIER_PRICES = {
    "maker": 19,
    "pro":   49,
    "farm":  199,
    "scale": 499,
}

# Annual prices ($USD — billed once per year, ~17% savings)
TIER_PRICES_ANNUAL = {
    "maker": 189,
    "pro":   489,
    "farm":  1990,
    "scale": 4990,
}

# Professional tier monthly prices ($USD) — matches website
PROFESSIONAL_PRICES = {
    "workshop":   1199,
    "business":   1999,
    "enterprise": 3999,
}

# Product model: EVERY tier (incl. free) ships the FULL feature set. The ONLY
# paid differentiator is device capacity (see DEVICE_LIMITS). So the marketing
# feature list is identical across tiers — keep in sync with
# license._tier_to_features (enforcement) intent.
_ALL_FEATURES = [
    "All features included", "Webhooks", "Multi-user", "RBAC", "OEE Dashboard",
    "Floor Plan", "Analytics", "SSO", "Audit Logs", "Compliance Export", "White-label",
]
TIER_FEATURES = {
    t: _ALL_FEATURES
    for t in ("maker", "pro", "farm", "scale", "workshop", "business", "enterprise",
              "airgap", "airgap_standard", "airgap_enterprise")
}

billing_router = APIRouter(tags=["billing"])


class CheckoutRequest(BaseModel):
    tier: str
    billing_period: str = "monthly"  # "monthly" or "annual"


class CheckoutResponse(BaseModel):
    checkout_url: str


class BillingPlan(BaseModel):
    tier: str
    price_per_month: int
    price_annual: int | None
    device_limit: int
    features: list[str]
    segment: str = "community"  # "community" or "professional"


@billing_router.post("/billing/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    request: CheckoutRequest,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    """Create a Stripe Checkout Session for license upgrade."""
    tier = request.tier.lower()
    billing_period = request.billing_period.lower()

    is_professional = tier in PROFESSIONAL_DEVICE_LIMITS
    is_airgap = tier in AIRGAP_DEVICE_LIMITS
    all_known_tiers = set(PRICE_IDS) | set(PROFESSIONAL_DEVICE_LIMITS) | set(AIRGAP_DEVICE_LIMITS)
    if tier not in all_known_tiers:
        raise HTTPException(400, f"Unknown tier: {tier}")

    if not stripe.api_key:
        raise HTTPException(503, "Stripe not configured — set MEMAR_STRIPE_SECRET_KEY")

    if is_airgap:
        price_id = PRICE_IDS_AIRGAP[tier]
        device_limit = AIRGAP_DEVICE_LIMITS[tier]
    elif is_professional:
        price_id = PRICE_IDS_PROFESSIONAL[tier]
        device_limit = PROFESSIONAL_DEVICE_LIMITS[tier]
    elif billing_period == "annual":
        price_id = PRICE_IDS_ANNUAL[tier]
        device_limit = DEVICE_LIMITS[tier]
    else:
        price_id = PRICE_IDS[tier]
        device_limit = DEVICE_LIMITS[tier]

    if price_id.startswith("price_placeholder"):
        env_var = f"MEMAR_STRIPE_PRICE_{tier.upper()}" + ("_ANNUAL" if billing_period == "annual" else "")
        raise HTTPException(503, f"Stripe price ID for tier '{tier}' not configured — set {env_var}")

    public_url = _public_base_url()

    try:
        if is_airgap:
            # Air-gap = annual TERM, BILLED MONTHLY (12-month commitment). Billing is a
            # normal monthly Stripe subscription; the LICENSE is a 12-month offline key
            # (an air-gapped box can't heartbeat-renew). The webhook issues a 365-day key
            # at checkout and does NOT auto-renew monthly — renew yearly by re-issuing a
            # fresh key. NOTE: MEMAR_STRIPE_PRICE_AIRGAP_* must be RECURRING monthly prices.
            session = await asyncio.to_thread(
                stripe.checkout.Session.create,
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                customer_email=current_user.get("email") or current_user.get("username"),
                success_url=f"{public_url}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{public_url}/?checkout=cancelled",
                metadata={"tier": tier, "device_limit": str(device_limit), "billing_period": "monthly"},
            )
        else:
            session = await asyncio.to_thread(
                stripe.checkout.Session.create,
                mode="subscription",
                line_items=[{"price": price_id, "quantity": 1}],
                customer_email=current_user.get("email") or current_user.get("username"),
                success_url=f"{public_url}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{public_url}/?checkout=cancelled",
                metadata={"tier": tier, "device_limit": str(device_limit), "billing_period": billing_period},
            )
        return CheckoutResponse(checkout_url=session.url)

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating checkout session: {e}")
        raise HTTPException(500, "Failed to create checkout session")


@billing_router.get("/billing/plans", response_model=list[BillingPlan])
async def get_billing_plans() -> list[BillingPlan]:
    """Get all available billing plans (public endpoint)."""
    community = [
        BillingPlan(
            tier=t,
            price_per_month=TIER_PRICES[t],
            price_annual=TIER_PRICES_ANNUAL[t],
            device_limit=DEVICE_LIMITS[t],
            features=TIER_FEATURES[t],
            segment="community",
        )
        for t in ("maker", "pro", "farm", "scale")
    ]
    professional = [
        BillingPlan(
            tier=t,
            price_per_month=PROFESSIONAL_PRICES[t],
            price_annual=None,  # contact sales for annual
            device_limit=PROFESSIONAL_DEVICE_LIMITS[t],
            features=TIER_FEATURES[t],
            segment="professional",
        )
        for t in ("workshop", "business", "enterprise")
    ]
    airgap = [
        BillingPlan(
            tier=t,
            price_per_month=AIRGAP_PRICES[t],
            price_annual=None,
            device_limit=AIRGAP_DEVICE_LIMITS[t],
            features=TIER_FEATURES[t],
            segment="airgap",
        )
        for t in ("airgap_standard", "airgap_enterprise")
    ]
    return community + professional + airgap


class SubscriptionStatus(BaseModel):
    tier: str
    status: str  # 'active' | 'cancelled' | 'past_due' | 'none' | 'expired'
    expires_at: Optional[str]
    device_limit: Optional[int]
    cancel_at_period_end: bool
    stripe_customer_id: Optional[str]
    days_until_expiry: Optional[int] = None  # whole days left on an active license; None if no expiry
    expiring_soon: bool = False              # active + within RENEWAL_WARNING_DAYS — drives the renewal banner


# How many days before expiry the UI starts warning about renewal.
# Same policy as the renewal banner (main.py): online plans renew automatically,
# so warn only in the last week; air-gap licences are renewed by hand, so a month.
RENEWAL_WARNING_DAYS_ONLINE = 7
RENEWAL_WARNING_DAYS_AIRGAP = 30


_FREE_SUBSCRIPTION = SubscriptionStatus(
    tier="free",
    status="none",
    expires_at=None,
    device_limit=5,
    cancel_at_period_end=False,
    stripe_customer_id=None,
    days_until_expiry=None,
    expiring_soon=False,
)


@billing_router.get("/billing/my-subscription", response_model=SubscriptionStatus)
async def get_my_subscription(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionStatus:
    """Return the current user's active subscription details."""
    email = current_user.get("email") or current_user.get("username")

    # Look up StripeCustomer record
    result = await db.execute(
        select(StripeCustomer)
        .where(StripeCustomer.email == email)
        .order_by(StripeCustomer.created_at.desc())
    )
    stripe_customer = result.scalars().first()

    if stripe_customer is None:
        return _FREE_SUBSCRIPTION

    stripe_customer_id = stripe_customer.stripe_customer_id

    # Most recent IssuedLicense for this customer
    lic_result = await db.execute(
        select(IssuedLicense)
        .where(IssuedLicense.stripe_customer_id == stripe_customer_id)
        .order_by(IssuedLicense.issued_at.desc())
        .limit(1)
    )
    license = lic_result.scalars().first()

    if license is None:
        return _FREE_SUBSCRIPTION

    # Try to fetch cancel_at_period_end from Stripe
    cancel_at_period_end = False
    try:
        if stripe.api_key:
            subs = await asyncio.to_thread(
                stripe.Subscription.list,
                customer=stripe_customer_id, status="active", limit=1,
            )
            if subs and subs.data:
                cancel_at_period_end = subs.data[0].cancel_at_period_end
    except stripe.error.StripeError as e:
        logger.warning(f"Could not fetch Stripe subscription details: {e}")

    now = datetime.now(timezone.utc)
    expires_at = license.expires_at
    # Make expires_at timezone-aware for comparison if it is naive
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    status = "active" if (expires_at is not None and expires_at > now) else "expired"

    # Renewal-warning signal: whole days left, and whether we're inside the
    # warning window. Only meaningful while the license is still active.
    days_until_expiry = None
    expiring_soon = False
    if status == "active" and expires_at is not None:
        days_until_expiry = max(0, (expires_at - now).days)
        window = (RENEWAL_WARNING_DAYS_AIRGAP if str(license.tier).startswith("airgap")
                  else RENEWAL_WARNING_DAYS_ONLINE)
        expiring_soon = days_until_expiry <= window

    return SubscriptionStatus(
        tier=license.tier,
        status=status,
        expires_at=license.expires_at.isoformat() if license.expires_at else None,
        device_limit=license.device_limit,
        cancel_at_period_end=cancel_at_period_end,
        stripe_customer_id=stripe_customer_id,
        days_until_expiry=days_until_expiry,
        expiring_soon=expiring_soon,
    )


@billing_router.delete("/billing/my-subscription")
async def cancel_my_subscription(
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Cancel the current user's subscription at the end of the billing period."""
    email = current_user.get("email") or current_user.get("username")

    # Look up StripeCustomer record
    result = await db.execute(
        select(StripeCustomer)
        .where(StripeCustomer.email == email)
        .order_by(StripeCustomer.created_at.desc())
    )
    stripe_customer = result.scalars().first()

    if stripe_customer is None:
        raise HTTPException(404, "No subscription found")

    # Air-gap tiers carry a 12-month commitment: a full 12-month (365-day) offline
    # key is issued at checkout, but Stripe billing is a plain cancellable monthly
    # subscription. Allowing self-serve cancellation here would let a customer pay a
    # single month and keep a working year-long key. Block it — air-gap cancellations
    # are handled out-of-band by support/sales. NOTE: this guard MUST stay ABOVE the
    # stripe.api_key check so it returns 403 even when Stripe is not configured.
    airgap_lic_result = await db.execute(
        select(IssuedLicense)
        .where(IssuedLicense.stripe_customer_id == stripe_customer.stripe_customer_id)
        .order_by(IssuedLicense.issued_at.desc())
        .limit(1)
    )
    latest_airgap_license = airgap_lic_result.scalars().first()
    if latest_airgap_license is not None and latest_airgap_license.tier in AIRGAP_DEVICE_LIMITS:
        raise HTTPException(
            403,
            "Air-gap subscriptions carry a 12-month commitment and cannot be "
            "cancelled online. Contact support to cancel.",
        )

    if not stripe.api_key:
        raise HTTPException(503, "Stripe not configured")

    stripe_customer_id = stripe_customer.stripe_customer_id

    try:
        subs = await asyncio.to_thread(
            stripe.Subscription.list,
            customer=stripe_customer_id, status="active", limit=1,
        )
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error listing subscriptions: {e}")
        raise HTTPException(500, "Failed to retrieve subscription from Stripe")

    if not subs or not subs.data:
        raise HTTPException(404, "No active subscription found")

    sub = subs.data[0]

    try:
        await asyncio.to_thread(stripe.Subscription.modify, sub.id, cancel_at_period_end=True)
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error cancelling subscription {sub.id}: {e}")
        raise HTTPException(500, "Failed to cancel subscription")

    return {
        "status": "cancel_at_period_end",
        "message": "Subscription will cancel at end of billing period",
    }


class UpgradeRequest(BaseModel):
    tier: str


@billing_router.post("/billing/upgrade")
async def upgrade_subscription(
    request: UpgradeRequest,
    current_user: dict = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upgrade or downgrade an existing active subscription to a new tier.

    Modifies the existing Stripe subscription in-place with prorations.
    Use /billing/checkout to start a brand-new subscription.
    """
    tier = request.tier.lower()

    if tier in AIRGAP_DEVICE_LIMITS:
        raise HTTPException(400, f"'{tier}' is an air-gap subscription — use /billing/checkout")
    all_known_tiers = set(PRICE_IDS) | set(PROFESSIONAL_DEVICE_LIMITS)
    if tier not in all_known_tiers:
        raise HTTPException(400, f"Unknown tier: {tier}")

    if not stripe.api_key:
        raise HTTPException(503, "Stripe not configured — set MEMAR_STRIPE_SECRET_KEY")

    email = current_user.get("email") or current_user.get("username")
    result = await db.execute(
        select(StripeCustomer)
        .where(StripeCustomer.email == email)
        .order_by(StripeCustomer.created_at.desc())
    )
    stripe_customer = result.scalars().first()

    if stripe_customer is None:
        raise HTTPException(404, "No subscription found — use /billing/checkout to start a new subscription")

    stripe_customer_id = stripe_customer.stripe_customer_id

    try:
        subs = await asyncio.to_thread(
            stripe.Subscription.list,
            customer=stripe_customer_id, status="active", limit=1,
        )
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error listing subscriptions: {e}")
        raise HTTPException(500, "Failed to retrieve subscription from Stripe")

    if not subs or not subs.data:
        raise HTTPException(404, "No active subscription — use /billing/checkout to start a new subscription")

    sub = subs.data[0]
    sub_item_id = sub["items"]["data"][0]["id"]

    # Preserve the customer's existing billing interval. PRICE_IDS_ANNUAL only
    # covers the community tiers (professional tiers have no annual price ID
    # to switch to) — without this, every upgrade/downgrade silently rewrote
    # an annual subscriber onto a monthly price.
    current_interval = sub["items"]["data"][0]["price"]["recurring"]["interval"]
    if tier in PRICE_IDS_PROFESSIONAL:
        price_id = PRICE_IDS_PROFESSIONAL[tier]
    elif current_interval == "year":
        price_id = PRICE_IDS_ANNUAL.get(tier, "")
    else:
        price_id = PRICE_IDS.get(tier, "")
    if not price_id or price_id.startswith("price_placeholder"):
        raise HTTPException(503, f"Stripe price ID for tier '{tier}' ({current_interval}ly) not configured")

    device_limit = PROFESSIONAL_DEVICE_LIMITS.get(tier) or DEVICE_LIMITS.get(tier, 0)

    try:
        await asyncio.to_thread(
            stripe.Subscription.modify,
            sub["id"],
            items=[{"id": sub_item_id, "price": price_id}],
            proration_behavior="create_prorations",
            metadata={"tier": tier, "device_limit": str(device_limit)},
        )
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error upgrading subscription {sub['id']}: {e}")
        raise HTTPException(500, "Failed to upgrade subscription")

    logger.info(f"Subscription upgraded for {email} to tier={tier}")
    return {"status": "upgraded", "tier": tier, "message": f"Subscription updated to {tier} tier"}


@billing_router.get("/billing/invoices")
async def list_invoices(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return up to 24 invoices for the current user's Stripe customer.

    Each invoice includes amount, date, status, and a hosted PDF URL.
    Returns an empty list when Stripe is not configured or the user has no subscription.
    """
    if not stripe.api_key:
        return []

    email = current_user.get("email") or current_user.get("username")
    result = await db.execute(
        select(StripeCustomer)
        .where(StripeCustomer.email == email)
        .order_by(StripeCustomer.created_at.desc())
    )
    customer = result.scalars().first()
    if customer is None:
        return []

    try:
        invoices = await asyncio.to_thread(
            stripe.Invoice.list, customer=customer.stripe_customer_id, limit=24
        )
    except stripe.error.StripeError as e:
        logger.warning("Could not fetch Stripe invoices: %s", e)
        return []

    return [
        {
            "id": inv.get("id"),
            "amount_paid": inv.get("amount_paid", 0),
            "currency": inv.get("currency", "usd"),
            "status": inv.get("status"),
            "created": inv.get("created"),
            "hosted_invoice_url": inv.get("hosted_invoice_url"),
            "invoice_pdf": inv.get("invoice_pdf"),
            "period_start": inv.get("period_start"),
            "period_end": inv.get("period_end"),
        }
        for inv in (invoices.data if invoices else [])
    ]
