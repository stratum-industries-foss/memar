"""Tests for the MEMAR Unified Messaging Hub."""

from __future__ import annotations

import asyncio
import os
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure unconfigured env before imports
for _k in [
    "MEMAR_TELEGRAM_BOT_TOKEN",
    "MEMAR_NTFY_URL",
    "MEMAR_NOTIFY_WEBHOOK_URL",
    "MEMAR_SLACK_WEBHOOK_URL",
    "MEMAR_SLACK_BOT_TOKEN",
    "MEMAR_DISCORD_WEBHOOK_URL",
    "MEMAR_DISCORD_BOT_TOKEN",
    "MEMAR_MATTERMOST_URL",
    "MEMAR_MATRIX_HOMESERVER",
]:
    os.environ.pop(_k, None)

from app.messaging.base import AlertEvent
from app.messaging.adapters.ntfy import NtfyAdapter
from app.messaging.adapters.webhook import GenericWebhookAdapter
from app.messaging.adapters.telegram import TelegramAdapter
from app.messaging.adapters.slack import SlackAdapter
from app.messaging.adapters.discord import DiscordAdapter
from app.messaging.adapters.mattermost import MattermostAdapter
from app.messaging.adapters.matrix import MatrixAdapter
from app.messaging import MessagingHub


# ---------------------------------------------------------------------------
# from_env returns None when unconfigured
# ---------------------------------------------------------------------------


def test_ntfy_from_env_returns_none_when_url_absent():
    os.environ.pop("MEMAR_NTFY_URL", None)
    assert NtfyAdapter.from_env() is None


def test_webhook_from_env_returns_none_when_url_absent():
    for k in ["MEMAR_NOTIFY_WEBHOOK_URL", "MEMAR_COOLANT_WEBHOOK_URL", "WEBHOOK_URL"]:
        os.environ.pop(k, None)
    assert GenericWebhookAdapter.from_env() is None


def test_telegram_from_env_returns_none_when_token_absent():
    os.environ.pop("MEMAR_TELEGRAM_BOT_TOKEN", None)
    assert TelegramAdapter.from_env() is None


def test_slack_from_env_returns_none_when_unconfigured():
    for k in ["MEMAR_SLACK_WEBHOOK_URL", "MEMAR_SLACK_BOT_TOKEN"]:
        os.environ.pop(k, None)
    assert SlackAdapter.from_env() is None


def test_discord_from_env_returns_none_when_unconfigured():
    for k in ["MEMAR_DISCORD_WEBHOOK_URL", "MEMAR_DISCORD_BOT_TOKEN"]:
        os.environ.pop(k, None)
    assert DiscordAdapter.from_env() is None


def test_mattermost_from_env_returns_none_when_url_absent():
    os.environ.pop("MEMAR_MATTERMOST_URL", None)
    assert MattermostAdapter.from_env() is None


def test_matrix_from_env_returns_none_when_homeserver_absent():
    os.environ.pop("MEMAR_MATRIX_HOMESERVER", None)
    assert MatrixAdapter.from_env() is None


# ---------------------------------------------------------------------------
# from_env returns instance when configured
# ---------------------------------------------------------------------------


def test_ntfy_from_env_returns_instance():
    os.environ["MEMAR_NTFY_URL"] = "https://ntfy.sh/test-topic"
    try:
        inst = NtfyAdapter.from_env()
        assert inst is not None
        assert inst.name == "ntfy"
        assert inst._url == "https://ntfy.sh/test-topic"
    finally:
        del os.environ["MEMAR_NTFY_URL"]


def test_webhook_from_env_returns_instance():
    os.environ["MEMAR_NOTIFY_WEBHOOK_URL"] = "https://hooks.example.com/memar"
    try:
        inst = GenericWebhookAdapter.from_env()
        assert inst is not None
        assert inst.name == "webhook"
    finally:
        del os.environ["MEMAR_NOTIFY_WEBHOOK_URL"]


def test_webhook_legacy_coolant_url_still_works():
    os.environ.pop("MEMAR_NOTIFY_WEBHOOK_URL", None)
    os.environ["MEMAR_COOLANT_WEBHOOK_URL"] = "https://legacy.example.com/coolant"
    try:
        inst = GenericWebhookAdapter.from_env()
        assert inst is not None
        assert inst._url == "https://legacy.example.com/coolant"
    finally:
        del os.environ["MEMAR_COOLANT_WEBHOOK_URL"]


