"""SAML service: accepts a correctly signed response, rejects each attack in the design.

Keys are generated per test run in memory and never written to disk.
"""

import base64
import datetime
import uuid

import pytest
from lxml import etree

from app import saml_service as S

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from signxml import SignatureMethod, XMLSigner
except ImportError:  # pragma: no cover
    pytest.skip("signxml/cryptography not installed", allow_module_level=True)

ACS = "https://memar.test/api/auth/saml/acs"
SP = "https://memar.test/api/auth/saml/metadata"
IDP = "https://idp.test/entity"
SSO = "https://idp.test/sso"
NS_P = "urn:oasis:names:tc:SAML:2.0:protocol"
NS_A = "urn:oasis:names:tc:SAML:2.0:assertion"


@pytest.fixture(scope="module")
def idp():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-idp")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=30))
            .sign(key, hashes.SHA256()))
    return key, cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.fixture
def cfg(idp):
    return S.SamlConfig(idp_entity_id=IDP, idp_sso_url=SSO, idp_cert_pem=idp[1],
                        sp_entity_id=SP, sp_acs_url=ACS)


def _ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _response(idp, *, in_response_to, now=None, audience=SP, destination=ACS,
              issuer=IDP, status="urn:oasis:names:tc:SAML:2.0:status:Success",
              not_on_or_after_delta=300, username="alice", sign=True, response_id=None):
    key, pem = idp
    now = now or datetime.datetime.now(datetime.timezone.utc)
    rid = response_id or "_" + uuid.uuid4().hex
    xml = f"""<samlp:Response xmlns:samlp="{NS_P}" xmlns:saml="{NS_A}" ID="{rid}" Version="2.0"
 IssueInstant="{_ts(now)}" Destination="{destination}" InResponseTo="{in_response_to}">
 <saml:Issuer>{issuer}</saml:Issuer>
 <samlp:Status><samlp:StatusCode Value="{status}"/></samlp:Status>
 <saml:Assertion ID="_a{uuid.uuid4().hex}" Version="2.0" IssueInstant="{_ts(now)}">
  <saml:Issuer>{issuer}</saml:Issuer>
  <saml:Subject>
   <saml:NameID>{username}</saml:NameID>
   <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
    <saml:SubjectConfirmationData Recipient="{ACS}" InResponseTo="{in_response_to}"
      NotOnOrAfter="{_ts(now + datetime.timedelta(seconds=not_on_or_after_delta))}"/>
   </saml:SubjectConfirmation>
  </saml:Subject>
  <saml:Conditions NotBefore="{_ts(now - datetime.timedelta(seconds=30))}"
    NotOnOrAfter="{_ts(now + datetime.timedelta(seconds=not_on_or_after_delta))}">
   <saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction>
  </saml:Conditions>
  <saml:AttributeStatement>
   <saml:Attribute Name="email"><saml:AttributeValue>alice@example.com</saml:AttributeValue></saml:Attribute>
  </saml:AttributeStatement>
 </saml:Assertion>
</samlp:Response>"""
    doc = etree.fromstring(xml.encode())
    if sign:
        doc = XMLSigner(signature_algorithm=SignatureMethod.ECDSA_SHA256 if hasattr(SignatureMethod, "ECDSA_SHA256") else None,
                        digest_algorithm="sha256").sign(doc, key=key, cert=pem)
    raw = etree.tostring(doc)
    return base64.b64encode(raw).decode()


def _open_request(cfg):
    _url, req_id = S.build_authn_request(cfg)
    return req_id


def test_signed_response_is_accepted(cfg, idp):
    rid = _open_request(cfg)
    identity = S.process_response(cfg, _response(idp, in_response_to=rid))
    assert identity["username"] == "alice"
    assert identity["email"] == "alice@example.com"


def test_unsigned_response_is_rejected(cfg, idp):
    rid = _open_request(cfg)
    with pytest.raises(S.SamlError):
        S.process_response(cfg, _response(idp, in_response_to=rid, sign=False))


def test_response_signed_by_another_key_is_rejected(cfg, idp):
    rid = _open_request(cfg)
    other = (ec.generate_private_key(ec.SECP256R1()), idp[1])  # signs with a key the cert does not match
    with pytest.raises(S.SamlError):
        S.process_response(cfg, _response(other, in_response_to=rid))


