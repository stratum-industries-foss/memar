"""SSO — proves the Farm/Scale 'SSO' claims are real.

OIDC: login redirect, tier-gating, code→token→user provisioning, state CSRF check.
LDAP: bind success/failure → token (skipped automatically until ldap3 is installed).
"""
import pytest
from datetime import datetime, timedelta, timezone
from jose import jwt
from jose import jwk as jose_jwk
from sqlalchemy import select

import app.license as licmod
import app.sso as sso
from app.license import LicenseState, _tier_to_features


def _set_tier(tier: str) -> None:
    licmod._state = LicenseState(tier=tier, device_limit=150, expires_at="2099-01-01",
                                 features=_tier_to_features(tier), customer_id="c", active=True)


def _oidc_env(monkeypatch):
    monkeypatch.setenv("MEMAR_OIDC_ISSUER", "https://idp.example.com")
    monkeypatch.setenv("MEMAR_OIDC_CLIENT_ID", "cid")
    monkeypatch.setenv("MEMAR_OIDC_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("MEMAR_OIDC_REDIRECT_URI", "https://memar.local/api/auth/sso/oidc/callback")

    async def fake_disc(issuer):
        return {"authorization_endpoint": "https://idp.example.com/authorize",
                "token_endpoint": "https://idp.example.com/token",
                "jwks_uri": "https://idp.example.com/.well-known/jwks.json"}

    monkeypatch.setattr(sso, "_oidc_discover", fake_disc)


@pytest.mark.asyncio
async def test_oidc_login_redirects_when_configured(client, monkeypatch):
    _oidc_env(monkeypatch)
    try:
        _set_tier("scale")
        r = await client.get("/api/auth/sso/oidc/login", follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers["location"]
        assert loc.startswith("https://idp.example.com/authorize?")
        assert "client_id=cid" in loc and "response_type=code" in loc and "state=" in loc
        assert "nonce=" in loc
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_oidc_login_gated_by_inactive_license(client, monkeypatch):
    _oidc_env(monkeypatch)
    try:
        # SSO is on every tier now — the remaining gate is an ACTIVE license.
        licmod._state = LicenseState(tier="scale", device_limit=500, expires_at="2099-01-01",
                                     features=_tier_to_features("scale"), customer_id="c", active=False)
        r = await client.get("/api/auth/sso/oidc/login", follow_redirects=False)
        assert r.status_code == 402
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_oidc_callback_provisions_user(client, monkeypatch):
    _oidc_env(monkeypatch)
    monkeypatch.setenv("MEMAR_PUBLIC_URL", "https://app.memar.local")

    # Generate a test RSA key pair to simulate a real IdP signing the id_token
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()
    )
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo
    )
    test_jwks = {"keys": [jose_jwk.construct(pub_pem, algorithm="RS256").to_dict()]}

    async def fake_jwks(jwks_uri):
        return test_jwks

    monkeypatch.setattr(sso, "_oidc_jwks", fake_jwks)

    # Generate state+nonce so we can embed the nonce in the id_token
    state, nonce = sso._make_state()
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    id_token = jwt.encode(
        {"email": "alice@corp.com", "email_verified": True, "sub": "abc", "nonce": nonce,
         "iss": "https://idp.example.com", "aud": "cid", "exp": exp},
        priv_pem, algorithm="RS256"
    )

    async def fake_token(disc, conf, code):
        return {"id_token": id_token}

    monkeypatch.setattr(sso, "_oidc_token", fake_token)
    try:
        _set_tier("scale")
        r = await client.get(f"/api/auth/sso/oidc/callback?code=xyz&state={state}", follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers["location"]
        assert loc.startswith("https://app.memar.local/#")
        assert "sso_access=" in loc and "sso_refresh=" in loc

        from app.db import AsyncSessionLocal
        from app.models_db import User
        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.username == "alice@corp.com"))).scalar_one_or_none()
        assert u is not None and u.role == "viewer"
    finally:
        licmod._state = None


def _oidc_keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                   serialization.NoEncryption())
    pub_pem = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return priv_pem, pub_pem


