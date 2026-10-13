"""HIGH-FLEET-04: _clear_client_cache must close each cached adapter's HTTP pool and cancel its
background task, not just drop references (which leaked a pool + task on every config reload)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.fleet as fleet


@pytest.mark.asyncio
async def test_clear_client_cache_closes_adapters():
    adapter = MagicMock()
    adapter._client = MagicMock()
    adapter._client.aclose = AsyncMock()
    adapter.disconnect = AsyncMock()

    fleet._client_cache.clear()
    fleet._client_cache["p:moonraker:http://p::"] = adapter

    task = fleet._clear_client_cache()
    assert fleet._client_cache == {}, "cache must be emptied synchronously"
    if task is not None:                       # None only on the unfixed code path
        await task                             # let the scheduled close run to completion

    adapter._client.aclose.assert_awaited_once()   # HTTP pool closed
    adapter.disconnect.assert_awaited_once()       # background task cancelled


@pytest.mark.asyncio
async def test_clear_client_cache_empty_is_noop():
    fleet._client_cache.clear()
    task = fleet._clear_client_cache()
    assert task is None
    assert fleet._client_cache == {}
