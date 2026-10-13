"""Regression tests: the Mattermost inbound slash-command endpoint previously
parsed a `token` field from the request body but never checked it against
anything — anyone who knew the URL could spoof a known admin's `user_id` and
get privileged commands executed as that user. It must now require
MEMAR_MATTERMOST_COMMAND_TOKEN to match, and fail closed when unconfigured."""

import pytest


@pytest.mark.asyncio
async def test_missing_token_rejected(client, monkeypatch):
    monkeypatch.setenv("MEMAR_MATTERMOST_COMMAND_TOKEN", "the-real-token")
    resp = await client.post(
        "/api/messaging/mattermost/command",
        data={"command": "/status", "text": "", "user_id": "u1", "channel_id": "c1"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_wrong_token_rejected(client, monkeypatch):
    monkeypatch.setenv("MEMAR_MATTERMOST_COMMAND_TOKEN", "the-real-token")
    resp = await client.post(
        "/api/messaging/mattermost/command",
        data={"command": "/status", "text": "", "user_id": "u1", "channel_id": "c1",
              "token": "an-attacker-guessed-token"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unconfigured_token_fails_closed(client, monkeypatch):
    """If the operator never set MEMAR_MATTERMOST_COMMAND_TOKEN, the endpoint
    must reject everything rather than accept an empty/blank token as valid."""
    monkeypatch.delenv("MEMAR_MATTERMOST_COMMAND_TOKEN", raising=False)
    resp = await client.post(
        "/api/messaging/mattermost/command",
        data={"command": "/status", "text": "", "user_id": "u1", "channel_id": "c1",
              "token": ""},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_correct_token_is_dispatched(client, monkeypatch):
    monkeypatch.setenv("MEMAR_MATTERMOST_COMMAND_TOKEN", "the-real-token")
    resp = await client.post(
        "/api/messaging/mattermost/command",
        data={"command": "/help", "text": "", "user_id": "u1", "channel_id": "c1",
              "token": "the-real-token"},
    )
    # Not 403 — request passed the token gate. (The hub may not be
    # initialized in this test's app context, in which case the route's own
    # "Messaging hub not initialized" branch returns 200 with that message —
    # either way, a valid token must never be rejected at the auth layer.)
    assert resp.status_code == 200