async def _oidc_callback_with_claims(client, monkeypatch, extra_claims: dict):
    """Drive a full OIDC callback with a real signed id_token carrying extra_claims."""
    _oidc_env(monkeypatch)
    monkeypatch.setenv("MEMAR_PUBLIC_URL", "https://app.memar.local")
    priv_pem, pub_pem = _oidc_keypair()
    test_jwks = {"keys": [jose_jwk.construct(pub_pem, algorithm="RS256").to_dict()]}

    async def fake_jwks(jwks_uri):
        return test_jwks
    monkeypatch.setattr(sso, "_oidc_jwks", fake_jwks)

    state, nonce = sso._make_state()
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)
    claims = {"sub": "abc", "nonce": nonce, "iss": "https://idp.example.com", "aud": "cid", "exp": exp}
    claims.update(extra_claims)
    id_token = jwt.encode(claims, priv_pem, algorithm="RS256")

    async def fake_token(disc, conf, code):
        return {"id_token": id_token}
    monkeypatch.setattr(sso, "_oidc_token", fake_token)

    return await client.get(f"/api/auth/sso/oidc/callback?code=xyz&state={state}", follow_redirects=False)


@pytest.mark.asyncio
async def test_oidc_unverified_email_falls_back_to_sub_based_username(client, monkeypatch):
    """Regression: an IdP asserting an email WITHOUT email_verified=true must not
    be trusted as that email's identity — a misconfigured/self-signup IdP could
    otherwise let an attacker claim any address. Must fall back to the
    sub-namespaced username instead of the raw (unverified) email."""
    try:
        _set_tier("scale")
        r = await _oidc_callback_with_claims(client, monkeypatch, {"email": "victim@corp.com"})
        assert r.status_code == 302

        from app.db import AsyncSessionLocal
        from app.models_db import User
        async with AsyncSessionLocal() as db:
            victim = (await db.execute(select(User).where(User.username == "victim@corp.com"))).scalar_one_or_none()
            sub_user = (await db.execute(select(User).where(User.username == "oidc:abc"))).scalar_one_or_none()
        assert victim is None
        assert sub_user is not None and sub_user.auth_provider == "oidc"
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_oidc_cannot_take_over_existing_local_account(client, monkeypatch):
    """Regression: an OIDC login whose (verified) email matches a pre-existing
    LOCAL-password account's username must be rejected, not silently logged in
    as that account — this was a full account-takeover path (admin included)."""
    from app.db import AsyncSessionLocal
    from app.models_db import User
    from app.auth import hash_password
    async with AsyncSessionLocal() as db:
        db.add(User(username="admin@corp.com", password_hash=hash_password("whatever-not-guessable"),
                    role="admin", is_active=True, auth_provider="local"))
        await db.commit()
    try:
        _set_tier("scale")
        r = await _oidc_callback_with_claims(
            client, monkeypatch, {"email": "admin@corp.com", "email_verified": True},
        )
        assert r.status_code == 409

        async with AsyncSessionLocal() as db:
            u = (await db.execute(select(User).where(User.username == "admin@corp.com"))).scalar_one()
        assert u.role == "admin" and u.auth_provider == "local"  # untouched
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_oidc_callback_rejects_bad_state(client, monkeypatch):
    _oidc_env(monkeypatch)
    try:
        _set_tier("scale")
        r = await client.get("/api/auth/sso/oidc/callback?code=xyz&state=forged", follow_redirects=False)
        assert r.status_code == 400
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_ldap_login_success_and_failure(client, monkeypatch):
    ldap3 = pytest.importorskip("ldap3")  # auto-skip until the dep is installed
    monkeypatch.setenv("MEMAR_LDAP_SERVER", "ldap://ldap.example.com")
    monkeypatch.setenv("MEMAR_LDAP_USER_DN_TEMPLATE", "uid={username},ou=people,dc=example,dc=com")

    class FakeConn:
        def __init__(self, *a, **k):
            if k.get("password") != "rightpass":
                raise Exception("invalidCredentials")

        def unbind(self):
            pass

    monkeypatch.setattr(ldap3, "Server", lambda *a, **k: object())
    monkeypatch.setattr(ldap3, "Connection", FakeConn)
    try:
        _set_tier("farm")
        ok = await client.post("/api/auth/sso/ldap/login", json={"username": "bob", "password": "rightpass"})
        assert ok.status_code == 200 and "access_token" in ok.json()
        bad = await client.post("/api/auth/sso/ldap/login", json={"username": "bob", "password": "wrong"})
        assert bad.status_code == 401
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_ldap_empty_or_whitespace_password_rejected(client, monkeypatch):
    """Regression: RFC 4513 'unauthenticated bind' — a SIMPLE bind with a
    zero-length password authenticates NOTHING, but some directories (older
    OpenLDAP, misconfigured AD) return success for it anyway. Must be rejected
    before ever constructing the ldap3 Connection, not left to the directory's
    own hardening."""
    ldap3 = pytest.importorskip("ldap3")
    monkeypatch.setenv("MEMAR_LDAP_SERVER", "ldap://ldap.example.com")
    monkeypatch.setenv("MEMAR_LDAP_USER_DN_TEMPLATE", "uid={username},ou=people,dc=example,dc=com")

    class AlwaysBindsConn:
        """Simulates a directory that accepts an unauthenticated (empty-password) bind."""
        def __init__(self, *a, **k):
            pass
        def unbind(self):
            pass

    monkeypatch.setattr(ldap3, "Server", lambda *a, **k: object())
    monkeypatch.setattr(ldap3, "Connection", AlwaysBindsConn)
    try:
        _set_tier("farm")
        empty = await client.post("/api/auth/sso/ldap/login", json={"username": "bob", "password": ""})
        assert empty.status_code in (401, 422)  # 422 = Pydantic min_length=1 catches it first
        whitespace = await client.post("/api/auth/sso/ldap/login", json={"username": "bob", "password": "   "})
        assert whitespace.status_code == 401  # passes min_length=1, caught by the explicit .strip() check
    finally:
        licmod._state = None


