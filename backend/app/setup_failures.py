"""Failed setup-code attempts, counted per client and globally.

Only WRONG codes are counted. A correct claim, an ordinary request or a claim
that needs no code never adds to the count, so the owner is not locked out by
requests that are not failures. Two windows:

- per client: a single address that keeps guessing is blocked for a while;
- global: a cap on total failures across all clients, so spreading guesses over
  many addresses does not defeat the per-client limit. It is high enough that a
  real owner who mistypes a few times is never blocked by it.

State is in-memory and per process. The instance runs one uvicorn worker (see
the Dockerfile and systemd unit); with more workers the limits are per worker.
"""

from __future__ import annotations

import threading
import time

PER_CLIENT_MAX = 5          # wrong codes allowed per client
PER_CLIENT_WINDOW_S = 900   # 15 minutes
GLOBAL_MAX = 60             # wrong codes allowed across all clients
GLOBAL_WINDOW_S = 900

_lock = threading.Lock()
_client: dict[str, list[float]] = {}
_global: list[float] = []


def _prune(stamps: list[float], now: float, window: float) -> None:
    cutoff = now - window
    while stamps and stamps[0] < cutoff:
        stamps.pop(0)


def check(client: str, now: float | None = None) -> float:
    """Seconds to wait before this client may try again (0 means allowed)."""
    now = time.monotonic() if now is None else now
    with _lock:
        mine = _client.setdefault(client, [])
        _prune(mine, now, PER_CLIENT_WINDOW_S)
        _prune(_global, now, GLOBAL_WINDOW_S)
        wait = 0.0
        if len(mine) >= PER_CLIENT_MAX:
            wait = max(wait, PER_CLIENT_WINDOW_S - (now - mine[0]))
        if len(_global) >= GLOBAL_MAX:
            wait = max(wait, GLOBAL_WINDOW_S - (now - _global[0]))
        return max(0.0, wait)


def record_failure(client: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    with _lock:
        _client.setdefault(client, []).append(now)
        _global.append(now)
        # Bound memory: forget clients with nothing left in the window.
        if len(_client) > 4096:
            for key in [k for k, v in _client.items() if not v or now - v[-1] > PER_CLIENT_WINDOW_S]:
                _client.pop(key, None)


def reset() -> None:
    """Tests and the reset-admin path."""
    with _lock:
        _client.clear()
        _global.clear()
