"""MATRIX-SYNC-BACKOFF-01: the sync loop must retry with backoff instead of
dying permanently on the first unexpected exception out of sync_forever()."""
import asyncio as asyncio_module

import pytest

from app.messaging.adapters.matrix import MatrixAdapter


class _FakeClient:
    """sync_forever fails `fail_times` times, then returns cleanly."""

    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    async def sync_forever(self, timeout, full_state):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"transient failure #{self.calls}")
        return


@pytest.mark.asyncio
async def test_sync_loop_retries_with_backoff_instead_of_dying(monkeypatch):
    real_sleep = asyncio_module.sleep
    sleep_calls = []

    async def fast_sleep(delay):
        sleep_calls.append(delay)
        await real_sleep(0)  # yield control without a real wait

    monkeypatch.setattr(asyncio_module, "sleep", fast_sleep)

    adapter = MatrixAdapter(homeserver="https://h", user="@bot:h", password="p", room_id="!r:h")
    fake_client = _FakeClient(fail_times=2)

    async def fake_get_client():
        return fake_client

    monkeypatch.setattr(adapter, "_get_client", fake_get_client)

    await adapter.start()
    for _ in range(200):
        await real_sleep(0)
        if fake_client.calls >= 3:
            break

    # Before the fix, the loop called sync_forever exactly once and gave up
    # on the first RuntimeError — command handling would stay dead forever.
    assert fake_client.calls == 3, "sync loop must retry after a fatal exception, not die"
    assert sleep_calls == [2, 4], "backoff must be 2**attempt, capped, between retries"

    await adapter.stop()
