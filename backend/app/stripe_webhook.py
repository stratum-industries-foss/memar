"""Stripe webhook receiver and license key issuance."""

import asyncio
import os
import base64
import json
import logging
from datetime import datetime, timezone, timedelta, date

import stripe
from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.exc import IntegrityError

from .models_db import StripeCustomer, IssuedLicense, StripeEventLog
from .email_service import send_cancellation_email, send_license_email, send_payment_failed_email, send_welcome_email, send_alert
from .license import apply_license
from .deps import get_db


logger = logging.getLogger(__name__)

# T39: Map tier from Stripe price_id instead of checkout metadata.
# This is the source of truth for what the customer actually paid for.
PRICE_TO_TIER: dict[str, tuple[str, int]] = {
    os.getenv("MEMAR_STRIPE_PRICE_FREE", ""): ("free", 1),
    os.getenv("MEMAR_STRIPE_PRICE_MAKER", ""): ("maker", 3),
    os.getenv("MEMAR_STRIPE_PRICE_PRO", ""): ("pro", 10),
    os.getenv("MEMAR_STRIPE_PRICE_SCALE", ""): ("scale", 25),
    os.getenv("MEMAR_STRIPE_PRICE_WORKSHOP", ""): ("workshop", 50),
    os.getenv("MEMAR_STRIPE_PRICE_BUSINESS", ""): ("business", 100),
    os.getenv("MEMAR_STRIPE_PRICE_ENTERPRISE", ""): ("enterprise", 250),
    os.getenv("MEMAR_STRIPE_PRICE_AIRGAP", ""): ("airgap", 3),
    os.getenv("MEMAR_STRIPE_PRICE_AIRGAP_STANDARD", ""): ("airgap_standard", 10),
    os.getenv("MEMAR_STRIPE_PRICE_AIRGAP_ENTERPRISE", ""): ("airgap_enterprise", 50),
}
# Remove empty-string keys (unset env vars)
PRICE_TO_TIER = {k: v for k, v in PRICE_TO_TIER.items() if k}


def get_tier_from_price(price_id: str) -> tuple[str, int]:
    """Get tier name and device limit from Stripe price_id."""
    return PRICE_TO_TIER.get(price_id, ("free", 1))


async def mark_event_processed(db: AsyncSession, event_id: str) -> None:
    """T41: Mark a Stripe event as processed BEFORE sending emails.
    
    This ensures we ACK to Stripe even if email delivery fails, preventing
    infinite retries while still having the license persisted in DB.
    """
    from sqlalchemy import update
    await db.execute(
        update(StripeEventLog)
        .where(StripeEventLog.stripe_event_id == event_id)
        .values(processed=True)
    )
    await db.commit()

stripe_router = APIRouter(tags=["stripe"])


def _generate_license_key(
    customer_id: str,
    device_limit: int,
    tier: str,
    days: int = 31,
    expires_on: "date | None" = None,
) -> str:
    """
    Generate an Ed25519-signed license key.
    Only works if MEMAR_LICENSE_PRIVATE_KEY is set (license issuer only).

    expires_on: explicit expiry date (used on renewal, where the expiry is the
    Stripe subscription's current_period_end). If omitted, expiry is now + days.
    """
    import nacl.signing

    privkey_b64 = os.getenv("MEMAR_LICENSE_PRIVATE_KEY")
    if not privkey_b64:
        raise RuntimeError(
            "MEMAR_LICENSE_PRIVATE_KEY not set; "
            "this instance cannot generate license keys. "
            "Only the webhook-receiving instance can issue licenses."
        )

    try:
        privkey_bytes = base64.b64decode(privkey_b64)
        signing_key = nacl.signing.SigningKey(privkey_bytes)

        if expires_on is not None:
            expires_at = expires_on.isoformat()
        else:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
        claims = {
            "customer_id": customer_id,
            "device_limit": device_limit,
            "tier": tier,
            "expires_at": expires_at,
            "issued_at": datetime.now(timezone.utc).date().isoformat(),
        }

        claims_bytes = json.dumps(claims).encode("utf-8")
        sig_bytes = signing_key.sign(claims_bytes).signature

        # Agile envelope: alg/kid/ver let the signing scheme evolve later (e.g. add
        # a post-quantum Falcon verifier or hybrid) without a wire-format change or
        # breaking already-issued keys. license.py verifies by dispatching on alg/kid.
        envelope = {
            "alg": "ed25519",
            "kid": "k1",
            "ver": 2,
            "claims": base64.b64encode(claims_bytes).decode("utf-8"),
            "sig": base64.b64encode(sig_bytes).decode("utf-8"),
        }
        license_key = base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("utf-8")

        logger.info(f"Generated license key for customer {customer_id} (tier={tier})")
        return license_key

    except Exception as e:
        logger.error(f"Failed to generate license key: {e}")
        raise


