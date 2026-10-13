"""PERF-FLEET-SEQFETCH-01/02/03: dry_run_batch_action, fetch_fleet_metrics,
and dispatch_dry_run each fetched one printer at a time in a sequential loop
— total latency scaled linearly with fleet size instead of staying close to
the slowest single printer, unlike every sibling batch-fetch path in this
file (which already gathers).

Not an output-equality concern (the fetch functions are monkeypatched to
return fixed data either way) — the only observable difference is wall-clock
time. Race N printers' fetches (each with a fixed simulated latency) and
assert total time stays close to ONE fetch's duration, not N of them.
"""
import asyncio
import time

import pytest

import app.fleet as fleet
from app.models import (
    DispatchDryRunRequest,
    DryRunRequest,
    FleetPrinterStatus,
    HistoryResponse,
    MachineType,
    PrinterConfig,
    Protocol,
)

FETCH_SECONDS = 0.1
N_PRINTERS = 5


def _printer(pid: str) -> PrinterConfig:
    return PrinterConfig(
        id=pid, name=pid, base_url=f"http://{pid}:80",
        machine_type=MachineType.FDM, protocol=Protocol.OCTOPRINT,
    )


def _status(pid: str) -> FleetPrinterStatus:
    return FleetPrinterStatus(
        id=pid, name=pid, base_url=f"http://{pid}:80",
        enabled=True, online=True, state="idle",
    )


@pytest.mark.asyncio
async def test_dry_run_batch_action_fetches_concurrently(monkeypatch):
    printers = [_printer(f"p{i}") for i in range(N_PRINTERS)]

    async def slow_fetch_status(printer):
        await asyncio.sleep(FETCH_SECONDS)
        return _status(printer.id)

    monkeypatch.setattr(fleet, "fetch_printer_status", slow_fetch_status)

    request = DryRunRequest(printer_ids=[p.id for p in printers])
    start = time.monotonic()
    result = await fleet.dry_run_batch_action(printers, request, "home")
    elapsed = time.monotonic() - start

    assert len(result.results) == N_PRINTERS
    # Pre-fix: N sequential fetches take ~N * FETCH_SECONDS. Post-fix: gathered
    # concurrently, total time stays close to a single fetch's duration.
    assert elapsed < FETCH_SECONDS * (N_PRINTERS / 2), (
        f"{N_PRINTERS} printer fetches took {elapsed:.2f}s "
        f"(~{elapsed / FETCH_SECONDS:.1f}x a single fetch) — looks sequential, not concurrent"
    )


@pytest.mark.asyncio
async def test_dispatch_dry_run_evaluates_concurrently(monkeypatch):
    printers = [_printer(f"p{i}") for i in range(N_PRINTERS)]

    async def slow_fetch_status(printer):
        await asyncio.sleep(FETCH_SECONDS)
        return _status(printer.id)

    async def fast_get_client(printer):
        # Real client construction (OctoPrintClient etc.) pays a ~0.2s one-time
        # warmup cost (SSL context / httpx init) on first call in the process —
        # irrelevant to what this test checks (fetch_printer_status concurrency)
        # and large enough to swamp the timing budget. Bypass it.
        return object()

    monkeypatch.setattr(fleet, "fetch_printer_status", slow_fetch_status)
    monkeypatch.setattr(fleet, "_get_client", fast_get_client)

    request = DispatchDryRunRequest(filename="test.gcode")
    start = time.monotonic()
    result = await fleet.dispatch_dry_run(printers, request)
    elapsed = time.monotonic() - start

    assert len(result.results) == N_PRINTERS
    assert elapsed < FETCH_SECONDS * (N_PRINTERS / 2), (
        f"{N_PRINTERS} printer evaluations took {elapsed:.2f}s "
        f"(~{elapsed / FETCH_SECONDS:.1f}x a single fetch) — looks sequential, not concurrent"
    )


@pytest.mark.asyncio
async def test_fetch_fleet_metrics_fetches_history_concurrently(monkeypatch):
    printers = [_printer(f"p{i}") for i in range(N_PRINTERS)]

    async def fast_fetch_fleet(printers_arg):
        return [_status(p.id) for p in printers_arg]

    async def slow_fetch_history(printer, limit=15):
        await asyncio.sleep(FETCH_SECONDS)
        return HistoryResponse(printer_id=printer.id)

    monkeypatch.setattr(fleet, "fetch_fleet", fast_fetch_fleet)
    monkeypatch.setattr(fleet, "fetch_history", slow_fetch_history)

    start = time.monotonic()
    result = await fleet.fetch_fleet_metrics(printers)
    elapsed = time.monotonic() - start

    assert len(result.printers) == N_PRINTERS
    assert elapsed < FETCH_SECONDS * (N_PRINTERS / 2), (
        f"{N_PRINTERS} history fetches took {elapsed:.2f}s "
        f"(~{elapsed / FETCH_SECONDS:.1f}x a single fetch) — looks sequential, not concurrent"
    )
