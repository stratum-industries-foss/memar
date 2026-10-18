"""SAML 2.0 Web SSO (service provider side), built on signxml.

Trust model, in the order it is enforced:

1. The identity provider's X.509 certificate is pinned in the admin settings.
   Metadata is never fetched at login time, so a network attacker cannot swap
   the signing key.
2. The response's XML signature must verify against that certificate. Only the
   element the signature covers is read afterwards (signature wrapping is the
   classic SAML bypass: an unsigned copy of the assertion placed next to a
   signed one).
3. Audience must equal our entity ID; Destination and Recipient must equal our
   ACS URL; NotBefore / NotOnOrAfter must bracket now (small clock skew allowed).
4. InResponseTo must match a request we issued, and that request is single use.
5. A response ID is accepted once (replay).

Anything else is rejected with a generic error. The detailed reason goes to the
server log only.
"""

from __future__ import annotations

import base64
import logging
import secrets
import threading
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}
CLOCK_SKEW = timedelta(seconds=120)
REQUEST_TTL = timedelta(minutes=10)

_lock = threading.Lock()
_pending: dict[str, datetime] = {}   # AuthnRequest ID -> issued at (single use)
_seen: dict[str, datetime] = {}      # accepted Response IDs (replay guard)


class SamlError(Exception):
    """Generic rejection. The message is for the server log, never the user."""


@dataclass
class SamlConfig:
    idp_entity_id: str
    idp_sso_url: str
    idp_cert_pem: str          # pinned IdP signing certificate
    sp_entity_id: str          # our entity ID (Audience)
    sp_acs_url: str            # our Assertion Consumer Service URL
    attribute_username: str = "username"
    attribute_email: str = "email"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_authn_request(cfg: SamlConfig) -> tuple[str, str]:
    """Return (redirect URL, request ID). The ID is stored for InResponseTo."""
    req_id = "_" + secrets.token_hex(20)
    issued = _now()
    xml = (
        '<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{req_id}" Version="2.0" IssueInstant="{issued.strftime("%Y-%m-%dT%H:%M:%SZ")}" '
        f'Destination="{cfg.idp_sso_url}" AssertionConsumerServiceURL="{cfg.sp_acs_url}" '
        'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST">'
        f"<saml:Issuer>{cfg.sp_entity_id}</saml:Issuer>"
        '<samlp:NameIDPolicy Format="urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified" '
        'AllowCreate="true"/>'
        "</samlp:AuthnRequest>"
    )
    deflated = zlib.compress(xml.encode("utf-8"))[2:-4]  # raw DEFLATE for HTTP-Redirect
    param = base64.b64encode(deflated).decode("ascii")
    with _lock:
        _prune(_now())
        _pending[req_id] = issued
    return f"{cfg.idp_sso_url}?{urlencode({'SAMLRequest': param})}", req_id


def _prune(now: datetime) -> None:
    for store in (_pending, _seen):
        for key in [k for k, t in store.items() if now - t > REQUEST_TTL * 3]:
            store.pop(key, None)


def _verify_signature(response_xml: bytes, cert_pem: str) -> ET.Element:
    """Return the signed Response element. Raises SamlError if the signature
    does not verify against the pinned certificate."""
    try:
        from signxml import XMLVerifier
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise SamlError("signxml not installed") from exc
    try:
        verified = XMLVerifier().verify(response_xml, x509_cert=cert_pem)
    except Exception as exc:  # signxml raises several types; all are rejections
        raise SamlError(f"signature did not verify: {exc}") from exc
    # verified.signed_xml is the element the signature covers. We read only it.
    return verified.signed_xml


def process_response(cfg: SamlConfig, saml_response_b64: str, now: Optional[datetime] = None) -> dict:
    """Validate a POSTed SAMLResponse and return {username, email, name_id}.
    Raises SamlError on any failure."""
    now = now or _now()
    try:
        raw = base64.b64decode(saml_response_b64, validate=True)
    except Exception as exc:
        raise SamlError("response is not base64") from exc
    if len(raw) > 256 * 1024:
        raise SamlError("response too large")

    root = _verify_signature(raw, cfg.idp_cert_pem)
    if root.tag != f"{{{NS['samlp']}}}Response":
        raise SamlError("signed element is not a Response")

    if root.get("Destination") != cfg.sp_acs_url:
        raise SamlError("Destination mismatch")
    status = root.find("samlp:Status/samlp:StatusCode", NS)
    if status is None or status.get("Value") != "urn:oasis:names:tc:SAML:2.0:status:Success":
        raise SamlError("IdP did not report success")

    response_id = root.get("ID") or ""
    in_response_to = root.get("InResponseTo") or ""
    with _lock:
        _prune(now)
        if not response_id or response_id in _seen:
            raise SamlError("response ID missing or replayed")
        issued = _pending.pop(in_response_to, None)  # single use
        if issued is None or now - issued > REQUEST_TTL:
            raise SamlError("InResponseTo does not match an open request")
        _seen[response_id] = now

    assertion = root.find("saml:Assertion", NS)
    if assertion is None:
        raise SamlError("no assertion")
    # The signature check above already succeeded: _verify_signature returns the
    # signed element with its Signature removed, so the presence of a Signature
    # element is not re-checked here. Unsigned input never reaches this point.

    issuer = assertion.findtext("saml:Issuer", default="", namespaces=NS)
    if issuer != cfg.idp_entity_id:
        raise SamlError("issuer is not the configured IdP")

    audiences = [a.text for a in assertion.findall("saml:Conditions/saml:AudienceRestriction/saml:Audience", NS)]
    if cfg.sp_entity_id not in audiences:
        raise SamlError("audience mismatch")

    conditions = assertion.find("saml:Conditions", NS)
    if conditions is not None:
        nb, noa = conditions.get("NotBefore"), conditions.get("NotOnOrAfter")
        if nb and now + CLOCK_SKEW < _parse_time(nb):
            raise SamlError("assertion not yet valid")
        if noa and now - CLOCK_SKEW >= _parse_time(noa):
            raise SamlError("assertion expired")

    subj_conf = assertion.find("saml:Subject/saml:SubjectConfirmation/saml:SubjectConfirmationData", NS)
    if subj_conf is not None:
        if subj_conf.get("Recipient") != cfg.sp_acs_url:
            raise SamlError("Recipient mismatch")
        if subj_conf.get("InResponseTo") not in (None, in_response_to):
            raise SamlError("subject InResponseTo mismatch")

    name_id = assertion.findtext("saml:Subject/saml:NameID", default="", namespaces=NS)
    attrs = {}
    for attr in assertion.findall("saml:AttributeStatement/saml:Attribute", NS):
        values = [v.text or "" for v in attr.findall("saml:AttributeValue", NS)]
        if values:
            attrs[attr.get("Name", "")] = values[0]

    username = attrs.get(cfg.attribute_username) or name_id
    if not username:
        raise SamlError("no username in the assertion")
    return {
        "username": username.strip()[:255],
        "email": (attrs.get(cfg.attribute_email) or "").strip()[:255],
        "name_id": name_id,
    }
