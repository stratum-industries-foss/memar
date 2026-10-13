"""OEE factors must be genuinely distinct — performance != quality (the bug),
and performance must be honest (None) when no slicer estimate exists."""
import pytest

import app.oee as oee
from app.models import HistoryJob, HistoryResponse


def _job(status, print_duration, total_duration, estimated_time=None):
    md = {"estimated_time": estimated_time} if estimated_time is not None else {}
    return HistoryJob(status=status, print_duration=print_duration,
                      total_duration=total_duration, metadata=md)


def _printer():
    return type("P", (), {"id": "p"})()


@pytest.mark.asyncio
async def test_performance_is_distinct_and_real(monkeypatch):
    jobs = [
        _job("completed", print_duration=120, total_duration=130, estimated_time=100),  # slow → 100/120
        _job("completed", print_duration=100, total_duration=110, estimated_time=100),  # on est → 1.0
        _job("completed", print_duration=90, total_duration=100, estimated_time=100),   # fast → cap 1.0
        _job("error", print_duration=50, total_duration=60),
    ]

    async def fake_history(printer, limit=100):
        return HistoryResponse(printer_id="p", jobs=jobs)

    monkeypatch.setattr(oee, "fetch_history", fake_history)
    r = await oee._calc_oee(_printer())

    assert abs(r["quality"] - 0.75) < 1e-9                       # 3 completed / 4 attempted
    expected_perf = (min(1.0, 100 / 120) + 1.0 + 1.0) / 3
    assert r["performance"] is not None
    assert abs(r["performance"] - expected_perf) < 1e-6
    assert r["performance"] != r["quality"]                      # the bug is gone
    assert r["availability"] is not None and r["oee"] is not None


@pytest.mark.asyncio
async def test_performance_none_without_estimates(monkeypatch):
    jobs = [_job("completed", 100, 110), _job("error", 50, 60)]  # no estimated_time

    async def fake_history(printer, limit=100):
        return HistoryResponse(printer_id="p", jobs=jobs)

    monkeypatch.setattr(oee, "fetch_history", fake_history)
    r = await oee._calc_oee(_printer())

    assert r["performance"] is None     # honest — not fabricated from success rate
    assert r["quality"] == 0.5
    assert r["oee"] is None             # can't compute full OEE without performance
