"""License key system with Ed25519 verification and feature gating."""

import base64
import json
import os
from dataclasses import dataclass
from datetime import date
import logging

import nacl.signing
import nacl.exceptions


logger = logging.getLogger(__name__)


# Embedded Ed25519 public key (base64) — the root of trust for license
# verification. Every shipped/customer instance verifies license keys against
# this. The matching PRIVATE key lives ONLY on the issuer instance
# (MEMAR_LICENSE_PRIVATE_KEY) and signs every key sold. Rotating this requires
# re-issuing all outstanding licenses, so it changes rarely.
# Generated 2026-06-14 (replaces the dev placeholder whose private key was unknown).
EMBEDDED_PUBLIC_KEY_B64 = "MBK+pVwNJE25P5jHXUeTwDXPuDw5doCaNKxNdm+q2ug="

# Default key id for the embedded Ed25519 root of trust.
DEFAULT_KID = "k1"


# ── Cryptographic agility ────────────────────────────────────────────────────
# License keys carry their own algorithm (`alg`) + key id (`kid`), so the signing
# scheme can evolve (add post-quantum Falcon/ML-DSA, or a hybrid) WITHOUT a format
# redesign or breaking already-issued keys. To migrate later:
#   1. add a verifier to _VERIFIERS,
#   2. register the new public key under a new kid in _public_key_for(),
#   3. point the signer (stripe_webhook._generate_license_key) at the new alg/kid.
# Old keys keep verifying via their own alg/kid. "none" is never allowed
# (prevents algorithm-confusion / downgrade attacks).

def _verify_ed25519(pubkey_b64: str, message: bytes, sig: bytes) -> None:
    """Verify an Ed25519 signature. Raises BadSignatureError on failure."""
    nacl.signing.VerifyKey(base64.b64decode(pubkey_b64)).verify(message, sig)


_VERIFIERS = {
    "ed25519": _verify_ed25519,
    # "falcon": _verify_falcon,   # ← future post-quantum slot (FN-DSA)
}
_ALLOWED_ALGS = set(_VERIFIERS)  # allowlist; never includes "none"

# Future PQC / rotated keys: kid -> (alg, public_key_b64).
_KEY_REGISTRY: dict[str, tuple[str, str]] = {}


def _public_key_for(kid: str | None) -> tuple[str, str]:
    """Resolve a key id to (alg, public_key_b64)."""
    if kid in (None, DEFAULT_KID):
        # Embedded Ed25519 root, overridable via env for testing/rotation.
        return "ed25519", os.getenv("MEMAR_LICENSE_PUBLIC_KEY", EMBEDDED_PUBLIC_KEY_B64)
    reg = _KEY_REGISTRY.get(kid)
    if reg is None:
        raise ValueError(f"unknown license key id: {kid!r}")
    return reg


def _verify_license(license_key: str) -> dict:
    """
    Verify a license key and return its claims dict. Raises on failure
    (BadSignatureError for a bad signature; ValueError for bad format/alg).

    Two wire formats are accepted:
      • agile : base64(JSON {alg, kid, ver, claims:b64, sig:b64})   ← current
      • legacy: base64(64-byte Ed25519 sig || claims-JSON)          ← pre-agility keys
    """
    raw = base64.b64decode(license_key)

    # Agile envelope?
    env = None
    try:
        cand = json.loads(raw.decode("utf-8"))
        if isinstance(cand, dict) and {"alg", "sig", "claims"} <= cand.keys():
            env = cand
    except (ValueError, UnicodeDecodeError):
        env = None

    if env is not None:
        alg = env.get("alg")
        kid = env.get("kid", DEFAULT_KID)
        if alg not in _ALLOWED_ALGS:
            raise ValueError(f"unsupported/disallowed license alg: {alg!r}")
        key_alg, pubkey_b64 = _public_key_for(kid)
        if key_alg != alg:
            raise ValueError(f"alg/kid mismatch: kid {kid!r} is {key_alg}, not {alg}")
        claims_bytes = base64.b64decode(env["claims"])
        _VERIFIERS[alg](pubkey_b64, claims_bytes, base64.b64decode(env["sig"]))
        return json.loads(claims_bytes.decode("utf-8"))

    # Legacy: 64-byte Ed25519 sig || payload.
    if len(raw) < 64:
        raise ValueError("license key too short (expected sig + payload)")
    sig_bytes, payload_bytes = raw[:64], raw[64:]
    _, pubkey_b64 = _public_key_for(DEFAULT_KID)
    _verify_ed25519(pubkey_b64, payload_bytes, sig_bytes)
    return json.loads(payload_bytes.decode("utf-8"))


