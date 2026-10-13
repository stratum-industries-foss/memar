# MEMAR deployment scripts

Self-contained tooling for taking the MEMAR backend to production. `mint_license.py`
imports `app.license` to round-trip-verify each key it issues; the others run
standalone against the environment.

Run everything with the project venv. From `backend/`:

```bash
../.venv/bin/python scripts/<script>.py
```

---

## 1. Generate the license keypair — `generate_license_keypair.py`

Generates a fresh Ed25519 keypair (PyNaCl) and prints both halves as base64,
in the exact format `license.py` and `stripe_webhook.py` consume:

- `MEMAR_LICENSE_PRIVATE_KEY` = `base64(bytes(signing_key))` — 32-byte seed
- `MEMAR_LICENSE_PUBLIC_KEY`  = `base64(bytes(verify_key))`  — 32-byte public key

```bash
../.venv/bin/python scripts/generate_license_keypair.py
```

**Key placement (important):**

| Key | Where | Notes |
|-----|-------|-------|
| **PRIVATE** | The **single** issuer instance only (the one receiving Stripe webhooks) | Never on customer/self-hosted boxes. Never commit. Leak = anyone can forge licenses. |
| **PUBLIC** | Every verifying instance, or baked into `EMBEDDED_PUBLIC_KEY_B64` in `license.py` | Safe to distribute — verify-only. |

To rotate: regenerate, redeploy the new public key everywhere, reissue
customer license keys, then retire the old private key.

---

## 2. Preflight validator — `preflight.py`

Reads the environment and prints a PASS/WARN/FAIL report grouped by subsystem
(auth / deployment / licensing / stripe / email / optional). Exit code:

- `0` — all required vars present for the active mode
- `1` — at least one required var missing/invalid

```bash
../.venv/bin/python scripts/preflight.py
```

Mode is driven by `MEMAR_ENV`:

- `MEMAR_ENV=production` — launch-critical vars are **FAIL** if missing.
- anything else (dev/test) — the same gaps are **WARN**; exit stays `0`.

**What's enforced (matches the code, not wishful thinking):**

- `MEMAR_JWT_SECRET` is the one truly boot-blocking var — `auth.py` raises in
  production without it. Checked for length ≥ 32.
- `MEMAR_PUBLIC_URL`, `MEMAR_ADMIN_PASSWORD`, `MEMAR_OWNER_EMAIL` are
  launch-correctness vars (defaults exist but are wrong/unsafe for prod).
- **Stripe is conditional:** only if `MEMAR_STRIPE_SECRET_KEY` is set do the
  webhook secret and price IDs become required, and any `price_placeholder…`
  value is a FAIL (mirrors `billing.py`). No Stripe key = subsystem skipped.
- **SMTP is conditional:** validated only if any SMTP var is set.
- License **private** key is never globally required (issuer-only); the
  **public** key is an optional override of the embedded default.

---

## 3. Mint a license offline — `mint_license.py`

Issues a signed license key **by hand**, for the B2B paths that never touch Stripe:
pilots, air-gapped deployments, and white-label/OEM deals. Produces the exact same
agile-envelope format the webhook worker emits, so the key verifies offline on any
customer instance against the embedded public key — no internet, no phone-home.

Requires the issuer **private** key (same one the worker holds):

```bash
export MEMAR_LICENSE_PRIVATE_KEY=...    # base64 32-byte Ed25519 seed
# 30-day Workshop pilot for a prospect
../.venv/bin/python scripts/mint_license.py --tier workshop --days 30 --customer "Acme Machining"
# 12-month air-gap standard (500 machines) — the B2B default
../.venv/bin/python scripts/mint_license.py --tier airgap_standard --days 365 --customer "Defense Supplier LLC"
# Perpetual white-label key (no expiry, never phones home)
../.venv/bin/python scripts/mint_license.py --tier enterprise --perpetual --customer "Integrator Partner" --out partner.key
```

The bare key prints to **stdout** (pipe-friendly); a human summary prints to stderr.
Every mint is round-trip-verified before it's handed over — if the private key
doesn't match the embedded public key, it errors instead of issuing a dud.

| Tier input | Claim tier | Default devices |
|---|---|---|
| `maker` / `pro` / `farm` / `scale` | same | 15 / 40 / 150 / 500 |
| `workshop` / `business` / `enterprise` | same | 500 / 2000 / 10000 |
| `airgap_standard` / `airgap_enterprise` | `airgap` | 500 / 9999 |

> Air-gap aliases deliberately claim tier `airgap` (singular) — `license._tier_to_features`
> only recognises `airgap`, so `airgap_standard` as a claim tier would yield no features.
> Override the count with `--device-limit`.

---

## 4. Go-live env checklist

1. `cp .env.example .env` at the repo root and fill in real values.
2. Set `MEMAR_ENV=production`.
3. Generate `MEMAR_JWT_SECRET`:
   ```bash
   ../.venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
   ```
4. Set `MEMAR_ADMIN_USER` + `MEMAR_ADMIN_PASSWORD` (don't rely on the
   auto-generated `.admin-credentials` file).
5. Set `MEMAR_PUBLIC_URL` to the real public HTTPS URL and
   `MEMAR_OWNER_EMAIL`.
6. Point `MEMAR_DB_PATH` / `MEMAR_DATA_DIR` at persistent, writable storage.
7. **If selling licenses:** run `generate_license_keypair.py`; put the private
   key on the issuer instance only, the public key on verifiers.
8. **If billing via Stripe:** set `MEMAR_STRIPE_SECRET_KEY` (live),
   `MEMAR_STRIPE_WEBHOOK_SECRET`, and every real `MEMAR_STRIPE_PRICE_*` ID
   (no placeholders).
9. **If sending email:** set the SMTP block. The password env var is
   `MEMAR_SMTP_PASSWORD` (used by all email modules).
10. Run preflight and confirm exit `0`:
    ```bash
    set -a; . ../.env; set +a
    ../.venv/bin/python scripts/preflight.py
    ```
11. Make sure `.env` is **not** committed (it is already git-ignored).
