#!/usr/bin/env python3
"""Mint a signed MEMAR license key OFFLINE — for pilots, air-gap, and white-label.

The Stripe webhook worker mints keys automatically on a community-tier purchase.
But B2B never touches that path: pilots, air-gapped deployments, and white-label/OEM
deals are closed by hand and need a signed key issued directly. This is that tool.

It produces the SAME "agile envelope" format the worker emits and that
app.license._verify_license accepts:

    base64( JSON{ alg:"ed25519", kid, ver:2, claims:b64(JSON), sig:b64 } )

The signature is over the exact claims bytes that get embedded, so the key is
self-consistent and verifies offline against the embedded public key on any
customer instance — no internet, no Stripe, no phone-home.

Requires the issuer private key (the same one the worker holds):

    export MEMAR_LICENSE_PRIVATE_KEY=...        # base64, 32-byte Ed25519 seed

Examples:
    # 30-day Workshop pilot for a prospect
    python mint_license.py --tier workshop --days 30 --customer "Acme Machining"

    # 12-month air-gap standard license (500 machines), the B2B default
    python mint_license.py --tier airgap_standard --days 365 --customer "Defense Supplier LLC"

    # Perpetual white-label key (no expiry)
    python mint_license.py --tier enterprise --perpetual --customer "Integrator Partner"

The minted key is printed to stdout (paste into the customer's MEMAR_LICENSE_KEY
or the in-app activation box). Use --out to also write it to a file.
"""

import argparse
import base64
import json
import os
import sys
from datetime import date, timedelta

import nacl.signing

# Import the verifier so every mint is round-trip checked against the real
# verification path before we hand the key over.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir))
from app import license as license_mod  # noqa: E402

KID = license_mod.DEFAULT_KID  # "k1" — the embedded root of trust
VER = 2

# Friendly tier name -> (claim_tier, default_device_limit). Air-gap aliases map to
# the claim tier "airgap" because app.license._tier_to_features only recognises
# "airgap" (singular) — "airgap_standard" would yield an empty feature set.
TIER_LIMITS = {
    "maker": ("maker", 15),
    "pro": ("pro", 40),
    "farm": ("farm", 150),
    "scale": ("scale", 500),
    "workshop": ("workshop", 500),
    "business": ("business", 2000),
    "enterprise": ("enterprise", 10000),
    "airgap": ("airgap", 500),
    "airgap_standard": ("airgap", 500),
    "airgap_enterprise": ("airgap", 9999),  # "unlimited"
}


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def mint(priv_b64: str, *, claim_tier: str, device_limit: int,
         customer_id: str, expires_at: str | None) -> str:
    """Build a signed agile-envelope license key string."""
    signing_key = nacl.signing.SigningKey(base64.b64decode(priv_b64))
    claims = {
        "customer_id": customer_id,
        "device_limit": device_limit,
        "tier": claim_tier,
        "expires_at": expires_at,  # YYYY-MM-DD or null (perpetual)
        "issued_at": date.today().isoformat(),
    }
    claims_bytes = json.dumps(claims).encode("utf-8")
    sig = signing_key.sign(claims_bytes).signature  # 64-byte standard Ed25519
    envelope = {
        "alg": "ed25519",
        "kid": KID,
        "ver": VER,
        "claims": _b64(claims_bytes),
        "sig": _b64(sig),
    }
    return _b64(json.dumps(envelope).encode("utf-8"))


def _resolve_expiry(args) -> str | None:
    if args.perpetual:
        return None
    if args.expires:
        date.fromisoformat(args.expires)  # validate format, raises on bad input
        return args.expires
    return (date.today() + timedelta(days=args.days)).isoformat()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Mint a signed MEMAR license key offline (pilots / air-gap / white-label).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--tier", required=True, choices=sorted(TIER_LIMITS),
                   help="License tier. Air-gap aliases map to claim tier 'airgap'.")
    p.add_argument("--customer", required=True,
                   help="Customer identifier (org name or email) — recorded in the key.")
    p.add_argument("--device-limit", type=int, default=None,
                   help="Override the tier's default device limit.")
    exp = p.add_mutually_exclusive_group()
    exp.add_argument("--days", type=int, default=365,
                     help="Days until expiry (default 365). Use 30 for a pilot.")
    exp.add_argument("--expires", help="Explicit expiry date YYYY-MM-DD.")
    exp.add_argument("--perpetual", action="store_true",
                     help="No expiry (white-label / OEM). Never phones home.")
    p.add_argument("--out", help="Also write the key to this file.")
    args = p.parse_args()

    priv_b64 = os.getenv("MEMAR_LICENSE_PRIVATE_KEY")
    if not priv_b64:
        p.error("MEMAR_LICENSE_PRIVATE_KEY is not set — export the issuer private key first.")

    claim_tier, default_limit = TIER_LIMITS[args.tier]
    device_limit = args.device_limit if args.device_limit is not None else default_limit
    expires_at = _resolve_expiry(args)

    key = mint(priv_b64, claim_tier=claim_tier, device_limit=device_limit,
               customer_id=args.customer, expires_at=expires_at)

    # Round-trip: verify against the REAL verification path before handing it over.
    # This catches a wrong private key (sig won't match the embedded public key) and
    # any format drift. If the issuer private key differs from the public key the
    # instance embeds, set MEMAR_LICENSE_PUBLIC_KEY to match for this check.
    try:
        claims = license_mod._verify_license(key)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: minted key FAILED self-verification: {e}", file=sys.stderr)
        print("  → the private key likely does not match the embedded public key "
              "(MEMAR_LICENSE_PUBLIC_KEY / EMBEDDED_PUBLIC_KEY_B64).", file=sys.stderr)
        return 1
    if license_mod._tier_to_features(claims.get("tier", "")) == []:
        print(f"WARNING: tier {claims.get('tier')!r} maps to NO features — "
              "feature gates will 402. Use a recognised tier.", file=sys.stderr)

    if args.out:
        with open(args.out, "w") as f:
            f.write(key + "\n")

    # Human-readable summary to stderr; the bare key to stdout (pipe-friendly).
    print(
        f"Minted MEMAR license\n"
        f"  customer    : {args.customer}\n"
        f"  tier        : {claim_tier}  (input: {args.tier})\n"
        f"  device_limit: {device_limit}\n"
        f"  expires_at  : {expires_at or 'never (perpetual)'}\n"
        f"  verified    : OK (validates offline against the embedded public key)\n"
        + (f"  written to  : {args.out}\n" if args.out else ""),
        file=sys.stderr,
    )
    print(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