def test_slack_from_env_webhook_only():
    os.environ["MEMAR_SLACK_WEBHOOK_URL"] = "https://hooks.slack.com/xxx"
    try:
        inst = SlackAdapter.from_env()
        assert inst is not None
        assert inst.name == "slack"
        assert not inst.supports_commands  # no bot token → push-only
    finally:
        del os.environ["MEMAR_SLACK_WEBHOOK_URL"]


# ---------------------------------------------------------------------------
# Hub broadcasts to all adapters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hub_broadcasts_to_all():
    """Hub calls send() on each configured adapter."""
    mock_a = AsyncMock()
    mock_a.name = "adapter_a"
    mock_a.supports_commands = False
    mock_a.send = AsyncMock(return_value=True)

    mock_b = AsyncMock()
    mock_b.name = "adapter_b"
    mock_b.supports_commands = False
    mock_b.send = AsyncMock(return_value=True)

    hub = MessagingHub(adapters=[mock_a, mock_b])
    event = AlertEvent(
        type="printer.error",
        title="Error",
        body="Something broke",
        severity="error",
        data={},
    )
    await hub.broadcast(event)

    mock_a.send.assert_awaited_once_with(event)
    mock_b.send.assert_awaited_once_with(event)


@pytest.mark.asyncio
async def test_hub_broadcast_does_not_raise_on_adapter_failure():
    """A failing adapter should not abort the broadcast."""
    mock_ok = AsyncMock()
    mock_ok.name = "ok"
    mock_ok.supports_commands = False
    mock_ok.send = AsyncMock(return_value=True)

    mock_fail = AsyncMock()
    mock_fail.name = "fail"
    mock_fail.supports_commands = False
    mock_fail.send = AsyncMock(side_effect=RuntimeError("adapter exploded"))

    hub = MessagingHub(adapters=[mock_ok, mock_fail])
    event = AlertEvent(type="test", title="t", body="b", severity="info", data={})
    # Must not raise
    await hub.broadcast(event)

    mock_ok.send.assert_awaited_once()
    assert hub._last_delivery["fail"]["ok"] is False
    assert "adapter exploded" in hub._last_delivery["fail"]["error"]


@pytest.mark.asyncio
async def test_hub_empty_adapters_broadcast_noop():
    hub = MessagingHub(adapters=[])
    event = AlertEvent(type="test", title="t", body="b", severity="info", data={})
    # Must not raise, must complete immediately
    await hub.broadcast(event)


def test_hub_adapter_status_includes_all():
    mock_a = MagicMock()
    mock_a.name = "telegram"
    mock_a.supports_commands = True

    hub = MessagingHub(adapters=[mock_a])
    status = hub.adapter_status()
    assert len(status) == 1
    assert status[0]["name"] == "telegram"
    assert status[0]["bidirectional"] is True
    assert status[0]["ok"] is None  # no delivery yet


# ---------------------------------------------------------------------------
# Hub from_env returns hub with 0 adapters when none configured
# ---------------------------------------------------------------------------


def test_hub_from_env_no_adapters_when_unconfigured():
    hub = MessagingHub.from_env()
    assert isinstance(hub, MessagingHub)
    assert hub._adapters == []


# ---------------------------------------------------------------------------
# ntfy adapter send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ntfy_send_success():
    adapter = NtfyAdapter(url="https://ntfy.sh/test", token="tok")
    event = AlertEvent(type="printer.error", title="Error", body="bad", severity="error", data={})

    with patch("httpx.AsyncClient") as mock_cls:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.status_code = 200
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.post = AsyncMock(return_value=mock_resp)
        mock_cls.return_value = mock_ctx

        result = await adapter.send(event)

    assert result is True
    assert adapter._last_error is None


# ---------------------------------------------------------------------------
# webhook adapter — event filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_event_filter_skips_non_matching():
    adapter = GenericWebhookAdapter(
        url="https://hooks.example.com/",
        event_filter={"printer.error"},
    )
    event = AlertEvent(type="printer.complete", title="Done", body="ok", severity="info", data={})
    # Should return True (filtered = not an error) without HTTP call
    result = await adapter.send(event)
    assert result is True


