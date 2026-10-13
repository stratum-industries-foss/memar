#!/usr/bin/env python3
"""
MEMAR production preflight validator.

Reads the environment and reports, grouped by subsystem, whether each variable
is present and sane. Exits 0 if everything REQUIRED (for the active mode) is
present, 1 otherwise.

Design rules (anchored to what the code actually enforces — verified by grep):
  * The ONLY var the app hard-refuses to boot without is MEMAR_JWT_SECRET, and
    only when MEMAR_ENV=production (auth.py raises RuntimeError). A green
    preflight in production means "it will actually boot and links/redirects
    will work" — not "every feature is configured."
  * License PRIVATE key is issuer-only (one instance) — never globally required.
  * License PUBLIC key has an embedded default in license.py — optional override.
  * Stripe is conditional: only if MEMAR_STRIPE_SECRET_KEY is set do the webhook
    secret + non-placeholder price IDs become required.
  * SMTP is conditional: only validated as a coherent set if any SMTP var is set.

Self-contained: imports only stdlib. Does NOT import the MEMAR app (importing
backend.app.auth would trigger the JWT boot logic and could itself raise in
production mode). The var names below are hardcoded from a grep of backend/app.

Run (from backend/):
    ../.venv/bin/python scripts/preflight.py
"""

import base64
import os
import sys


# --- status levels ---------------------------------------------------------
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

_COLOR = {
    PASS: "\033[32m",   # green
    WARN: "\033[33m",   # yellow
    FAIL: "\033[31m",   # red
}
_RESET = "\033[0m"
_USE_COLOR = sys.stdout.isatty()


def _tag(level: str) -> str:
    if _USE_COLOR:
        return f"{_COLOR[level]}{level:<4}{_RESET}"
    return f"{level:<4}"


class Report:
    """Accumulates check results grouped by subsystem and tracks failures."""

    def __init__(self) -> None:
        self.sections: list[tuple[str, list[tuple[str, str, str]]]] = []
        self.failures = 0
        self.warnings = 0

    def section(self, name: str) -> "Section":
        rows: list[tuple[str, str, str]] = []
        self.sections.append((name, rows))
        return Section(self, rows)

    def render(self) -> None:
        for name, rows in self.sections:
            print(f"\n{name}")
            print("-" * len(name))
            if not rows:
                print("  (nothing to check)")
                continue
            for level, key, msg in rows:
                print(f"  [{_tag(level)}] {key:<34} {msg}")


class Section:
    def __init__(self, report: Report, rows: list) -> None:
        self._report = report
        self._rows = rows

    def add(self, level: str, key: str, msg: str) -> None:
        self._rows.append((level, key, msg))
        if level == FAIL:
            self._report.failures += 1
        elif level == WARN:
            self._report.warnings += 1


# --- helpers ---------------------------------------------------------------
def _b64_len(value: str) -> int | None:
    """Return decoded byte length if base64-decodable, else None."""
    try:
        return len(base64.b64decode(value, validate=True))
    except Exception:
        return None


