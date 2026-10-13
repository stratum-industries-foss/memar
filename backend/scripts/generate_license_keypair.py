#!/usr/bin/env python3
"""
Generate an Ed25519 keypair for MEMAR license signing/verification.

The keypair is used by:
  - stripe_webhook.py  -> signs license keys with MEMAR_LICENSE_PRIVATE_KEY
  - license.py         -> verifies license keys with MEMAR_LICENSE_PUBLIC_KEY
                          (or the EMBEDDED_PUBLIC_KEY_B64 constant if unset)

Wire format (must match the consuming code exactly):
  - private key:  base64.b64encode(bytes(signing_key))   -> 32-byte Ed25519 seed
  - public key:   base64.b64encode(bytes(verify_key))    -> 32-byte Ed25519 public key

A license KEY (not the keypair) is then:  base64( 64-byte-signature + JSON-payload )
which stripe_webhook._generate_license_key() produces and license.load_license_from_env()
consumes.

Run (from backend/):
    ../.venv/bin/python scripts/generate_license_keypair.py

This is self-contained: it imports only PyNaCl (already a MEMAR dependency) and stdlib.
It does NOT import the MEMAR app, so it is safe to run in any environment.
"""

import base64
import sys

try:
    import nacl.signing
except ImportError:
    sys.stderr.write(
        "ERROR: PyNaCl is not installed in this interpreter.\n"
        "Run with the MEMAR venv, e.g. from backend/:\n"
        "    ../.venv/bin/python scripts/generate_license_keypair.py\n"
    )
    sys.exit(2)


def generate() -> tuple[str, str]:
    """Generate a fresh Ed25519 keypair, return (private_b64, public_b64)."""
    signing_key = nacl.signing.SigningKey.generate()
    verify_key = signing_key.verify_key

    # Format must match license.py / stripe_webhook.py exactly:
    #   private: base64 of the 32-byte signing-key seed
    #   public:  base64 of the 32-byte verify key
    private_b64 = base64.b64encode(bytes(signing_key)).decode("ascii")
    public_b64 = base64.b64encode(bytes(verify_key)).decode("ascii")
    return private_b64, public_b64


def _self_check(private_b64: str, public_b64: str) -> None:
    """Sign + verify a probe payload to prove the printed keys actually work."""
    sk = nacl.signing.SigningKey(base64.b64decode(private_b64))
    vk = nacl.signing.VerifyKey(base64.b64decode(public_b64))
    probe = b"memar-license-keypair-self-check"
    signed = sk.sign(probe)
    # Raises nacl.exceptions.BadSignatureError if the keys don't match.
    assert vk.verify(signed.message, signed.signature) == probe


def main() -> int:
    private_b64, public_b64 = generate()
    _self_check(private_b64, public_b64)

    bar = "=" * 72
    print(bar)
    print("  MEMAR Ed25519 License Keypair")
    print(bar)
    print()
    print("MEMAR_LICENSE_PRIVATE_KEY (SECRET — issuer instance ONLY):")
    print(f"  {private_b64}")
    print()
    print("MEMAR_LICENSE_PUBLIC_KEY (safe to distribute / embed):")
    print(f"  {public_b64}")
    print()
    print("-" * 72)
    print("WHERE EACH KEY GOES")
    print("-" * 72)
    print(
        "  PRIVATE KEY:\n"
        "    * Set MEMAR_LICENSE_PRIVATE_KEY ONLY on the single instance that\n"
        "      receives Stripe webhooks and issues licenses (the license issuer).\n"
        "    * NEVER put it on customer/self-hosted deployments. NEVER commit it.\n"
        "    * If it leaks, anyone can forge valid licenses — rotate immediately\n"
        "      (regenerate, redeploy the new public key everywhere, reissue keys).\n"
    )
    print(
        "  PUBLIC KEY:\n"
        "    * Set MEMAR_LICENSE_PUBLIC_KEY on every instance that must VERIFY\n"
        "      licenses, OR bake it into license.py's EMBEDDED_PUBLIC_KEY_B64.\n"
        "    * Safe to distribute publicly — it can only verify, not sign.\n"
    )
    print("-" * 72)
    print("NEXT STEPS")
    print("-" * 72)
    print(
        "  1. Add the PRIVATE key to the issuer instance's .env (and nowhere else).\n"
        "  2. Either set the PUBLIC key in each verifier's .env, or replace\n"
        "     EMBEDDED_PUBLIC_KEY_B64 in backend/app/license.py with it.\n"
        "  3. Run scripts/preflight.py to confirm both decode correctly.\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