@dataclass
class LicenseState:
    """License state snapshot."""

    tier: str  # free, maker, farm, scale, enterprise
    device_limit: int
    expires_at: str | None  # ISO date string
    features: list[str]
    customer_id: str | None
    active: bool
    warning: str | None = None


# Module-level license state singleton.
_state: LicenseState | None = None


def get_license() -> LicenseState:
    """Get the current license state. Re-evaluates expiry on each call (not just at load time)."""
    global _state
    if _state is None:
        _state = LicenseState(
            tier="free",
            device_limit=5,
            expires_at=None,
            features=_tier_to_features("free"),
            customer_id=None,
            active=True,
            warning=None,
        )

    # M1 BUG FIX: Re-check expiry on every call. The initial load_license_from_env()
    # checks expiry once at startup, but if the license was active at that time and
    # later the expiry date passes, the in-memory _state.active would stay True until
    # the process restarts. This re-check catches the transition to expired mid-lifetime.
    # Air-gap/perpetual licenses (expires_at=None) stay active indefinitely — guard that.
    if _state.active and _state.expires_at is not None:
        try:
            expiry = date.fromisoformat(_state.expires_at)
            if date.today() > expiry:
                _state = LicenseState(
                    tier="free",
                    device_limit=5,
                    expires_at=_state.expires_at,
                    features=_tier_to_features("free"),
                    customer_id=_state.customer_id,
                    active=False,
                    warning=f"Expired on {_state.expires_at}",
                )
        except (ValueError, TypeError):
            pass  # malformed date, trust existing state

    return _state


def _tier_to_features(tier: str) -> list[str]:
    """Map tier name to list of enabled features.

    Product model: any PAID tier unlocks the full feature set — tiers differ
    from each other only by device-count limit (see billing.DEVICE_LIMITS /
    billing.PROFESSIONAL_DEVICE_LIMITS). The free tier is the one exception:
    it gets none of these, so there's an actual reason to upgrade.
    require_feature() 402s both an inactive/expired key and a feature missing
    from the active tier's list. An unknown tier returns [] (no features).
    """
    _ALL = [
        "multi_user", "webhooks", "rbac", "floor_plan", "oee", "email_alerts",
        "sso", "audit_logs", "compliance_export", "custom_branding",
    ]
    tier_map = {
        t: _ALL
        for t in (
            "maker", "pro", "farm", "scale",
            "workshop", "business", "enterprise",
            "airgap", "airgap_standard", "airgap_enterprise",
        )
    }
    tier_map["free"] = []
    return tier_map.get(tier, [])


def load_license_from_env() -> None:
    """
    Load and verify license key from MEMAR_LICENSE_KEY env var.
    On error: log WARNING, keep free tier (never abort startup).
    """
    global _state

    license_key = os.getenv("MEMAR_LICENSE_KEY")
    if not license_key:
        logger.info("No license key provided, using free tier")
        _state = LicenseState(
            tier="free",
            device_limit=5,
            expires_at=None,
            features=_tier_to_features("free"),
            customer_id=None,
            active=True,
            warning=None,
        )
        return

    try:
        # Verify + decode (alg/kid-agile, with legacy-format fallback).
        try:
            payload = _verify_license(license_key)
        except nacl.exceptions.BadSignatureError:
            logger.warning("License signature verification failed")
            _state = LicenseState(
                tier="free",
                device_limit=5,
                expires_at=None,
                features=_tier_to_features("free"),
                customer_id=None,
                active=True,
                warning="Invalid signature",
            )
            return

        # Validate expiry
        expiry_str = payload.get("expires_at")
        if expiry_str:
            expiry = date.fromisoformat(expiry_str)
            if date.today() > expiry:
                logger.warning(f"License expired on {expiry_str}; reverting to free tier (hard cutoff)")
                # Hard cutoff: an expired key drops to the free tier (free
                # device limit) with active=False. Under the all-features model
                # the free tier's feature LIST is the full set, so the lockout is
                # enforced solely by active=False — every feature gate
                # (require_feature, branding, sso, email alerts) fails closed when
                # the license is inactive. The free-tier 5-device cap also binds.
                _state = LicenseState(
                    tier="free",
                    device_limit=5,
                    expires_at=expiry_str,
                    features=_tier_to_features("free"),
                    customer_id=payload.get("customer_id"),
                    active=False,
                    warning=f"Expired on {expiry_str}",
                )
                return

        # Success
        tier = payload.get("tier", "free")
        _state = LicenseState(
            tier=tier,
            device_limit=payload.get("device_limit", 5),
            expires_at=expiry_str,
            features=_tier_to_features(tier),
            customer_id=payload.get("customer_id"),
            active=True,
            warning=None,
        )
        logger.info(f"License loaded: tier={tier}, customer={_state.customer_id}, expires={expiry_str}")

    except Exception as e:
        logger.warning(f"Failed to load license: {e}; using free tier")
        _state = LicenseState(
            tier="free",
            device_limit=5,
            expires_at=None,
            features=_tier_to_features("free"),
            customer_id=None,
            active=True,
            warning=str(e),
        )