def test_tampered_signed_response_is_rejected(cfg, idp):
    rid = _open_request(cfg)
    b64 = _response(idp, in_response_to=rid)
    raw = base64.b64decode(b64).replace(b"alice@example.com", b"mallory@example.com")
    with pytest.raises(S.SamlError):
        S.process_response(cfg, base64.b64encode(raw).decode())


def test_wrong_audience_is_rejected(cfg, idp):
    rid = _open_request(cfg)
    with pytest.raises(S.SamlError, match="audience"):
        S.process_response(cfg, _response(idp, in_response_to=rid, audience="https://other.sp/"))


def test_wrong_destination_is_rejected(cfg, idp):
    rid = _open_request(cfg)
    with pytest.raises(S.SamlError, match="Destination"):
        S.process_response(cfg, _response(idp, in_response_to=rid, destination="https://evil/acs"))


def test_expired_assertion_is_rejected(cfg, idp):
    rid = _open_request(cfg)
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
    with pytest.raises(S.SamlError, match="expired|not yet"):
        S.process_response(cfg, _response(idp, in_response_to=rid, now=past, not_on_or_after_delta=60))


def test_replayed_response_is_rejected(cfg, idp):
    rid = _open_request(cfg)
    b64 = _response(idp, in_response_to=rid, response_id="_fixed-replay-id")
    S.process_response(cfg, b64)
    rid2 = _open_request(cfg)
    b64_again = _response(idp, in_response_to=rid2, response_id="_fixed-replay-id")
    with pytest.raises(S.SamlError, match="replayed"):
        S.process_response(cfg, b64_again)


def test_response_without_an_open_request_is_rejected(cfg, idp):
    with pytest.raises(S.SamlError, match="InResponseTo"):
        S.process_response(cfg, _response(idp, in_response_to="_never-issued"))


def test_request_is_single_use(cfg, idp):
    rid = _open_request(cfg)
    S.process_response(cfg, _response(idp, in_response_to=rid))
    with pytest.raises(S.SamlError):
        S.process_response(cfg, _response(idp, in_response_to=rid))


def test_failed_status_is_rejected(cfg, idp):
    rid = _open_request(cfg)
    with pytest.raises(S.SamlError, match="success"):
        S.process_response(cfg, _response(idp, in_response_to=rid,
                                          status="urn:oasis:names:tc:SAML:2.0:status:Requester"))


async def test_saml_login_without_configuration_is_503(client):
    from app import license as licmod
    from app.license import LicenseState, _tier_to_features
    saved = licmod._state
    licmod._state = LicenseState(tier="pro", device_limit=40, expires_at="2099-01-01",
                                 features=_tier_to_features("pro"), customer_id="cus_test", active=True)
    try:
        r = await client.get("/api/auth/saml/login", follow_redirects=False)
    finally:
        licmod._state = saved
    assert r.status_code == 503, r.text


async def test_public_sso_config_reports_saml_only_when_licensed_and_configured(client, admin_client):
    from app import license as licmod
    from app.license import LicenseState, _tier_to_features
    saved = licmod._state
    try:
        # configured but on the free tier: must not advertise SAML
        licmod._state = LicenseState(tier="free", device_limit=5, expires_at=None,
                                     features=_tier_to_features("free"), customer_id=None, active=True)
        r = await client.get("/api/auth/sso/config")
        assert r.json()["saml"] is False

        # licensed but no IdP configured: still not advertised
        licmod._state = LicenseState(tier="pro", device_limit=40, expires_at="2099-01-01",
                                     features=_tier_to_features("pro"), customer_id="cus_test", active=True)
        r = await client.get("/api/auth/sso/config")
        assert r.json()["saml"] is False

        # licensed and configured: advertised
        put = await admin_client.put("/api/admin/sso/settings", json={
            "saml_idp_entity_id": IDP, "saml_idp_sso_url": SSO, "saml_idp_cert_pem": "x"})
        assert put.status_code == 200, put.text
        r = await client.get("/api/auth/sso/config")
        assert r.json()["saml"] is True
        got = (await admin_client.get("/api/admin/sso/settings")).json()
        assert got["saml_configured"] is True and got["saml_idp_sso_url"] == SSO
    finally:
        licmod._state = saved
        await admin_client.put("/api/admin/sso/settings", json={
            "saml_idp_entity_id": "", "saml_idp_sso_url": "", "saml_idp_cert_pem": "", "saml_sp_entity_id": ""})