def main() -> int:
    env = os.environ
    raw_mode = env.get("MEMAR_ENV", "").lower()
    is_prod = raw_mode in ("production", "prod")
    mode_label = "PRODUCTION" if is_prod else (raw_mode or "dev (MEMAR_ENV unset)")

    # In production, treat launch-correctness vars as required (FAIL).
    # In dev, the same gaps are WARN (or skipped).
    req = FAIL if is_prod else WARN

    rep = Report()

    print("=" * 72)
    print(f"  MEMAR Preflight   —   mode: {mode_label}")
    print("=" * 72)

    # --- AUTH ---------------------------------------------------------------
    s = rep.section("AUTH")
    jwt = env.get("MEMAR_JWT_SECRET")
    if not jwt:
        # Boot-blocking in production (auth.py raises RuntimeError).
        s.add(
            FAIL if is_prod else WARN,
            "MEMAR_JWT_SECRET",
            "MISSING — app refuses to boot in production; dev uses a random ephemeral key",
        )
    elif len(jwt) < 32:
        s.add(
            req,
            "MEMAR_JWT_SECRET",
            f"too short ({len(jwt)} chars); use >=32 (e.g. `python -c 'import secrets;print(secrets.token_hex(32))'`)",
        )
    else:
        s.add(PASS, "MEMAR_JWT_SECRET", f"present ({len(jwt)} chars)")

    admin_pw = env.get("MEMAR_ADMIN_PASSWORD")
    if not admin_pw:
        s.add(
            req,
            "MEMAR_ADMIN_PASSWORD",
            "unset — admin password auto-generated to .admin-credentials (not a real launch)",
        )
    else:
        s.add(PASS, "MEMAR_ADMIN_PASSWORD", "set")
    s.add(PASS, "MEMAR_ADMIN_USER", f"= {env.get('MEMAR_ADMIN_USER', 'admin (default)')}")

    no_auth = env.get("MEMAR_NO_AUTH", "").lower() in ("1", "true", "yes")
    if no_auth and is_prod:
        s.add(FAIL, "MEMAR_NO_AUTH", "AUTH DISABLED in production — refuse to ship like this")
    elif no_auth:
        s.add(WARN, "MEMAR_NO_AUTH", "auth bypass enabled (dev only)")

    # --- DEPLOYMENT / URLs --------------------------------------------------
    s = rep.section("DEPLOYMENT")
    pub = env.get("MEMAR_PUBLIC_URL")
    if not pub:
        s.add(
            req,
            "MEMAR_PUBLIC_URL",
            "unset — defaults to localhost; breaks Stripe redirects + email links in prod",
        )
    elif "localhost" in pub or "127.0.0.1" in pub:
        s.add(req if is_prod else PASS, "MEMAR_PUBLIC_URL", f"= {pub} (localhost — not a public URL)")
    else:
        s.add(PASS, "MEMAR_PUBLIC_URL", f"= {pub}")

    owner = env.get("MEMAR_OWNER_EMAIL")
    if not owner:
        s.add(req, "MEMAR_OWNER_EMAIL", "unset — owner notifications/license emails have no recipient")
    else:
        s.add(PASS, "MEMAR_OWNER_EMAIL", f"= {owner}")

    s.add(PASS, "MEMAR_DB_PATH", f"= {env.get('MEMAR_DB_PATH', './memar.db (default)')}")
    s.add(PASS, "MEMAR_DATA_DIR", f"= {env.get('MEMAR_DATA_DIR', './data (default)')}")
    s.add(PASS, "MEMAR_CONFIG_PATH", f"= {env.get('MEMAR_CONFIG_PATH', 'auto-discovered (unset)')}")
    s.add(PASS, "MEMAR_CORS_ORIGINS", f"= {env.get('MEMAR_CORS_ORIGINS', 'localhost dev defaults')}")

    # --- LICENSING ----------------------------------------------------------
    s = rep.section("LICENSING")
    priv = env.get("MEMAR_LICENSE_PRIVATE_KEY")
    if priv:
        n = _b64_len(priv)
        if n is None:
            s.add(FAIL, "MEMAR_LICENSE_PRIVATE_KEY", "set but NOT valid base64")
        elif n != 32:
            s.add(FAIL, "MEMAR_LICENSE_PRIVATE_KEY", f"decodes to {n} bytes; Ed25519 seed must be 32")
        else:
            s.add(
                WARN,
                "MEMAR_LICENSE_PRIVATE_KEY",
                "PRESENT — only correct on the issuer instance; a security risk elsewhere",
            )
    else:
        s.add(PASS, "MEMAR_LICENSE_PRIVATE_KEY", "unset — correct for normal (non-issuer) deployments")

    lic_key = env.get("MEMAR_LICENSE_KEY")
    if lic_key:
        n = _b64_len(lic_key)
        if n is None:
            s.add(WARN, "MEMAR_LICENSE_KEY", "set but NOT valid base64 — will fall back to free tier")
        elif n < 64:
            s.add(WARN, "MEMAR_LICENSE_KEY", f"only {n} bytes; need >= 64 (sig+payload) — free tier")
        else:
            s.add(PASS, "MEMAR_LICENSE_KEY", "signed key present (tier loaded from it if valid)")
    else:
        s.add(PASS, "MEMAR_LICENSE_KEY", "unset — free tier (or loaded from DB)")

    pubkey = env.get("MEMAR_LICENSE_PUBLIC_KEY")
    if pubkey:
        n = _b64_len(pubkey)
        if n is None:
            s.add(FAIL, "MEMAR_LICENSE_PUBLIC_KEY", "set but NOT valid base64")
        elif n != 32:
            s.add(FAIL, "MEMAR_LICENSE_PUBLIC_KEY", f"decodes to {n} bytes; Ed25519 public key must be 32")
        else:
            s.add(PASS, "MEMAR_LICENSE_PUBLIC_KEY", "valid 32-byte override")
    else:
        s.add(PASS, "MEMAR_LICENSE_PUBLIC_KEY", "unset — using embedded default in license.py")

    # --- STRIPE / BILLING (conditional on secret key) -----------------------
    s = rep.section("STRIPE / BILLING")
    stripe_key = env.get("MEMAR_STRIPE_SECRET_KEY")
    if not stripe_key:
        s.add(WARN, "MEMAR_STRIPE_SECRET_KEY", "unset — billing/checkout disabled (self-hosted-without-billing)")
    else:
        if stripe_key.startswith("sk_test_"):
            s.add(req, "MEMAR_STRIPE_SECRET_KEY", "is a TEST key (sk_test_) — use a live key in production")
        elif stripe_key.startswith("sk_live_"):
            s.add(PASS, "MEMAR_STRIPE_SECRET_KEY", "live key set")
        else:
            s.add(WARN, "MEMAR_STRIPE_SECRET_KEY", "set (unrecognized prefix)")

        wh = env.get("MEMAR_STRIPE_WEBHOOK_SECRET")
        if not wh:
            s.add(req, "MEMAR_STRIPE_WEBHOOK_SECRET", "REQUIRED when Stripe is enabled — webhooks won't verify")
        elif not wh.startswith("whsec_"):
            s.add(WARN, "MEMAR_STRIPE_WEBHOOK_SECRET", "set (expected whsec_ prefix)")
        else:
            s.add(PASS, "MEMAR_STRIPE_WEBHOOK_SECRET", "set")

        # Price IDs — placeholders are a FAIL when Stripe is enabled
        # (billing.py rejects anything starting with "price_placeholder").
        price_vars = [
            "MEMAR_STRIPE_PRICE_MAKER", "MEMAR_STRIPE_PRICE_PRO",
            "MEMAR_STRIPE_PRICE_FARM", "MEMAR_STRIPE_PRICE_SCALE",
            "MEMAR_STRIPE_PRICE_MAKER_ANNUAL", "MEMAR_STRIPE_PRICE_PRO_ANNUAL",
            "MEMAR_STRIPE_PRICE_FARM_ANNUAL", "MEMAR_STRIPE_PRICE_SCALE_ANNUAL",
            "MEMAR_STRIPE_PRICE_WORKSHOP", "MEMAR_STRIPE_PRICE_BUSINESS",
            "MEMAR_STRIPE_PRICE_ENTERPRISE",
        ]
        for pv in price_vars:
            val = env.get(pv)
            if not val:
                s.add(req, pv, "unset — checkout for this tier 500s (falls back to placeholder)")
            elif val.startswith("price_placeholder"):
                s.add(req, pv, f"= {val} (PLACEHOLDER — billing.py rejects this)")
            elif not val.startswith("price_"):
                s.add(WARN, pv, f"= {val} (expected a price_… ID)")
            else:
                s.add(PASS, pv, "set")

    # --- EMAIL / SMTP (conditional) -----------------------------------------
    s = rep.section("EMAIL / SMTP")
    smtp_keys = {
        "MEMAR_SMTP_HOST": env.get("MEMAR_SMTP_HOST"),
        "MEMAR_SMTP_PORT": env.get("MEMAR_SMTP_PORT"),
        "MEMAR_SMTP_USER": env.get("MEMAR_SMTP_USER"),
        "MEMAR_SMTP_PASSWORD": env.get("MEMAR_SMTP_PASSWORD"),
        "MEMAR_SMTP_FROM": env.get("MEMAR_SMTP_FROM"),
    }
    any_smtp = any(v for k, v in smtp_keys.items() if k != "MEMAR_SMTP_HOST") or bool(
        env.get("MEMAR_SMTP_USER")
    )
    if not any_smtp:
        s.add(WARN, "MEMAR_SMTP_*", "unset — email reports + license-delivery emails disabled")
    else:
        for key in ("MEMAR_SMTP_HOST", "MEMAR_SMTP_PORT", "MEMAR_SMTP_USER", "MEMAR_SMTP_FROM"):
            v = smtp_keys[key]
            s.add(PASS if v else WARN, key, (f"= {v}" if v else "unset (has default)"))
        # All SMTP modules (email_service.py, email_reports.py, stripe_webhook.py) read MEMAR_SMTP_PASSWORD.
        if smtp_keys["MEMAR_SMTP_PASSWORD"]:
            s.add(PASS, "MEMAR_SMTP_PASSWORD", "set (used by all email modules)")
        else:
            s.add(WARN, "MEMAR_SMTP_PASSWORD", "unset — outbound email won't authenticate")

    # --- OPTIONAL / MISC ----------------------------------------------------
    s = rep.section("OPTIONAL")
    slack = env.get("MEMAR_SLACK_WEBHOOK_URL")
    s.add(PASS if slack else WARN, "MEMAR_SLACK_WEBHOOK_URL", "set" if slack else "unset — Slack alerts disabled")
    s.add(PASS, "MEMAR_DEMO_MODE", f"= {env.get('MEMAR_DEMO_MODE', 'off (default)')}")
    s.add(PASS, "MEMAR_MONITOR_INTERVAL", f"= {env.get('MEMAR_MONITOR_INTERVAL', 'default')}")
    s.add(PASS, "MEMAR_VISION_MODEL", f"= {env.get('MEMAR_VISION_MODEL', 'vision (default)')}")
    s.add(PASS, "MEMAR_PRINT_CV_BIN", f"= {env.get('MEMAR_PRINT_CV_BIN', 'auto (unset)')}")
    s.add(PASS, "MEMAR_SPOOL_CV_BIN", f"= {env.get('MEMAR_SPOOL_CV_BIN', 'auto (unset)')}")

    # --- render + summary ---------------------------------------------------
    rep.render()

    print("\n" + "=" * 72)
    if rep.failures:
        verdict = f"{_tag(FAIL)}  {rep.failures} required check(s) failed, {rep.warnings} warning(s)"
        if not is_prod:
            verdict += "  (note: not in production mode)"
    elif rep.warnings:
        verdict = f"{_tag(WARN)}  all required present, {rep.warnings} warning(s)"
    else:
        verdict = f"{_tag(PASS)}  all checks passed"
    print(f"  {verdict}")
    print("=" * 72)

    return 1 if rep.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