def warn_device_count(enabled_count: int) -> None:
    """Log warning if device count exceeds license limit."""
    license_state = get_license()
    if enabled_count > license_state.device_limit:
        logger.warning(
            f"Device count ({enabled_count}) exceeds license limit ({license_state.device_limit}); "
            "new device additions will be blocked"
        )


def apply_license(key: str) -> bool:
    """Apply a license key at runtime (no restart needed). Returns True if valid."""
    global _state
    original_state = _state

    try:
        old_key = os.environ.get("MEMAR_LICENSE_KEY")
        os.environ["MEMAR_LICENSE_KEY"] = key
        load_license_from_env()

        # Restore original env var
        if old_key is None:
            del os.environ["MEMAR_LICENSE_KEY"]
        else:
            os.environ["MEMAR_LICENSE_KEY"] = old_key

        if _state.active and _state.tier != "free":
            return True
        # Key was invalid/expired — don't silently downgrade a working license.
        _state = original_state
        return False
    except Exception as e:
        logger.error(f"apply_license failed: {e}")
        _state = original_state
        return False


async def license_reload_loop(interval_s: int = 60) -> None:
    """Periodically reconcile this worker's in-memory license with the DB.

    The env-var key (MEMAR_LICENSE_KEY) is authoritative and identical across all
    uvicorn workers, so when it's set this is a no-op. It only matters for the
    runtime API-activation flow (a key applied via /api/license/activate on one
    worker): this loop lets the other workers pick up the latest activated license
    from the DB within interval_s, so multi-worker deployments converge.
    """
    import asyncio
    while True:
        await asyncio.sleep(interval_s)
        if os.getenv("MEMAR_LICENSE_KEY"):
            continue
        try:
            from .db import AsyncSessionLocal
            async with AsyncSessionLocal() as db:
                await load_license_from_db(db)
        except Exception as e:  # noqa: BLE001
            logger.debug("license reload failed: %s", e)


async def load_license_from_db(db) -> None:
    """Load license from DB on startup. Called AFTER load_license_from_env()."""
    from sqlalchemy import select
    from .models_db import IssuedLicense

    # If env var is set, env takes precedence
    if os.getenv("MEMAR_LICENSE_KEY"):
        logger.info("License key from env var takes precedence over DB")
        return

    try:
        result = await db.execute(
            select(IssuedLicense)
            .where(IssuedLicense.activated == True)  # noqa: E712
            .order_by(IssuedLicense.issued_at.desc())
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        if latest:
            logger.info(f"Loading license from DB: tier={latest.tier}")
            apply_license(latest.license_key)
    except Exception as e:
        logger.warning(f"Failed to load license from DB: {e}")


# ── Online subscription heartbeat (auto-refresh) ─────────────────────────────
# Optional: when MEMAR_LICENSE_HEARTBEAT_URL is set, the instance periodically
# asks the remote endpoint "is my subscription still active?". While active, the
# endpoint returns a freshly-signed key with a later expiry, which we apply +
# persist — so renewals never need a manual key paste (max enforcement, min
# friction). If the endpoint is unreachable or reports inactive, we HOLD the
# current key; it lapses on its own embedded expiry (the grace window). Air-gap /
# perpetual licenses (no expiry) are skipped entirely — they never phone home.


async def _current_license_key() -> str | None:
    """The key string to present to the heartbeat — env var if set, else the
    latest DB-activated key."""
    key = os.getenv("MEMAR_LICENSE_KEY")
    if key:
        return key
    from sqlalchemy import select
    from .db import AsyncSessionLocal
    from .models_db import IssuedLicense
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(IssuedLicense).where(IssuedLicense.activated == True)  # noqa: E712
            .order_by(IssuedLicense.issued_at.desc()).limit(1))).scalar_one_or_none()
        return row.license_key if row else None


