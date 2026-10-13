"""EMAIL-TLS-CONFIG-01: SMTP TLS mode + unauthenticated-relay support.

email_service._send() previously hardcoded start_tls=True and unconditionally
called smtp.login(), which breaks implicit-TLS (port 465) deployments and
unauthenticated internal/LAN relays. These tests pin the new configurable
behavior (MEMAR_SMTP_TLS_MODE / MEMAR_SMTP_ALLOW_UNAUTHENTICATED) and confirm
the default stays byte-for-byte identical to the original hardcoded behavior.
"""
import pytest

import app.email_service as email_service


class _FakeSMTP:
    """Captures constructor kwargs + whether login()/sendmail() were called."""

    last_kwargs: dict | None = None
    login_called = False
    sendmail_called = False

    def __init__(self, **kwargs):
        _FakeSMTP.last_kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def login(self, user, password):
        _FakeSMTP.login_called = True

    async def sendmail(self, from_addr, to_addrs, msg):
        _FakeSMTP.sendmail_called = True


@pytest.fixture(autouse=True)
def _reset_fake_and_creds(monkeypatch):
    _FakeSMTP.last_kwargs = None
    _FakeSMTP.login_called = False
    _FakeSMTP.sendmail_called = False
    monkeypatch.setattr(email_service.aiosmtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(email_service, "SMTP_USER", "user@example.com")
    monkeypatch.setattr(email_service, "SMTP_PASSWORD", "hunter2")
    monkeypatch.setattr(email_service, "SMTP_ALLOW_UNAUTHENTICATED", False)
    monkeypatch.setattr(email_service, "SMTP_TLS_MODE", "starttls")
    yield


@pytest.mark.asyncio
async def test_default_mode_matches_original_hardcoded_start_tls():
    ok = await email_service._send(["a@b.com"], "Subj", "body")
    assert ok is True
    assert _FakeSMTP.last_kwargs.get("start_tls") is True
    assert "use_tls" not in _FakeSMTP.last_kwargs
    assert _FakeSMTP.login_called is True


@pytest.mark.asyncio
async def test_implicit_tls_mode_uses_use_tls_not_start_tls(monkeypatch):
    monkeypatch.setattr(email_service, "SMTP_TLS_MODE", "implicit")
    ok = await email_service._send(["a@b.com"], "Subj", "body")
    assert ok is True
    assert _FakeSMTP.last_kwargs.get("use_tls") is True
    assert "start_tls" not in _FakeSMTP.last_kwargs


@pytest.mark.asyncio
async def test_none_tls_mode_uses_neither_flag(monkeypatch):
    monkeypatch.setattr(email_service, "SMTP_TLS_MODE", "none")
    ok = await email_service._send(["a@b.com"], "Subj", "body")
    assert ok is True
    assert "start_tls" not in _FakeSMTP.last_kwargs
    assert "use_tls" not in _FakeSMTP.last_kwargs


@pytest.mark.asyncio
async def test_default_still_refuses_to_send_without_credentials(monkeypatch):
    """No regression: an unconfigured deployment must still skip cleanly,
    not attempt a real network connection."""
    monkeypatch.setattr(email_service, "SMTP_USER", "")
    monkeypatch.setattr(email_service, "SMTP_PASSWORD", "")
    ok = await email_service._send(["a@b.com"], "Subj", "body")
    assert ok is False
    assert _FakeSMTP.last_kwargs is None  # never attempted a connection


@pytest.mark.asyncio
async def test_allow_unauthenticated_sends_without_login(monkeypatch):
    monkeypatch.setattr(email_service, "SMTP_USER", "")
    monkeypatch.setattr(email_service, "SMTP_PASSWORD", "")
    monkeypatch.setattr(email_service, "SMTP_ALLOW_UNAUTHENTICATED", True)
    ok = await email_service._send(["a@b.com"], "Subj", "body")
    assert ok is True
    assert _FakeSMTP.login_called is False
    assert _FakeSMTP.sendmail_called is True


@pytest.mark.asyncio
async def test_all_six_public_senders_route_through_send(monkeypatch):
    """Confirms the dedup: every public sender ends up calling the same
    low-level _send(), not a duplicated inline SMTP block."""
    calls = []

    async def fake_send(recipients, subject, body_text, body_html=None):
        calls.append(subject)
        return True

    monkeypatch.setattr(email_service, "_send", fake_send)

    assert await email_service.send_license_email("a@b.com", "pro", "KEY") is True
    assert await email_service.send_payment_failed_email("a@b.com", 1000) is True
    assert await email_service.send_renewal_warning_email("a@b.com", "pro", 5, "2099-01-01") is True
    assert await email_service.send_password_reset_email("a@b.com", "https://x/reset?t=1") is True
    assert await email_service.send_welcome_email("a@b.com", "pro") is True
    assert await email_service.send_cancellation_email("a@b.com", "pro", "2099-01-01") is True

    assert len(calls) == 6


@pytest.mark.asyncio
async def test_send_license_email_escapes_html_in_tier_and_key(monkeypatch):
    """ADMIN-LICENSE-EMAIL-ESCAPE-01: send_license_email's HTML body must
    escape tier/license_key like every sibling sender already does — a raw
    license key or tier string containing HTML-significant characters must
    not be able to break out of the markup."""
    captured = {}

    async def fake_send(recipients, subject, body_text, body_html=None):
        captured["html"] = body_html
        return True

    monkeypatch.setattr(email_service, "_send", fake_send)

    await email_service.send_license_email("a@b.com", "<script>pro", "KEY</code><script>alert(1)</script>")

    assert "<script>" not in captured["html"]
    assert "&lt;script&gt;" in captured["html"]
