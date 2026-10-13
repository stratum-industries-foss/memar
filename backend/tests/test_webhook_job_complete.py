"""Regression: printer.complete must fire for non-Moonraker adapters, which
finish a print by going printing -> "ready" (never "complete"/"idle")."""
import pytest
from types import SimpleNamespace

from app import webhooks


def _printer(pid, state, online=True, filename="part.gcode"):
    return SimpleNamespace(id=pid, online=online,
                           job=SimpleNamespace(state=state, filename=filename))


def _drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


@pytest.fixture(autouse=True)
def _reset_and_silence(monkeypatch):
    # Deterministic module state + silence the fire-and-forget side effects so
    # the test doesn't depend on DB/telemetry/config being wired up.
    webhooks._prev_states.clear()
    _drain(webhooks._event_queue)

    async def _noop_deduct(p):
        return None

    monkeypatch.setattr(webhooks, "_deduct_spool_on_complete", _noop_deduct)
    monkeypatch.setattr(webhooks, "_record_job", lambda *a, **k: None)
    yield
    webhooks._prev_states.clear()
    _drain(webhooks._event_queue)


@pytest.mark.asyncio
async def test_printing_to_ready_fires_complete():
    pid = "octo-1"
    await webhooks.detect_state_changes([_printer(pid, "printing")])  # establish prev
    await webhooks.detect_state_changes([_printer(pid, "ready")])     # job ends -> "ready"
    events = _drain(webhooks._event_queue)
    completes = [e for e in events if e["type"] == "printer.complete" and e["printer_id"] == pid]
    assert len(completes) == 1


@pytest.mark.asyncio
async def test_moonraker_complete_still_fires():
    pid = "voron-1"
    await webhooks.detect_state_changes([_printer(pid, "printing")])
    await webhooks.detect_state_changes([_printer(pid, "complete")])
    events = _drain(webhooks._event_queue)
    assert any(e["type"] == "printer.complete" and e["printer_id"] == pid for e in events)


@pytest.mark.asyncio
async def test_idle_printer_does_not_spuriously_complete():
    pid = "octo-2"
    await webhooks.detect_state_changes([_printer(pid, "ready")])   # never printed
    await webhooks.detect_state_changes([_printer(pid, "ready")])   # still idle
    events = _drain(webhooks._event_queue)
    assert not any(e["type"] == "printer.complete" for e in events)