async def test_saml_cannot_take_over_a_local_account(client, admin_client, idp, cfg):
    """A SAML assertion naming an existing local (password) account must be refused,
    never signed in. This is the account-takeover check the commit message describes."""
    from app import license as licmod
    from app.license import LicenseState, _tier_to_features
    from app.models_db import User
    from app.db import AsyncSessionLocal
    from sqlalchemy import select

    saved = licmod._state
    licmod._state = LicenseState(tier="pro", device_limit=40, expires_at="2099-01-01",
                                 features=_tier_to_features("pro"), customer_id="cus_test", active=True)
    try:
        # the instance's local admin account (created by the setup flow in the test fixtures)
        async with AsyncSessionLocal() as db:
            local = (await db.execute(select(User).where(User.role == "admin"))).scalars().first()
        assert local is not None and local.auth_provider != "saml", "fixture must have a local admin"
        target = local.username

        rid = _open_request(cfg)
        b64 = _response(idp, in_response_to=rid, username=target)
        from app.sso import _provision_and_issue
        from fastapi import HTTPException
        async with AsyncSessionLocal() as db:
            raised = None
            try:
                await _provision_and_issue(db, username=target, provider="saml")
            except HTTPException as exc:
                raised = exc
        assert raised is not None and raised.status_code == 409, "SAML must not match a local account"

        # the owner's local login still works and is unchanged
        async with AsyncSessionLocal() as db:
            after = (await db.execute(select(User).where(User.username == target))).scalar_one()
        assert after.auth_provider == local.auth_provider, "local account must not be re-bound to SAML"
    finally:
        licmod._state = saved


async def test_acs_hands_tokens_to_the_frontend_under_the_names_it_reads(client, idp, cfg):
    """Regression: the frontend reads sso_access / sso_refresh from the URL fragment.
    The SAML callback once sent access_token, so the browser discarded the session
    and the user stayed on the login form. Assert the redirect uses the names the
    frontend actually reads (frontend/src/App.tsx: ssoFrag.get('sso_access'))."""
    from app import license as licmod
    from app.license import LicenseState, _tier_to_features
    from app.models_db import SSOSettings
    from app.db import AsyncSessionLocal
    from sqlalchemy import select

    import os
    saved = licmod._state
    saved_public = os.environ.get("MEMAR_PUBLIC_URL")
    # The route builds its ACS from MEMAR_PUBLIC_URL; the signed response must name that same ACS.
    os.environ["MEMAR_PUBLIC_URL"] = "https://memar.test"
    licmod._state = LicenseState(tier="pro", device_limit=40, expires_at="2099-01-01",
                                 features=_tier_to_features("pro"), customer_id="cus_test", active=True)
    try:
        async with AsyncSessionLocal() as db:
            s = (await db.execute(select(SSOSettings).where(SSOSettings.id == 1))).scalar_one_or_none()
            if s is None:
                s = SSOSettings(id=1)
                db.add(s)
            s.saml_idp_entity_id = cfg.idp_entity_id
            s.saml_idp_sso_url = cfg.idp_sso_url
            s.saml_idp_cert_pem = cfg.idp_cert_pem
            await db.commit()
        rid = _open_request(cfg)
        from urllib.parse import quote
        b64 = quote(_response(idp, in_response_to=rid, username="fragment.user", destination="https://memar.test/api/auth/saml/acs"), safe="")
        r = await client.post("/api/auth/saml/acs", content=f"SAMLResponse={b64}",
                              headers={"Content-Type": "application/x-www-form-urlencoded"},
                              follow_redirects=False)
        assert r.status_code == 302, r.text
        loc = r.headers["location"]
        fragment = loc.split("#", 1)[1] if "#" in loc else ""
        from urllib.parse import parse_qs
        names = set(parse_qs(fragment).keys())
        assert {"sso_access", "sso_refresh"} <= names, f"frontend reads sso_access/sso_refresh, got {names}"
        assert "access_token" not in names
    finally:
        licmod._state = saved
        if saved_public is None:
            os.environ.pop("MEMAR_PUBLIC_URL", None)
        else:
            os.environ["MEMAR_PUBLIC_URL"] = saved_public