async def _persist_refreshed_key(key: str) -> None:
    """Persist a heartbeat-refreshed key onto the single latest activated row so a
    restart (or a later worker outage) keeps the most recent valid entitlement."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from .db import AsyncSessionLocal
    from .models_db import IssuedLicense
    try:
        st = get_license()
        exp = (datetime.fromisoformat(st.expires_at).replace(tzinfo=timezone.utc)
               if st.expires_at else datetime.now(timezone.utc) + timedelta(days=3650))
        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(IssuedLicense).where(IssuedLicense.activated == True)  # noqa: E712
                .order_by(IssuedLicense.issued_at.desc()).limit(1))).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if row is not None:
                row.license_key, row.expires_at, row.activated_at = key, exp, now
                row.tier, row.device_limit = st.tier, st.device_limit
            else:
                db.add(IssuedLicense(
                    stripe_customer_id=st.customer_id or "heartbeat", email="heartbeat@local",
                    tier=st.tier, device_limit=st.device_limit, license_key=key,
                    stripe_session_id=f"heartbeat_{int(now.timestamp())}",
                    expires_at=exp, activated=True, activated_at=now))
            await db.commit()
    except Exception as e:  # noqa: BLE001 — persistence is best-effort
        logger.debug("heartbeat persist failed: %s", e)


async def _run_license_heartbeat(url: str) -> None:
    """One heartbeat cycle: refresh the key if the subscription is active."""
    state = get_license()
    # Skipped entirely — these never phone home:
    #   • free        — nothing to refresh
    #   • air-gap     — sold time-boxed but renews out-of-band (new key file),
    #                   so even with an embedded expiry it must make zero egress
    #   • perpetual   — no expiry, nothing to renew
    if state.tier == "free" or state.tier.startswith("airgap") or state.expires_at is None:
        return
    key = await _current_license_key()
    if not key:
        return
    from .license_client import fetch_license_status
    resp = await fetch_license_status(url, key)
    if not resp or not (resp.get("active") and resp.get("license_key")):
        return  # inactive/unreachable → hold; current key lapses at its own expiry
    if apply_license(resp["license_key"]):
        await _persist_refreshed_key(resp["license_key"])
        logger.info("license auto-refreshed via heartbeat (tier=%s, expires=%s)",
                    get_license().tier, resp.get("expires_at"))


# Heartbeat endpoint is disabled by default for offline-first operation.
# To enable heartbeat (optional auto-renewal), set MEMAR_LICENSE_HEARTBEAT_URL
# to the endpoint URL. Free + air-gap licenses skip heartbeat regardless.
DEFAULT_HEARTBEAT_URL = ""


async def license_heartbeat_loop(interval_s: int = 3600) -> None:
    """Periodic license refresh against the heartbeat endpoint (disabled by default —
    DEFAULT_HEARTBEAT_URL is empty; set MEMAR_LICENSE_HEARTBEAT_URL to the endpoint
    URL to enable optional auto-renewal). Runs immediately
    on start (to close any post-restart gap), then every interval_s. Free + air-gap
    licenses are handled inside _run_license_heartbeat (early return / skip)."""
    import asyncio
    url = os.getenv("MEMAR_LICENSE_HEARTBEAT_URL", DEFAULT_HEARTBEAT_URL)
    if not url:  # explicitly emptied → disabled
        return
    while True:
        try:
            await _run_license_heartbeat(url)
        except Exception as e:  # noqa: BLE001
            logger.debug("license heartbeat cycle error: %s", e)
        await asyncio.sleep(interval_s)


# Days before expiry to send the proactive warning email (separate from the
# 14-day UI banner in billing.py — email goes earlier to reach users who don't log in).
_RENEWAL_EMAIL_DAYS = 30


async def _check_renewal_warnings() -> None:
    """Find activated licenses expiring within _RENEWAL_EMAIL_DAYS and send one-time warning emails."""
    import math
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, and_
    from .db import AsyncSessionLocal
    from .models_db import IssuedLicense
    from .email_service import send_renewal_warning_email

    now = datetime.now(timezone.utc)
    threshold = now + timedelta(days=_RENEWAL_EMAIL_DAYS)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(IssuedLicense).where(
                and_(
                    IssuedLicense.activated == True,  # noqa: E712
                    IssuedLicense.expires_at.isnot(None),
                    IssuedLicense.expires_at > now,
                    IssuedLicense.expires_at <= threshold,
                    IssuedLicense.renewal_warning_sent_at.is_(None),
                )
            )
        )
        expiring = result.scalars().all()
        for lic in expiring:
            exp = lic.expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            days_left = max(0, math.ceil((exp - now).total_seconds() / 86400))
            sent = await send_renewal_warning_email(
                email=lic.email,
                tier=lic.tier,
                days_left=days_left,
                expires_at=exp,
            )
            if sent:
                lic.renewal_warning_sent_at = now
        if expiring:
            await db.commit()


async def renewal_warning_loop(interval_s: int = 86400) -> None:
    """Daily loop: send one-time expiry warning emails 30 days before license expiry.
    Fires immediately on startup (catches gaps if the server was down), then daily."""
    import asyncio
    while True:
        try:
            await _check_renewal_warnings()
        except Exception as e:  # noqa: BLE001
            logger.debug("renewal warning check error: %s", e)
        await asyncio.sleep(interval_s)
