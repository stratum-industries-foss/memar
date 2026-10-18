"""Async email delivery via SMTP."""

import os
import html
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib


logger = logging.getLogger(__name__)


SMTP_HOST = os.getenv("MEMAR_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("MEMAR_SMTP_PORT", "587"))
SMTP_USER = os.getenv("MEMAR_SMTP_USER", "")
SMTP_PASSWORD = os.getenv("MEMAR_SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("MEMAR_SMTP_FROM", SMTP_USER)
# starttls (default): connect plaintext on e.g. 587, then upgrade via STARTTLS —
# matches the gmail-style config this module shipped with originally.
# implicit: connect via TLS/SSL from the first byte (e.g. port 465).
# none: no encryption — only for trusted internal/LAN relays.
SMTP_TLS_MODE = os.getenv("MEMAR_SMTP_TLS_MODE", "starttls").strip().lower()
# Preserves the original hard requirement for USER+PASSWORD by default (zero
# behavior change for existing gmail-based deployments); set true to allow an
# internal/LAN relay that accepts mail with no login at all.
SMTP_ALLOW_UNAUTHENTICATED = os.getenv("MEMAR_SMTP_ALLOW_UNAUTHENTICATED", "false").strip().lower() in ("1", "true", "yes")


def _looks_like_email(value: str) -> bool:
    """Cheap 'is this an email address' check for routing password-reset mail."""
    value = (value or "").strip()
    return "@" in value and "." in value.rsplit("@", 1)[-1]


def _resolve_reset_recipient(username: str) -> "str | None":
    """Where to send a password-reset email for `username`.

    MEMAR users authenticate by username, and the shipped default admin's username
    is literally "admin" (NOT an email) — addressing reset mail to the username
    silently fails to deliver for that account. If the username is itself email-
    shaped, use it; otherwise fall back to MEMAR_ADMIN_EMAIL. Returns None when no
    deliverable address can be determined (caller then skips the send)."""
    if _looks_like_email(username):
        return username.strip()
    admin_email = os.getenv("MEMAR_ADMIN_EMAIL", "").strip()
    return admin_email or None



def _public_url() -> str:
    """Base URL for links in outgoing mail. Same source as the setup link and the
    SSO callbacks (firstrun.public_base_url), so the three never disagree. When that
    resolves only to 'localhost' (inside a container, with no MEMAR_PUBLIC_URL) it is
    useless to a recipient, so return empty and let callers say 'not configured'."""
    from .firstrun import public_base_url
    url = public_base_url().rstrip("/")
    if "localhost" in url or "127.0.0.1" in url:
        return ""
    return url

async def send_license_email(email: str, tier: str, license_key: str) -> bool:
    """Send license key via SMTP. Returns True on success."""
    try:
        subject = f"Your MEMAR {tier.title()} License Key"
        body_text = f"""Your MEMAR license key is ready.

Tier: {tier.title()}
License Key:
{license_key}

To activate:
1. Open your MEMAR instance
2. Go to Settings → License
3. Paste the key above and click Activate

Or set the environment variable:
  MEMAR_LICENSE_KEY={license_key}
  (restart MEMAR after setting)

Questions? Reply to this email.

— MEMAR by Stratum Industries
"""

        safe_tier = html.escape(tier.title())
        safe_key = html.escape(license_key)
        body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:system-ui,-apple-system,sans-serif;color:#e8e8e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0d;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#111;border-radius:8px;border:1px solid #222;padding:40px;">
        <tr><td>
          <h1 style="margin:0 0 8px;font-size:22px;color:#e8e8e8;">Your MEMAR {safe_tier} License Key</h1>
          <p style="margin:0 0 24px;color:#999;font-size:14px;">Your license key is ready to activate.</p>

          <p style="margin:0 0 8px;font-size:14px;color:#bbb;">Tier: <strong style="color:#e8e8e8;">{safe_tier}</strong></p>
          <p style="margin:0 0 8px;font-size:14px;color:#bbb;">License Key:</p>
          <code style="background:#1a1a1a;padding:12px 16px;display:block;border-radius:6px;word-break:break-all;font-size:13px;border:1px solid #333;color:#e8e8e8;">{safe_key}</code>

          <h2 style="margin:32px 0 12px;font-size:16px;color:#e8e8e8;">Activation Steps</h2>
          <ol style="margin:0 0 24px;padding-left:20px;color:#bbb;font-size:14px;line-height:1.8;">
            <li>Open your MEMAR instance</li>
            <li>Go to <strong style="color:#e8e8e8;">Settings &rarr; License</strong></li>
            <li>Paste the key above and click <strong style="color:#e8e8e8;">Activate</strong></li>
          </ol>

          <p style="margin:0 0 8px;font-size:13px;color:#777;">Or set the environment variable and restart:</p>
          <code style="background:#1a1a1a;padding:10px 14px;display:block;border-radius:6px;font-size:12px;border:1px solid #333;color:#aaa;">MEMAR_LICENSE_KEY={safe_key}</code>

          <hr style="margin:32px 0;border:none;border-top:1px solid #222;">
          <p style="margin:0;font-size:12px;color:#555;">&mdash; MEMAR by Stratum Industries</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

        return await _send([email], subject, body_text, body_html)

    except Exception as e:
        logger.error(f"Failed to send license email: {e}")
        return False


async def send_payment_failed_email(email: str, amount_due_cents: int) -> bool:
    """Send payment failure notice via SMTP. Returns True on success."""
    try:
        amount_str = f"{amount_due_cents / 100:.2f}"
        public_url = _public_url()
        billing_url = f"{public_url}/?billing=update" if public_url else "[billing URL not configured]"
        subject = "MEMAR Payment Failed"

        body_text = f"""Payment of ${amount_str} failed.

Please update your payment method within 7 days to avoid service interruption.

Update your payment method here:
{billing_url}

Questions? Reply to this email.

— MEMAR by Stratum Industries
"""

        body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:system-ui,-apple-system,sans-serif;color:#e8e8e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0d;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#111;border-radius:8px;border:1px solid #222;padding:40px;">
        <tr><td>
          <h1 style="margin:0 0 8px;font-size:22px;color:#e8e8e8;">Payment of ${amount_str} failed</h1>
          <p style="margin:0 0 24px;color:#999;font-size:14px;">There was an issue processing your payment.</p>

          <p style="margin:0 0 24px;font-size:15px;color:#bbb;line-height:1.6;">
            Please update your payment method within <strong style="color:#e8e8e8;">7 days</strong>
            to avoid service interruption.
          </p>

          <a href="{billing_url}"
             style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;font-size:14px;font-weight:600;">
            Update Payment Method
          </a>

          <p style="margin:24px 0 0;font-size:13px;color:#777;">
            Or copy this link into your browser:<br>
            <span style="color:#aaa;">{billing_url}</span>
          </p>

          <hr style="margin:32px 0;border:none;border-top:1px solid #222;">
          <p style="margin:0;font-size:12px;color:#555;">&mdash; MEMAR by Stratum Industries</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

        return await _send([email], subject, body_text, body_html)

    except Exception as e:
        logger.error(f"Failed to send payment failed email: {e}")
        return False


async def send_renewal_warning_email(
    email: str,
    tier: str,
    days_left: int,
    expires_at,
) -> bool:
    """Send a one-time license expiry warning. Returns True on success."""
    try:
        from datetime import datetime as _dt
        expires_str = expires_at.strftime("%B %d, %Y") if hasattr(expires_at, "strftime") else str(expires_at)
        public_url = _public_url()
        billing_url = f"{public_url}/?billing=true" if public_url else "[billing URL not configured]"
        subject = f"MEMAR {tier.title()} license expires in {days_left} day{'s' if days_left != 1 else ''}"

        body_text = f"""Your MEMAR {tier.title()} license expires on {expires_str} ({days_left} days from now).

If your subscription is still active, your license key will be renewed automatically on your next billing date — no action needed.

If you have cancelled or are on an annual / air-gap license, renew before the expiry date to avoid service interruption.

Update billing:
{billing_url}

Questions? Reply to this email.

— MEMAR by Stratum Industries
"""

        body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:system-ui,-apple-system,sans-serif;color:#e8e8e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0d;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#111;border-radius:8px;border:1px solid #222;padding:40px;">
        <tr><td>
          <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#8a8a8a;margin-bottom:8px;">MEMAR Fleet Alert</div>
          <h1 style="margin:0 0 8px;font-size:22px;color:#e0b84a;">License expires in {days_left} day{'s' if days_left != 1 else ''}</h1>
          <p style="margin:0 0 24px;color:#999;font-size:14px;">Your {tier.title()} license expires on <strong style="color:#e8e8e8;">{expires_str}</strong>.</p>

          <div style="background:#1a1a1a;border:1px solid #333;border-left:3px solid #e0b84a;border-radius:6px;padding:16px 20px;margin-bottom:24px;">
            <p style="margin:0;font-size:14px;color:#bbb;line-height:1.6;">
              <strong style="color:#e8e8e8;">Active subscription?</strong> Your license key renews automatically — no action needed.<br>
              <strong style="color:#e8e8e8;">Cancelled or annual/air-gap?</strong> Renew before the expiry date to avoid service interruption.
            </p>
          </div>

          <a href="{billing_url}"
             style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;font-size:14px;font-weight:600;">
            Update Billing →
          </a>

          <p style="margin:24px 0 0;font-size:13px;color:#777;">
            Or copy this link:<br>
            <span style="color:#aaa;">{billing_url}</span>
          </p>

          <hr style="margin:32px 0;border:none;border-top:1px solid #222;">
          <p style="margin:0;font-size:12px;color:#555;">&mdash; MEMAR by Stratum Industries</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

        return await _send([email], subject, body_text, body_html)

    except Exception as e:
        logger.error("Failed to send renewal warning email: %s", e)
        return False


async def send_password_reset_email(username: str, reset_url: str) -> bool:
    """Send a password-reset link. Returns True on success."""
    recipient = _resolve_reset_recipient(username)
    if not recipient:
        logger.warning(
            "No deliverable email for password reset (username=%r is not email-shaped "
            "and MEMAR_ADMIN_EMAIL is unset); skipping send", username
        )
        return False

    try:
        subject = "MEMAR — password reset"
        body_text = f"""A password reset was requested for your MEMAR account ({username}).

Click the link below to set a new password (expires in 15 minutes):
{reset_url}

If you did not request this, ignore this email — no action is needed.

— MEMAR by Stratum Industries
"""
        safe_url = html.escape(reset_url)
        body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:system-ui,-apple-system,sans-serif;color:#e8e8e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0d;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#111;border-radius:8px;border:1px solid #222;padding:40px;">
        <tr><td>
          <h1 style="margin:0 0 8px;font-size:22px;color:#e8e8e8;">Reset your password</h1>
          <p style="margin:0 0 24px;color:#999;font-size:14px;">A reset was requested for account <strong style="color:#e8e8e8;">{html.escape(username)}</strong>. Link expires in 15 minutes.</p>
          <a href="{safe_url}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;font-size:14px;font-weight:600;">
            Reset password
          </a>
          <p style="margin:24px 0 0;font-size:13px;color:#777;">Or copy this link:<br><span style="color:#aaa;">{safe_url}</span></p>
          <p style="margin:16px 0 0;font-size:13px;color:#555;">If you did not request this, ignore this email — no action needed.</p>
          <hr style="margin:32px 0;border:none;border-top:1px solid #222;">
          <p style="margin:0;font-size:12px;color:#555;">&mdash; MEMAR by Stratum Industries</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

        return await _send([recipient], subject, body_text, body_html)

    except Exception as e:
        logger.error("Failed to send password reset email: %s", e)
        return False


async def send_welcome_email(email: str, tier: str) -> bool:
    """Send a welcome / getting-started email after a successful purchase."""
    try:
        public_url = _public_url().rstrip("/")
        docs_url = f"{public_url}/docs" if public_url else "https://stratum.industries/memar/docs"
        subject = f"Welcome to MEMAR {tier.title()} — getting started"
        body_text = f"""Welcome to MEMAR {tier.title()}!

Your license key was emailed separately. To get started:

1. Set MEMAR_LICENSE_KEY=<your key> in your .env file and restart MEMAR
   — or paste it into Settings → License → Activate
2. Add your first device: Settings → Add device
3. Watch the fleet matrix update in real time

Documentation: {docs_url}

Questions? Reply to this email.

— MEMAR by Stratum Industries
"""
        safe_docs = html.escape(docs_url)
        body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:system-ui,-apple-system,sans-serif;color:#e8e8e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0d;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#111;border-radius:8px;border:1px solid #222;padding:40px;">
        <tr><td>
          <h1 style="margin:0 0 8px;font-size:22px;color:#e8e8e8;">Welcome to MEMAR {html.escape(tier.title())}</h1>
          <p style="margin:0 0 24px;color:#999;font-size:14px;">Your license key was emailed separately. Here's how to get started quickly.</p>
          <h2 style="margin:0 0 12px;font-size:16px;color:#e8e8e8;">Quick-start steps</h2>
          <ol style="margin:0 0 24px;padding-left:20px;color:#bbb;font-size:14px;line-height:1.8;">
            <li>Set <code style="background:#1a1a1a;padding:2px 6px;border-radius:4px;color:#e8e8e8;">MEMAR_LICENSE_KEY=&lt;your key&gt;</code> and restart MEMAR — or paste it via Settings → License → Activate</li>
            <li>Add your first device: <strong style="color:#e8e8e8;">Settings &rarr; Add device</strong></li>
            <li>Watch the fleet matrix update in real time</li>
          </ol>
          <a href="{safe_docs}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;font-size:14px;font-weight:600;">
            View documentation
          </a>
          <hr style="margin:32px 0;border:none;border-top:1px solid #222;">
          <p style="margin:0;font-size:12px;color:#555;">Questions? Reply to this email &mdash; MEMAR by Stratum Industries</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

        return await _send([email], subject, body_text, body_html)

    except Exception as e:
        logger.error("Failed to send welcome email: %s", e)
        return False


async def send_cancellation_email(email: str, tier: str, expires_at) -> bool:
    """Send a subscription cancellation confirmation. Returns True on success."""
    try:
        expires_str = expires_at.strftime("%B %d, %Y") if hasattr(expires_at, "strftime") else str(expires_at)
        public_url = _public_url().rstrip("/")
        billing_url = f"{public_url}/?billing=true" if public_url else ""
        subject = f"MEMAR {tier.title()} subscription cancelled"
        body_text = f"""Your MEMAR {tier.title()} subscription has been cancelled.

Your access continues until: {expires_str}

After that date your license key will stop working and you will be moved to the free tier (up to 5 devices).

If this was a mistake or you'd like to reactivate, reply to this email.

— MEMAR by Stratum Industries
"""
        safe_billing = html.escape(billing_url)
        reactivate_link = (
            f'<a href="{safe_billing}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 24px;border-radius:6px;font-size:14px;font-weight:600;">Reactivate subscription</a>'
            if billing_url else ""
        )
        body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:system-ui,-apple-system,sans-serif;color:#e8e8e8;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0d0d0d;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#111;border-radius:8px;border:1px solid #222;padding:40px;">
        <tr><td>
          <h1 style="margin:0 0 8px;font-size:22px;color:#e8e8e8;">Subscription cancelled</h1>
          <p style="margin:0 0 24px;color:#999;font-size:14px;">Your MEMAR {html.escape(tier.title())} subscription has been cancelled.</p>
          <div style="background:#1a1a1a;border:1px solid #333;border-left:3px solid #e0b84a;border-radius:6px;padding:16px 20px;margin-bottom:24px;">
            <p style="margin:0;font-size:14px;color:#bbb;line-height:1.6;">
              Your access continues until <strong style="color:#e8e8e8;">{html.escape(expires_str)}</strong>.<br>
              After that your key stops working and you drop to the free tier (5 devices).
            </p>
          </div>
          {reactivate_link}
          <p style="margin:24px 0 0;font-size:13px;color:#777;">Changed your mind? Reply to this email and we'll sort it out.</p>
          <hr style="margin:32px 0;border:none;border-top:1px solid #222;">
          <p style="margin:0;font-size:12px;color:#555;">&mdash; MEMAR by Stratum Industries</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

        return await _send([email], subject, body_text, body_html)

    except Exception as e:
        logger.error("Failed to send cancellation email: %s", e)
        return False


async def _send(recipients: list[str], subject: str, body_text: str, body_html: str | None = None) -> bool:
    """Low-level SMTP send to one or more recipients. Returns True on success.

    Single place every email-sending function in this module routes through —
    TLS mode and auth are decided here once (via SMTP_TLS_MODE /
    SMTP_ALLOW_UNAUTHENTICATED) rather than duplicated at each call site.
    """
    if not SMTP_ALLOW_UNAUTHENTICATED and (not SMTP_USER or not SMTP_PASSWORD):
        logger.warning("SMTP credentials not configured; skipping email")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body_text, "plain"))
        if body_html:
            msg.attach(MIMEText(body_html, "html"))
        connect_kwargs: dict = {"hostname": SMTP_HOST, "port": SMTP_PORT}
        if SMTP_TLS_MODE == "implicit":
            connect_kwargs["use_tls"] = True
        elif SMTP_TLS_MODE != "none":
            connect_kwargs["start_tls"] = True
        async with aiosmtplib.SMTP(**connect_kwargs) as smtp:
            if SMTP_USER:
                await smtp.login(SMTP_USER, SMTP_PASSWORD)
            await smtp.sendmail(SMTP_FROM, recipients, msg.as_string())
        logger.info(f"Email sent to {recipients}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


async def send_alert(subject: str, body: str, to=None, body_html: str | None = None,
                     device_id: str | None = None) -> bool:
    """Send an operational alert email.

    Recipients: `to` (str or list) if given, else the comma-separated
    MEMAR_ALERT_EMAILS env var. `device_id` is accepted for caller convenience
    (e.g. the coolant AlertRouter) and is not otherwise required.
    Returns True on success, False if no recipients/SMTP are configured.
    """
    if isinstance(to, str):
        recipients = [to]
    elif to:
        recipients = list(to)
    else:
        recipients = [e.strip() for e in os.getenv("MEMAR_ALERT_EMAILS", "").split(",") if e.strip()]
    if not recipients:
        logger.info("No alert recipients (MEMAR_ALERT_EMAILS unset); skipping alert: %s", subject)
        return False
    # Operational alerts historically went out plain-text only. Auto-wrap them in
    # the branded HTML shell so every caller (coolant, webhook, ...) gets a styled
    # multipart email for free; callers that pass body_html keep full control.
    if body_html is None:
        body_html = _brand_alert_html(subject, body)
    return await _send(recipients, subject, body, body_html)


def _brand_alert_html(subject: str, body_text: str) -> str:
    """Wrap a plain-text alert body in MEMAR's dark branded HTML shell."""
    safe_body = html.escape(body_text).replace("\n", "<br>")
    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0d0d0d;font-family:system-ui,-apple-system,sans-serif;color:#e8e8e8;">
  <div style="max-width:560px;margin:0 auto;padding:32px 24px;">
    <div style="font-size:13px;letter-spacing:0.12em;text-transform:uppercase;color:#8a8a8a;margin-bottom:8px;">MEMAR Fleet Alert</div>
    <h1 style="font-size:20px;margin:0 0 16px;color:#f5f5f5;">{html.escape(subject)}</h1>
    <div style="font-size:15px;line-height:1.6;color:#d8d8d8;">{safe_body}</div>
    <div style="margin-top:28px;padding-top:16px;border-top:1px solid #262626;font-size:12px;color:#6a6a6a;">Sent by MEMAR · self-hosted fleet monitoring</div>
  </div>
</body>
</html>"""