async def _handle_checkout_completed(session: dict, db: AsyncSession, event_id: str = "") -> None:
    """Handle Stripe checkout.session.completed event."""
    # T39: Extract tier from price_id (source of truth for what was paid)
    # instead of relying on checkout metadata which can be spoofed.
    line_items = session.get("line_items", {}).get("data", [])
    price_id = None
    if line_items:
        price_id = line_items[0].get("price", {}).get("id")
    
    if price_id:
        tier, device_limit = get_tier_from_price(price_id)
    else:
        # Fallback to metadata for backwards compatibility (e.g. custom checkouts)
        meta = session.get("metadata") or {}
        tier = meta.get("tier")
        device_limit = int(meta.get("device_limit", 0))
    
    if not tier:
        # One-time, non-license purchase (e.g. the Quickstart Installer service) —
        # there is no key to issue. Skip gracefully so the webhook returns 200
        # instead of erroring and forcing Stripe to retry.
        logger.info(
            f"checkout.session.completed without tier in price_id or metadata "
            f"(session {session.get('id')}); skipping license issuance"
        )
        return
    email = (session.get("customer_details") or {}).get("email")
    stripe_customer_id = session.get("customer")
    session_id = session.get("id")
    if not email or not stripe_customer_id:
        # Malformed/partial session payload — without an email we can't deliver
        # the key and without a customer id we can't map it. Skip gracefully so
        # the webhook returns 200 instead of KeyError-ing into a Stripe retry.
        logger.warning(
            f"checkout.session.completed missing email/customer "
            f"(session {session_id}); skipping license issuance"
        )
        return

    billing_period = session.get("metadata", {}).get("billing_period", "monthly")
    # Air-gap is an annual TERM billed monthly: an air-gapped box has no heartbeat and
    # can't fetch monthly renewals, so issue a full 12-month key at checkout. (Annual
    # community/pro billing is also 365.) Everything else gets a 31-day key that the
    # online heartbeat auto-refreshes each month.
    _AIRGAP_TIERS = {"airgap", "airgap_standard", "airgap_enterprise"}
    license_days = 365 if (billing_period == "annual" or tier in _AIRGAP_TIERS) else 31

    try:
        # Generate license key
        license_key = _generate_license_key(
            customer_id=stripe_customer_id,
            device_limit=device_limit,
            tier=tier,
            days=license_days,
        )

        # Store in DB
        expires_at = datetime.now(timezone.utc) + timedelta(days=license_days)
        issued_license = IssuedLicense(
            stripe_customer_id=stripe_customer_id,
            email=email,
            tier=tier,
            device_limit=device_limit,
            license_key=license_key,
            stripe_session_id=session_id,
            expires_at=expires_at,
            activated=False,
        )
        db.add(issued_license)

        # Create or update Stripe customer mapping
        existing = await db.execute(
            select(StripeCustomer).where(
                StripeCustomer.stripe_customer_id == stripe_customer_id
            )
        )
        customer = existing.scalar_one_or_none()
        if not customer:
            customer = StripeCustomer(
                stripe_customer_id=stripe_customer_id,
                email=email,
                user_id=None,
            )
            db.add(customer)

        # T41: Mark event processed BEFORE sending email.
        # This ensures we ACK to Stripe even if email fails — the license
        # is already persisted in DB and won't be lost.
        await mark_event_processed(db, event_id)

        # Send license key email + getting-started welcome email
        email_ok = await send_license_email(email=email, tier=tier, license_key=license_key)
        if not email_ok:
            logger.warning(f"Email delivery failed for {email}, but license was issued")
        await send_welcome_email(email=email, tier=tier)

        _ENTERPRISE_TIERS = {"scale", "workshop", "business", "enterprise"}
        if tier in _ENTERPRISE_TIERS:
            owner_email = os.getenv("MEMAR_OWNER_EMAIL", "")
            if owner_email:
                await _notify_owner_enterprise(owner_email, email, tier, stripe_customer_id)

        logger.info(f"License issued for {email} (tier={tier})")

    except Exception as e:
        logger.error(f"Failed to handle checkout completed: {e}")
        await db.rollback()
        raise


