"""Offline license mint CLI — keys it produces must validate on the real path.

Uses a throwaway keypair (via MEMAR_LICENSE_PUBLIC_KEY override) so the test never
needs the production issuer private key.
"""

import base64
import importlib
import os

import nacl.signing
import pytest

import app.license as license_mod
from scripts import mint_license


@pytest.fixture()
def issuer_keypair(monkeypatch):
    """Generate a fresh Ed25519 keypair and point verification at its public key."""
    sk = nacl.signing.SigningKey.generate()
    priv_b64 = base64.b64encode(bytes(sk)).decode()
    pub_b64 = base64.b64encode(bytes(sk.verify_key)).decode()
    monkeypatch.setenv("MEMAR_LICENSE_PRIVATE_KEY", priv_b64)
    # _public_key_for() honours MEMAR_LICENSE_PUBLIC_KEY for the default kid.
    monkeypatch.setenv("MEMAR_LICENSE_PUBLIC_KEY", pub_b64)
    return priv_b64, pub_b64


def test_minted_key_verifies_and_carries_tier_and_limit(issuer_keypair):
    priv_b64, _ = issuer_keypair
    key = mint_license.mint(
        priv_b64, claim_tier="workshop", device_limit=500,
        customer_id="Acme Machining", expires_at="2027-01-01",
    )
    claims = license_mod._verify_license(key)
    assert claims["tier"] == "workshop"
    assert claims["device_limit"] == 500
    assert claims["customer_id"] == "Acme Machining"
    assert claims["expires_at"] == "2027-01-01"
    # A recognised tier must map to the full feature set (not empty).
    assert license_mod._tier_to_features(claims["tier"]) != []


def test_airgap_alias_maps_to_airgap_claim_tier(issuer_keypair):
    """airgap_standard/airgap_enterprise must claim tier 'airgap' so features resolve."""
    claim_tier, default_limit = mint_license.TIER_LIMITS["airgap_enterprise"]
    assert claim_tier == "airgap"
    assert default_limit == 9999
    priv_b64, _ = issuer_keypair
    key = mint_license.mint(
        priv_b64, claim_tier=claim_tier, device_limit=default_limit,
        customer_id="Defense Supplier LLC", expires_at="2027-06-29",
    )
    claims = license_mod._verify_license(key)
    assert claims["tier"] == "airgap"
    assert license_mod._tier_to_features("airgap") != []  # would be [] for "airgap_standard"


def test_perpetual_key_has_no_expiry(issuer_keypair):
    priv_b64, _ = issuer_keypair
    key = mint_license.mint(
        priv_b64, claim_tier="enterprise", device_limit=10000,
        customer_id="Integrator Partner", expires_at=None,
    )
    claims = license_mod._verify_license(key)
    assert claims["expires_at"] is None


def test_minted_key_loads_through_apply_license(issuer_keypair, monkeypatch):
    """End-to-end: the key activates the real license state with the right limit."""
    priv_b64, _ = issuer_keypair
    key = mint_license.mint(
        priv_b64, claim_tier="airgap", device_limit=500,
        customer_id="Pilot Co", expires_at="2027-12-31",
    )
    assert license_mod.apply_license(key) is True
    state = license_mod.get_license()
    assert state.active is True
    assert state.tier == "airgap"
    assert state.device_limit == 500


def test_wrong_private_key_fails_verification(issuer_keypair):
    """A key signed by a different private key must NOT verify against the public key."""
    other = nacl.signing.SigningKey.generate()
    wrong_priv = base64.b64encode(bytes(other)).decode()
    key = mint_license.mint(
        wrong_priv, claim_tier="workshop", device_limit=500,
        customer_id="x", expires_at="2027-01-01",
    )
    with pytest.raises(Exception):
        license_mod._verify_license(key)
