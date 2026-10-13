"""
CLI tool for generating MEMAR license keys.

This runs ONLY on the license issuer's machine, never deployed to customers.

Usage:
    python -m tools.keygen.keygen --generate-keypair --privkey ./priv.key --pubkey ./pub.key
    python -m tools.keygen.keygen --customer-id CUST001 --device-limit 25 --tier farm --days 365 --privkey ./priv.key
"""

import base64
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import nacl.signing


# Tier to features mapping
TIER_FEATURES = {
    "free": [],
    "maker": ["multi_user", "webhooks", "rbac"],
    "farm": ["multi_user", "webhooks", "rbac", "floor_plan", "oee"],
    "scale": [
        "multi_user",
        "webhooks",
        "rbac",
        "floor_plan",
        "oee",
        "sso",
        "audit_logs",
        "compliance_export",
    ],
    "enterprise": [
        "multi_user",
        "webhooks",
        "rbac",
        "floor_plan",
        "oee",
        "sso",
        "audit_logs",
        "compliance_export",
        "custom_branding",
    ],
}


def generate_keypair(priv_path: str, pub_path: str) -> None:
    """
    Generate an Ed25519 keypair and save as base64 to files.

    Args:
        priv_path: Path to save private key (base64)
        pub_path: Path to save public key (base64)
    """
    # Generate keypair
    signing_key = nacl.signing.SigningKey.generate()
    verify_key = signing_key.verify_key

    # Encode as base64
    priv_b64 = base64.b64encode(bytes(signing_key)).decode("utf-8")
    pub_b64 = base64.b64encode(bytes(verify_key)).decode("utf-8")

    # Write to files
    Path(priv_path).write_text(priv_b64)
    Path(pub_path).write_text(pub_b64)

    print(f"Keypair generated:")
    print(f"  Private key: {priv_path}")
    print(f"  Public key: {pub_path}")
    print(f"  Public key (base64): {pub_b64}")


def generate_license(
    customer_id: str,
    device_limit: int,
    tier: str,
    days: int,
    privkey_path: str,
) -> str:
    """
    Generate and sign a license key.

    Args:
        customer_id: Customer identifier
        device_limit: Max devices allowed
        tier: License tier (free, maker, farm, scale, enterprise)
        days: Validity in days (0 = never expires)
        privkey_path: Path to private key (base64)

    Returns:
        Base64-encoded signed license key
    """
    # Load private key
    priv_b64 = Path(privkey_path).read_text().strip()
    priv_bytes = base64.b64decode(priv_b64)
    signing_key = nacl.signing.SigningKey(priv_bytes)

    # Build payload
    expires_at = None
    if days > 0:
        expiry_date = datetime.now() + timedelta(days=days)
        expires_at = expiry_date.strftime("%Y-%m-%d")

    features = TIER_FEATURES.get(tier, [])
    payload = {
        "customer_id": customer_id,
        "device_limit": device_limit,
        "tier": tier,
        "expires_at": expires_at,
        "features": features,
    }

    # Sign payload
    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_bytes = payload_json.encode("utf-8")
    sig = signing_key.sign(payload_bytes).signature

    # Combine sig + payload and encode
    license_bytes = sig + payload_bytes
    license_b64 = base64.b64encode(license_bytes).decode("utf-8")

    return license_b64


def main():
    """CLI entry point."""
    args = sys.argv[1:]

    if "--generate-keypair" in args:
        idx = args.index("--generate-keypair")
        priv_idx = args.index("--privkey") if "--privkey" in args else None
        pub_idx = args.index("--pubkey") if "--pubkey" in args else None

        priv_path = args[priv_idx + 1] if priv_idx is not None else "memar_private.key"
        pub_path = args[pub_idx + 1] if pub_idx is not None else "memar_public.key"

        generate_keypair(priv_path, pub_path)
        return

    # License generation
    if "--customer-id" in args:
        idx = args.index("--customer-id")
        customer_id = args[idx + 1]

        device_limit_idx = args.index("--device-limit") if "--device-limit" in args else None
        device_limit = int(args[device_limit_idx + 1]) if device_limit_idx is not None else 3

        tier_idx = args.index("--tier") if "--tier" in args else None
        tier = args[tier_idx + 1] if tier_idx is not None else "free"

        days_idx = args.index("--days") if "--days" in args else None
        days = int(args[days_idx + 1]) if days_idx is not None else 365

        privkey_idx = args.index("--privkey") if "--privkey" in args else None
        privkey_path = args[privkey_idx + 1] if privkey_idx is not None else "memar_private.key"

        license_key = generate_license(customer_id, device_limit, tier, days, privkey_path)
        print(f"License key generated:")
        print(f"  Customer: {customer_id}")
        print(f"  Tier: {tier}")
        print(f"  Device limit: {device_limit}")
        print(f"  Expires: {(datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d') if days > 0 else 'Never'}")
        print(f"  Base64: {license_key}")
        return

    # Usage
    print("Usage:")
    print("  Generate keypair:")
    print("    python -m tools.keygen.keygen --generate-keypair --privkey ./priv.key --pubkey ./pub.key")
    print("  Generate license:")
    print("    python -m tools.keygen.keygen --customer-id CUST001 --device-limit 25 --tier farm --days 365 --privkey ./priv.key")


if __name__ == "__main__":
    main()
