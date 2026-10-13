"""WEBHOOK-RETRY-BACKOFF-01: a webhook receiver returning 4xx/5xx must back
off between retries the same way a network exception already did. Before
the fix, a non-2xx HTTP response fell straight to the next attempt with no
delay at all, hammering a failing receiver 3x back-to-back."""
import asyncio as asyncio_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import webhooks


def _resp(status_code):
    r = MagicMock()
    r.status_code = status_code
    return r


@pytest.mark.asyncio
async def test_http_failure_backs_off_between_attempts(client, monkeypatch):
    real_sleep = asyncio_module.sleep
    sleep_calls = []

    async def fast_sleep(delay):
        sleep_calls.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(webhooks.asyncio, "sleep", fast_sleep)

    fake_client = AsyncMock()
    fake_client.post.side_effect = [_resp(500), _resp(502), _resp(503)]

    hook = SimpleNamespace(id=1, url="https://example.com/hook", secret="s3cr3t")
    event = {"type": "printer.error", "printer_id": "p1", "data": {}}

    await webhooks._dispatch_with_retry(fake_client, hook, event)

    assert fake_client.post.call_count == 3
    # Backoff BEFORE attempts 2 and 3 only — none after the final attempt.
    assert sleep_calls == [1, 2]


@pytest.mark.asyncio
async def test_success_on_first_attempt_never_sleeps(client, monkeypatch):
    real_sleep = asyncio_module.sleep
    sleep_calls = []

    async def fast_sleep(delay):
        sleep_calls.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(webhooks.asyncio, "sleep", fast_sleep)

    fake_client = AsyncMock()
    fake_client.post.return_value = _resp(200)

    hook = SimpleNamespace(id=1, url="https://example.com/hook", secret="s3cr3t")
    event = {"type": "printer.error", "printer_id": "p1", "data": {}}

    await webhooks._dispatch_with_retry(fake_client, hook, event)

    assert fake_client.post.call_count == 1
    assert sleep_calls == []