# ---------------------------------------------------------------------------
# Webhook legacy HMAC sign
# ---------------------------------------------------------------------------


def test_webhook_sign_output():
    from app.messaging.adapters.webhook import _sign
    sig = _sign("secret", b"payload")
    assert sig.startswith("sha256=")
    assert len(sig) == 71  # "sha256=" + 64 hex chars


# ---------------------------------------------------------------------------
# Command router — role gate
# ---------------------------------------------------------------------------


from app.messaging.commands import _role_ok


def test_role_ok_viewer_can_status():
    assert _role_ok("viewer", "viewer") is True


def test_role_ok_viewer_cannot_ack():
    assert _role_ok("viewer", "operator") is False


def test_role_ok_operator_can_ack():
    assert _role_ok("operator", "operator") is True


def test_role_ok_admin_can_all():
    assert _role_ok("admin", "admin") is True
    assert _role_ok("admin", "operator") is True
    assert _role_ok("admin", "viewer") is True


# ---------------------------------------------------------------------------
# Matrix adapter send — RoomSendError handling (BUG-HIGH-MATRIX-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matrix_send_reports_false_when_room_send_rejected():
    """BUG-HIGH-MATRIX-01: room_send returning a non-RoomSendResponse (nio's
    RoomSendError, e.g. bot never invited) must make send() return False."""
    from app.messaging.adapters.matrix import MatrixAdapter
    from app.messaging.base import AlertEvent

    adapter = MatrixAdapter(homeserver="https://hs", user="@bot:hs",
                            password="pw", room_id="!room:hs")

    class _RejectingClient:
        async def room_send(self, **kwargs):
            return object()  # stand-in for nio RoomSendError (NOT an exception)
    adapter._client = _RejectingClient()

    event = AlertEvent(type="cnc.coolant_low", title="Coolant low", body="12 psi",
                       severity="critical", data={})
    ok = await adapter.send(event)
    assert ok is False
    assert adapter._last_ok is None
    assert adapter._last_error is not None


@pytest.mark.asyncio
async def test_matrix_send_reports_true_on_real_response():
    """A genuine RoomSendResponse must still count as delivered (no over-rejection)."""
    from nio import RoomSendResponse
    from app.messaging.adapters.matrix import MatrixAdapter
    from app.messaging.base import AlertEvent

    adapter = MatrixAdapter(homeserver="https://hs", user="@bot:hs",
                            password="pw", room_id="!room:hs")

    class _OkClient:
        async def room_send(self, **kwargs):
            return RoomSendResponse("$evt:hs", "!room:hs")
    adapter._client = _OkClient()

    event = AlertEvent(type="cnc.coolant_low", title="ok", body="b", severity="info", data={})
    ok = await adapter.send(event)
    assert ok is True
    assert adapter._last_ok is not None


# ---------------------------------------------------------------------------
# Matrix adapter start — pre-start message replay (BUG-HIGH-MATRIX-02)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_matrix_ignores_pre_start_messages():
    """BUG-HIGH-MATRIX-02: on restart, historical /commands the initial sync replays
    (server_timestamp older than process start) must be ignored, not re-executed."""
    import time
    import types
    from app.messaging.adapters.matrix import MatrixAdapter

    adapter = MatrixAdapter(homeserver="https://hs", user="@bot:hs",
                            password="pw", room_id="!room:hs")

    captured = {}

    class _FakeClient:
        def add_event_callback(self, cb, ev_type):
            captured["cb"] = cb
        async def sync_forever(self, *a, **k):
            return
        async def room_send(self, **k):
            return None
    adapter._client = _FakeClient()

    dispatched = []

    class _Router:
        async def dispatch(self, cmd, args, sender, platform):
            dispatched.append(cmd)
            return "ok"
    adapter._command_router = _Router()

    await adapter.start()
    cb = captured["cb"]

    now_ms = time.time() * 1000

    def _ev(ts_ms, body):
        return types.SimpleNamespace(sender="@user:hs", body=body, server_timestamp=ts_ms)
    room = types.SimpleNamespace(room_id="!room:hs")

    await cb(room, _ev(now_ms - 3_600_000, "/ack all"))  # 1h before start → ignore
    await cb(room, _ev(now_ms + 1_000, "/ack all"))       # after start → run
    await adapter.stop()

    assert dispatched == ["ack"], f"only the post-start command should run, got {dispatched}"