async def _handle_invoice_payment_failed(invoice: dict, db: AsyncSession, event_id: str = "") -> None:
    """Handle Stripe invoice.payment_failed event."""
    stripe_customer_id = invoice["customer"]
    email = invoice.get("customer_email", "")
    amount_due = invoice.get("amount_due", 0)

    logger.warning(
        f"Payment failed for customer {stripe_customer_id}, amount_due={amount_due}"
    )

    try:
        # Find most recent issued license for this customer
        result = await db.execute(
            select(IssuedLicense)
            .where(IssuedLicense.stripe_customer_id == stripe_customer_id)
            .order_by(desc(IssuedLicense.issued_at))
            .limit(1)
        )
        license_row = result.scalar_one_or_none()

        # Use email from license record if invoice didn't include it
        if not email and license_row:
            email = license_row.email

        # T41: Mark processed before sending email
        await mark_event_processed(db, event_id)

        if email:
            email_ok = await send_payment_failed_email(email=email, amount_due_cents=amount_due)
            if not email_ok:
                logger.warning("Payment failed email delivery failed (SMTP not configured or error)")
        else:
            logger.warning(
                f"No email available for customer {stripe_customer_id}; skipping payment failed email"
            )

        # Do NOT revoke the license — service continues during retry window

    except Exception as e:
        logger.error(f"Failed to handle invoice.payment_failed: {e}")
        raise


async def _handle_subscription_deleted(subscription: dict, db: AsyncSession, event_id: str = "") -> None:
    """Handle Stripe customer.subscription.deleted event."""
    stripe_customer_id = subscription["customer"]

    try:
        result = await db.execute(
            select(IssuedLicense).where(
                IssuedLicense.stripe_customer_id == stripe_customer_id,
            )
        )
        licenses = result.scalars().all()

        # Mark all of the customer's licenses expired in our records. NOTE: this
        # is vendor-side bookkeeping only. An offline key already in the
        # customer's hands cannot be remotely revoked before its baked-in expiry
        # date — this is inherent to offline license verification and is the
        # reason key lifetimes are kept short (monthly). The customer loses
        # access via the hard cutoff when the installed key's date passes.
        now = datetime.now(timezone.utc)
        for lic in licenses:
            lic.expires_at = now

        n = len(licenses)
        logger.info(
            f"Subscription cancelled for {stripe_customer_id}, {n} license record(s) marked expired"
        )

        # T41: Mark processed before sending email
        await mark_event_processed(db, event_id)

        # Send cancellation confirmation to each affected email (deduplicated)
        seen_emails: set[str] = set()
        for lic in licenses:
            if lic.email and lic.email not in seen_emails:
                seen_emails.add(lic.email)
                await send_cancellation_email(
                    email=lic.email,
                    tier=lic.tier,
                    expires_at=now,
                )

    except Exception as e:
        logger.error(f"Failed to handle customer.subscription.deleted: {e}")
        await db.rollback()
        raise


async def _notify_owner_enterprise(owner_email: str, customer_email: str, tier: str, customer_id: str) -> None:
    """Email owner when an enterprise-tier customer signs up."""
    import smtplib
    from email.message import EmailMessage

    smtp_host = os.getenv("MEMAR_SMTP_HOST", "")
    smtp_user = os.getenv("MEMAR_SMTP_USER", "")
    smtp_pass = os.getenv("MEMAR_SMTP_PASSWORD", "")
    smtp_port = int(os.getenv("MEMAR_SMTP_PORT", "587"))

    if not smtp_host:
        logger.warning("MEMAR_SMTP_HOST not set; skipping enterprise owner notification")
        return

    def _send_sync() -> None:
        msg = EmailMessage()
        msg["Subject"] = f"[MEMAR] {tier.upper()} signup — {customer_email}"
        msg["From"] = smtp_user
        msg["To"] = owner_email
        msg.set_content(
            f"Enterprise customer just signed up.\n\n"
            f"Email: {customer_email}\n"
            f"Tier: {tier}\n"
            f"Stripe Customer ID: {customer_id}\n\n"
            f"Follow up within 24h."
        )
        with smtplib.SMTP(smtp_host, smtp_port) as s:
            s.starttls()
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)

    try:
        # BACKEND-CORE-BLOCKING-01: smtplib is fully synchronous — calling it
        # directly here blocked the event loop (DNS + TCP + TLS + send, easily
        # 1-5s) for the duration of every enterprise-tier signup, stalling all
        # other concurrent requests (other webhooks, API calls) on this process.
        await asyncio.to_thread(_send_sync)
        logger.info(f"Enterprise alert sent to {owner_email} for customer {customer_email}")
    except Exception as e:
        logger.warning(f"Enterprise owner notification failed (non-fatal): {e}")


