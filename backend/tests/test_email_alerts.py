"""Proves the Maker 'Email alerts' claim is real.

send_alert routing + recipient handling, the email_alerts tier gate + debounce,
and that a real device state change (→ offline) actually triggers an email.
"""
import asyncio
import types

import pytest

import app.email_service as email_service
import app.license as licmod
import app.webhooks as webhooks
from app.license import LicenseState, _tier_to_features


def _set_tier(tier: str) -> None:
    licmod._state = LicenseState(tier=tier, device_limit=150, expires_at="2099-01-01",
                                 features=_tier_to_features(tier), customer_id="c", active=True)


def _fake_printer(pid, online=True, job_state=None):
    job = types.SimpleNamespace(state=job_state, filename=None) if job_state is not None else None
    return types.SimpleNamespace(id=pid, online=online, job=job)


@pytest.mark.asyncio
async def test_send_alert_no_recipients_returns_false(monkeypatch):
    monkeypatch.delenv("MEMAR_ALERT_EMAILS", raising=False)
    assert await email_service.send_alert("s", "b") is False


@pytest.mark.asyncio
async def test_send_alert_routes_to_recipients(monkeypatch):
    captured = {}

    async def fake_send(recipients, subject, text, html=None):
        captured["to"], captured["subject"] = recipients, subject
        return True

    monkeypatch.setattr(email_service, "_send", fake_send)
    # explicit recipient
    assert await email_service.send_alert("Subj", "Body", to="ops@shop.com") is True
    assert captured["to"] == ["ops@shop.com"]
    # env fallback
    monkeypatch.setenv("MEMAR_ALERT_EMAILS", "a@x.com, b@y.com")
    assert await email_service.send_alert("S2", "B2") is True
    assert captured["to"] == ["a@x.com", "b@y.com"]


@pytest.mark.asyncio
async def test_email_alert_gated_by_active_license_and_debounced(monkeypatch):
    calls = []

    async def fake_send_alert(subject, body, **kw):
        calls.append(subject)
        return True

    monkeypatch.setattr(email_service, "send_alert", fake_send_alert)
    webhooks._last_email_alert.clear()
    try:
        # email_alerts is on every tier now — the gate is an ACTIVE license.
        licmod._state = LicenseState(tier="scale", device_limit=500, expires_at="2099-01-01",
                                     features=_tier_to_features("scale"), customer_id="c", active=False)
        await webhooks._email_alert("p1", "printer.error", "error")
        assert calls == []

        _set_tier("maker")  # active license → email fires
        await webhooks._email_alert("p1", "printer.error", "error")
        assert len(calls) == 1

        # debounced within the window
        await webhooks._email_alert("p1", "printer.error", "error")
        assert len(calls) == 1
    finally:
        licmod._state = None
        webhooks._last_email_alert.clear()


@pytest.mark.asyncio
async def test_offline_transition_triggers_email(monkeypatch):
    calls = []

    async def fake_send_alert(subject, body, **kw):
        calls.append(kw.get("device_id"))
        return True

    monkeypatch.setattr(email_service, "send_alert", fake_send_alert)
    webhooks._last_email_alert.clear()
    webhooks._prev_states.clear()
    try:
        _set_tier("maker")
        webhooks._prev_states["p9"] = "idle"  # prior state
        offline = _fake_printer("p9", online=False, job_state=None)  # → cur == "offline"
        await webhooks.detect_state_changes([offline])
        # the alert is fire-and-forget — wait for it deterministically
        for _ in range(100):
            if "p9" in calls:
                break
            await asyncio.sleep(0.01)
        assert "p9" in calls
    finally:
        licmod._state = None
        webhooks._last_email_alert.clear()
        webhooks._prev_states.clear()