def test_ldap_dn_value_escaping():
    """Unit test for the RFC 4514 DN escaper — ldap3 does not escape `user=`
    values itself, so unescaped special characters could alter the RDN
    sequence sent in the bind request."""
    esc = sso._escape_ldap_dn_value
    assert esc("bob") == "bob"
    assert esc("bob,evil=1") == "bob\\,evil=1"
    assert esc('bob"quote') == 'bob\\"quote'
    assert esc("bob\\slash") == "bob\\\\slash"
    assert esc("#leading") == "\\#leading"
    assert esc(" leading-space") == "\\ leading-space"
    assert esc("trailing-space ") == "trailing-space\\ "


@pytest.mark.asyncio
async def test_ldap_cannot_take_over_existing_local_account(client, monkeypatch):
    """Same collision protection as OIDC: a successful LDAP bind for a username
    that matches a pre-existing LOCAL-password account must be rejected, not
    silently logged in as that account."""
    ldap3 = pytest.importorskip("ldap3")
    monkeypatch.setenv("MEMAR_LDAP_SERVER", "ldap://ldap.example.com")
    monkeypatch.setenv("MEMAR_LDAP_USER_DN_TEMPLATE", "uid={username},ou=people,dc=example,dc=com")

    class FakeConn:
        def __init__(self, *a, **k):
            pass
        def unbind(self):
            pass
    monkeypatch.setattr(ldap3, "Server", lambda *a, **k: object())
    monkeypatch.setattr(ldap3, "Connection", FakeConn)

    from app.db import AsyncSessionLocal
    from app.models_db import User
    from app.auth import hash_password
    async with AsyncSessionLocal() as db:
        # "admin" is taken by the client fixture's own bootstrap user — use a
        # distinct local account here so this test isolates the collision path.
        db.add(User(username="shopfloor-lead", password_hash=hash_password("whatever-not-guessable"),
                    role="admin", is_active=True, auth_provider="local"))
        await db.commit()
    try:
        _set_tier("farm")
        r = await client.post("/api/auth/sso/ldap/login",
                              json={"username": "shopfloor-lead", "password": "anything"})
        assert r.status_code == 409
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_sso_settings_requires_admin(client):
    """Both GET and PUT must be unreachable without an admin token."""
    r = await client.get("/api/admin/sso/settings")
    assert r.status_code in (401, 403)
    r = await client.put("/api/admin/sso/settings", json={"oidc_issuer": "https://evil.example.com"})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_sso_settings_empty_by_default(admin_client):
    r = await admin_client.get("/api/admin/sso/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["oidc_issuer"] == "" and body["oidc_client_secret_set"] is False
    assert body["env_defaults"] == {
        "oidc_issuer_set": False, "oidc_client_id_set": False, "oidc_client_secret_set": False,
        "ldap_server_set": False, "ldap_user_dn_template_set": False,
    }


@pytest.mark.asyncio
async def test_sso_settings_put_set_get_clear_roundtrip(admin_client):
    # Set
    r = await admin_client.put("/api/admin/sso/settings", json={
        "oidc_issuer": "https://idp.example.com",
        "oidc_client_id": "cid123",
        "oidc_client_secret": "supersecret",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["oidc_issuer"] == "https://idp.example.com"
    assert body["oidc_client_id"] == "cid123"
    assert body["oidc_client_secret_set"] is True
    assert "supersecret" not in r.text  # secret value itself never comes back

    # Omitted field (ldap_server) untouched by the update above
    r = await admin_client.get("/api/admin/sso/settings")
    assert r.json()["ldap_server"] == ""

    # Explicit "" clears the DB override
    r = await admin_client.put("/api/admin/sso/settings", json={"oidc_issuer": ""})
    body = r.json()
    assert body["oidc_issuer"] == ""
    assert body["oidc_client_id"] == "cid123"  # untouched by this second PUT


@pytest.mark.asyncio
async def test_sso_settings_db_value_overrides_env_var(client, admin_client, monkeypatch):
    """End-to-end proof of the precedence chain: a DB-configured value actually
    gets used by the live OIDC login flow, not just echoed back by GET."""
    monkeypatch.setenv("MEMAR_OIDC_ISSUER", "https://env-configured.example.com")
    monkeypatch.setenv("MEMAR_OIDC_CLIENT_ID", "env-client-id")

    async def fake_disc(issuer):
        return {"authorization_endpoint": f"{issuer}/authorize",
                "token_endpoint": f"{issuer}/token", "jwks_uri": f"{issuer}/jwks"}
    monkeypatch.setattr(sso, "_oidc_discover", fake_disc)

    await admin_client.put("/api/admin/sso/settings", json={
        "oidc_issuer": "https://db-configured.example.com",
        "oidc_client_id": "db-client-id",
        "oidc_client_secret": "db-secret",
        "oidc_redirect_uri": "https://memar.local/api/auth/sso/oidc/callback",
    })
    try:
        _set_tier("scale")
        r = await client.get("/api/auth/sso/oidc/login", follow_redirects=False)
        assert r.status_code == 302
        loc = r.headers["location"]
        assert loc.startswith("https://db-configured.example.com/authorize?")
        assert "client_id=db-client-id" in loc
    finally:
        licmod._state = None


@pytest.mark.asyncio
async def test_sso_config_reflects_license_and_env(client, monkeypatch):
    """The login screen reads this to decide which buttons to show."""
    licmod._state = None  # unlicensed / unconfigured
    assert (await client.get("/api/auth/sso/config")).json() == {"oidc": False, "ldap": False}

    _oidc_env(monkeypatch)
    monkeypatch.setenv("MEMAR_LDAP_SERVER", "ldap://ldap.example.com")
    monkeypatch.setenv("MEMAR_LDAP_USER_DN_TEMPLATE", "uid={username},dc=x")
    try:
        _set_tier("scale")  # licensed + configured → both on
        c = (await client.get("/api/auth/sso/config")).json()
        assert c["oidc"] is True and c["ldap"] is True
        # SSO is on every tier now — the gate is an ACTIVE license. An inactive
        # (expired/revoked) license turns the buttons off even with env still set.
        licmod._state = LicenseState(tier="scale", device_limit=500, expires_at="2099-01-01",
                                     features=_tier_to_features("scale"), customer_id="c", active=False)
        c = (await client.get("/api/auth/sso/config")).json()
        assert c["oidc"] is False and c["ldap"] is False
    finally:
        licmod._state = None