async def _handle_invoice_paid(invoice: dict, db: AsyncSession, event_id: str = "") -> None:
    """
    Handle Stripe invoice.paid — renew the customer's license on each payment.

    Because licenses are verified OFFLINE (the customer runs MEMAR self-hosted
    with the key in an env var) and we enforce a HARD CUTOFF at the key's baked-in
    expiry, "extending" a DB column does nothing for the customer: their installed
    key still expires on its original date. Renewal therefore means issuing a NEW
    signed key with the new expiry and emailing it. We key off the customer's most
    recent issued license (not the `activated` flag, which the offline flow never
    sets) to recover tier + device_limit.
    """
    stripe_customer_id = invoice.get("customer")
    subscription_id = invoice.get("subscription")

    if not subscription_id:
        # one-time payment, not a subscription renewal — still mark processed
        await mark_event_processed(db, event_id)
        return

    try:
        # The very first invoice.paid fires alongside checkout.session.completed,
        # which already issued the initial key. Detect that via billing_reason to
        # avoid emailing two keys on signup.
        if invoice.get("billing_reason") == "subscription_create":
            logger.info(f"invoice.paid (subscription_create) for {stripe_customer_id}; initial key already issued at checkout")
            await mark_event_processed(db, event_id)
            return

        sub = await asyncio.to_thread(stripe.Subscription.retrieve, subscription_id)
        new_expiry = datetime.fromtimestamp(sub["current_period_end"], tz=timezone.utc)

        # Recover the customer's current tier + limit from their latest license.
        result = await db.execute(
            select(IssuedLicense)
            .where(IssuedLicense.stripe_customer_id == stripe_customer_id)
            .order_by(desc(IssuedLicense.issued_at))
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if latest is None:
            logger.warning(f"invoice.paid: no prior license for {stripe_customer_id}; cannot renew")
            await mark_event_processed(db, event_id)
            return

        # Air-gap keys are a 12-month term, renewed MANUALLY (the box has no heartbeat and
        # can't receive a new key). Monthly invoices only collect payment — do not re-mint a
        # short-dated (~period-end) key the air-gapped customer could never install anyway.
        if latest.tier in {"airgap", "airgap_standard", "airgap_enterprise"}:
            logger.info(
                f"invoice.paid: air-gap tier {latest.tier} for {stripe_customer_id}; "
                "monthly billing only — 12-month key renewed manually, skipping re-mint"
            )
            await mark_event_processed(db, event_id)
            return

        # Issue a fresh signed key with the new expiry and email it.
        new_key = _generate_license_key(
            customer_id=stripe_customer_id,
            device_limit=latest.device_limit,
            tier=latest.tier,
            expires_on=new_expiry.date(),
        )
        db.add(IssuedLicense(
            stripe_customer_id=stripe_customer_id,
            email=latest.email,
            tier=latest.tier,
            device_limit=latest.device_limit,
            license_key=new_key,
            stripe_session_id=f"renewal_{invoice.get('id', subscription_id)}",
            expires_at=new_expiry,
            activated=False,
        ))
        # T41: Mark event processed BEFORE sending email. The license is persisted
        # in DB, so even if email fails the customer can request a resend. This
        # prevents Stripe retry storms on transient SMTP issues.
        await mark_event_processed(db, event_id)

        email_ok = await send_license_email(email=latest.email, tier=latest.tier, license_key=new_key)
        if not email_ok:
            logger.warning(
                f"invoice.paid: renewal key generated for {latest.email} but email "
                f"delivery failed; license is persisted, customer can request resend"
            )

        logger.info(f"invoice.paid: renewed license for {stripe_customer_id} (tier={latest.tier}) until {new_expiry.date()}")

    except Exception as e:
        logger.error(f"Failed to handle invoice.paid: {e}")
        await db.rollback()
        raise


async def _handle_subscription_updated(subscription: dict, db: AsyncSession, event_id: str = "") -> None:
    """
    Handle Stripe customer.subscription.updated — a plan change (upgrade/downgrade).

    Stripe puts the new tier/device_limit in subscription metadata (set when the
    checkout/upgrade was created). If the tier differs from the customer's latest
    issued license, we issue a fresh key for the new tier and email it. No-op if
    the tier is unchanged (this event also fires for unrelated churn like payment
    method updates).
    """
    stripe_customer_id = subscription.get("customer")
    meta = subscription.get("metadata") or {}
    new_tier = meta.get("tier")
    if not new_tier:
        # nothing actionable without a target tier — still mark processed
        await mark_event_processed(db, event_id)
        return

    try:
        result = await db.execute(
            select(IssuedLicense)
            .where(IssuedLicense.stripe_customer_id == stripe_customer_id)
            .order_by(desc(IssuedLicense.issued_at))
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if latest is None:
            logger.warning(f"subscription.updated: no prior license for {stripe_customer_id}; ignoring")
            await mark_event_processed(db, event_id)
            return
        if latest.tier == new_tier:
            # not a tier change — still mark processed
            await mark_event_processed(db, event_id)
            return

        new_limit = int(meta.get("device_limit") or latest.device_limit)
        period_end = subscription.get("current_period_end")
        new_expiry = (
            datetime.fromtimestamp(period_end, tz=timezone.utc)
            if period_end else latest.expires_at
        )

        new_key = _generate_license_key(
            customer_id=stripe_customer_id,
            device_limit=new_limit,
            tier=new_tier,
            expires_on=new_expiry.date(),
        )
        db.add(IssuedLicense(
            stripe_customer_id=stripe_customer_id,
            email=latest.email,
            tier=new_tier,
            device_limit=new_limit,
            license_key=new_key,
            stripe_session_id=f"change_{subscription.get('id', stripe_customer_id)}_{new_tier}_{event_id}",
            expires_at=new_expiry,
            activated=False,
        ))
        # T41: Mark processed before sending email
        await mark_event_processed(db, event_id)

        email_ok = await send_license_email(email=latest.email, tier=new_tier, license_key=new_key)
        if not email_ok:
            logger.warning(f"subscription.updated: new key for {latest.email} generated but email failed")

        logger.info(f"subscription.updated: {stripe_customer_id} {latest.tier}->{new_tier}, new key issued")

    except Exception as e:
        logger.error(f"Failed to handle customer.subscription.updated: {e}")
        await db.rollback()
        raise


async def _handle_charge_refunded(charge: dict, db: AsyncSession, event_id: str = "") -> None:
    """Handle Stripe charge.refunded.

    Full refund: mark all of the customer's licenses expired (same offline-key
    limitation as subscription.deleted — short key lifetimes are the enforcement).
    Partial refund: log + owner alert only, no access change.
    """
    stripe_customer_id = charge.get("customer")
    amount = charge.get("amount", 0)
    amount_refunded = charge.get("amount_refunded", 0)
    is_full = charge.get("refunded", False) or (amount > 0 and amount_refunded >= amount)

    if not stripe_customer_id:
        logger.warning("charge.refunded: no customer field; skipping")
        await mark_event_processed(db, event_id)
        return

    try:
        result = await db.execute(
            select(IssuedLicense)
            .where(IssuedLicense.stripe_customer_id == stripe_customer_id)
            .order_by(desc(IssuedLicense.issued_at))
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        email = latest.email if latest else ""

        if is_full:
            all_result = await db.execute(
                select(IssuedLicense).where(IssuedLicense.stripe_customer_id == stripe_customer_id)
            )
            licenses = all_result.scalars().all()
            now = datetime.now(timezone.utc)
            for lic in licenses:
                lic.expires_at = now

            # T41: Mark processed before sending emails
            await mark_event_processed(db, event_id)

            seen: set[str] = set()
            for lic in licenses:
                if lic.email and lic.email not in seen:
                    seen.add(lic.email)
                    await send_cancellation_email(email=lic.email, tier=lic.tier, expires_at=now)

            logger.info(f"Full refund for {stripe_customer_id}: {len(licenses)} license(s) marked expired")
        else:
            # Partial refund — just mark processed
            await mark_event_processed(db, event_id)

        await send_alert(
            subject=f"[MEMAR] {'Full' if is_full else 'Partial'} refund — {stripe_customer_id}",
            body=(
                f"Customer: {email or 'unknown'}\n"
                f"Stripe ID: {stripe_customer_id}\n"
                f"Refunded: ${amount_refunded / 100:.2f} of ${amount / 100:.2f}\n"
                + ("License(s) marked expired in MEMAR." if is_full else "Access unchanged (partial refund).")
            ),
        )

    except Exception as e:
        logger.error(f"Failed to handle charge.refunded: {e}")
        await db.rollback()
        raise


async def _handle_charge_dispute(dispute: dict, db: AsyncSession, event_id: str = "") -> None:
    """Handle Stripe charge.dispute.created.

    Dispute objects carry no customer field — retrieve via the charge.
    Sends an owner alert; no automatic access change (dispute may be resolved).
    """
    charge_id = dispute.get("charge", "")
    reason = dispute.get("reason", "unknown")
    amount = dispute.get("amount", 0)

    stripe_customer_id = None
    email = ""

    try:
        if charge_id:
            try:
                ch = await asyncio.to_thread(stripe.Charge.retrieve, charge_id)
                stripe_customer_id = ch.get("customer")
            except Exception as ce:
                logger.warning(f"dispute: could not retrieve charge {charge_id}: {ce}")

        if stripe_customer_id:
            result = await db.execute(
                select(IssuedLicense)
                .where(IssuedLicense.stripe_customer_id == stripe_customer_id)
                .order_by(desc(IssuedLicense.issued_at))
                .limit(1)
            )
            lic = result.scalar_one_or_none()
            if lic:
                email = lic.email

        logger.warning(
            f"charge.dispute.created: customer={stripe_customer_id} charge={charge_id} "
            f"reason={reason} amount=${amount / 100:.2f}"
        )

        # T41: Mark processed before sending alert email
        await mark_event_processed(db, event_id)

        await send_alert(
            subject=f"[MEMAR] ⚠️ Dispute opened — {stripe_customer_id or charge_id}",
            body=(
                f"A Stripe dispute has been opened.\n\n"
                f"Customer: {email or 'unknown'}\n"
                f"Stripe ID: {stripe_customer_id or 'unknown'}\n"
                f"Charge ID: {charge_id}\n"
                f"Reason: {reason}\n"
                f"Amount: ${amount / 100:.2f}\n\n"
                f"Respond in the Stripe Dashboard within 7 days."
            ),
        )

    except Exception as e:
        logger.error(f"Failed to handle charge.dispute.created: {e}")
        raise


async def _handle_invoice_action_required(invoice: dict, db: AsyncSession, event_id: str = "") -> None:
    """Handle Stripe invoice.payment_action_required (e.g. 3DS challenge).

    Emails the customer a direct link to complete the payment.
    """
    stripe_customer_id = invoice.get("customer")
    email = invoice.get("customer_email", "")
    hosted_url = invoice.get("hosted_invoice_url", "")

    if not email and stripe_customer_id:
        result = await db.execute(
            select(IssuedLicense)
            .where(IssuedLicense.stripe_customer_id == stripe_customer_id)
            .order_by(desc(IssuedLicense.issued_at))
            .limit(1)
        )
        lic = result.scalar_one_or_none()
        if lic:
            email = lic.email

    logger.info(f"invoice.payment_action_required for {stripe_customer_id}")

    # T41: Mark processed before sending email
    await mark_event_processed(db, event_id)

    if email:
        await send_alert(
            subject="Action required: complete your MEMAR payment",
            body=(
                f"Your MEMAR payment requires additional verification (such as 3D Secure).\n\n"
                f"Please complete it here:\n{hosted_url}\n\n"
                f"Your subscription will remain active while this is pending.\n"
                f"If you did not initiate this charge, reply to this email."
            ),
            to=email,
        )
    else:
        logger.warning(f"invoice.payment_action_required: no email for {stripe_customer_id}; skipping notification")


async def _handle_subscription_paused(subscription: dict, db: AsyncSession, event_id: str = "") -> None:
    """Handle Stripe customer.subscription.paused.

    Stripe pauses billing; we suspend access by setting expires_at=now. Same
    offline-key limitation as cancellation — installed keys run until their
    baked-in expiry. Resume event is customer.subscription.resumed (not yet handled;
    renewal webhook covers the re-issue path).
    """
    stripe_customer_id = subscription.get("customer")
    if not stripe_customer_id:
        await mark_event_processed(db, event_id)
        return

    try:
        result = await db.execute(
            select(IssuedLicense).where(IssuedLicense.stripe_customer_id == stripe_customer_id)
        )
        licenses = result.scalars().all()
        now = datetime.now(timezone.utc)
        for lic in licenses:
            lic.expires_at = now

        logger.info(f"Subscription paused for {stripe_customer_id}, {len(licenses)} license(s) suspended")

        # T41: Mark processed before sending emails
        await mark_event_processed(db, event_id)

        seen: set[str] = set()
        for lic in licenses:
            if lic.email and lic.email not in seen:
                seen.add(lic.email)
                await send_cancellation_email(email=lic.email, tier=lic.tier, expires_at=now)

    except Exception as e:
        logger.error(f"Failed to handle customer.subscription.paused: {e}")
        await db.rollback()
        raise


@stripe_router.post("/stripe/webhook")
async def handle_stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Receive and process Stripe webhooks.
    Public endpoint (no auth), but Stripe-signed.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = os.getenv("MEMAR_STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret:
        logger.warning("MEMAR_STRIPE_WEBHOOK_SECRET not configured; rejecting webhook")
        raise HTTPException(400, "Webhook secret not configured")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        logger.warning("Invalid Stripe signature")
        raise HTTPException(400, "Invalid Stripe signature")
    except ValueError:
        logger.warning("Invalid webhook payload")
        raise HTTPException(400, "Invalid webhook payload")

    # Idempotency: insert-first, not check-then-insert. Two concurrent
    # redeliveries of the same event_id could both pass a SELECT and then both
    # run the side-effects. Instead we try to INSERT the event-log row up front
    # inside a savepoint; the unique constraint on stripe_event_id makes the
    # second insert raise IntegrityError.
    # 
    # T40: On IntegrityError, check if the prior attempt actually completed
    # (processed=True). If not, re-run the handler — the previous attempt
    # might have crashed mid-way (e.g. email timeout).
    event_id = event.get("id")
    event_type = event.get("type", "unknown")
    log = StripeEventLog(stripe_event_id=event_id, event_type=event_type, processed=False)
    should_process = True
    try:
        async with db.begin_nested():
            db.add(log)
            await db.flush()  # force the INSERT so the unique index fires now
    except IntegrityError:
        await db.rollback()
        # T40: Check if event was actually processed or just logged
        result = await db.execute(
            select(StripeEventLog.processed).where(
                StripeEventLog.stripe_event_id == event_id
            )
        )
        row = result.first()
        if row and row[0]:
            # Already fully processed
            logger.info(f"Event {event_id} already processed")
            return {"status": "already_processed"}
        else:
            # Logged but not processed — re-run handler
            logger.info(f"Event {event_id} logged but not processed; retrying handler")
            should_process = True

    if not should_process:
        return {"status": "already_processed"}

    try:
        if event_type == "checkout.session.completed":
            session = event["data"]["object"]
            await _handle_checkout_completed(session, db, event_id)

        elif event_type == "invoice.paid":
            await _handle_invoice_paid(event["data"]["object"], db, event_id)

        elif event_type == "invoice.payment_failed":
            await _handle_invoice_payment_failed(event["data"]["object"], db, event_id)

        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(event["data"]["object"], db, event_id)

        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(event["data"]["object"], db, event_id)

        elif event_type == "charge.refunded":
            await _handle_charge_refunded(event["data"]["object"], db, event_id)

        elif event_type == "charge.dispute.created":
            await _handle_charge_dispute(event["data"]["object"], db, event_id)

        elif event_type == "invoice.payment_action_required":
            await _handle_invoice_action_required(event["data"]["object"], db, event_id)

        elif event_type == "customer.subscription.paused":
            await _handle_subscription_paused(event["data"]["object"], db, event_id)

        else:
            # Unknown event type — mark processed to prevent retries
            await mark_event_processed(db, event_id)

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Webhook processing failed: {e}")
        await db.rollback()
        raise HTTPException(500, "Webhook processing failed")
