from datetime import date, timedelta

from app.fleet import _printer_maintenance_due
from app.models import PrinterConfig


def _pc(**kw) -> PrinterConfig:
    return PrinterConfig(id="p", name="P", base_url="http://x", **kw)


def test_boolean_fallback_when_no_date():
    assert _printer_maintenance_due(_pc(maintenance_due=True)) is True
    assert _printer_maintenance_due(_pc(maintenance_due=False)) is False


def test_past_date_marks_due_even_if_boolean_false():
    past = (date.today() - timedelta(days=1)).isoformat()
    assert _printer_maintenance_due(_pc(maintenance_due=False, next_service_due=past)) is True


def test_future_date_clears_due_even_if_boolean_true():
    future = (date.today() + timedelta(days=30)).isoformat()
    assert _printer_maintenance_due(_pc(maintenance_due=True, next_service_due=future)) is False


def test_today_counts_as_due():
    today = date.today().isoformat()
    assert _printer_maintenance_due(_pc(maintenance_due=False, next_service_due=today)) is True


def test_invalid_date_falls_back_to_boolean():
    assert _printer_maintenance_due(_pc(maintenance_due=True, next_service_due="not-a-date")) is True
    assert _printer_maintenance_due(_pc(maintenance_due=False, next_service_due="2026-13-99")) is False


def test_interval_overdue_marks_due():
    # last service 10 days ago, interval of 5 days (120h) → overdue
    old = (date.today() - timedelta(days=10)).isoformat()
    assert _printer_maintenance_due(
        _pc(maintenance_due=False, last_service_at=old, maintenance_interval_hours=120)
    ) is True


def test_interval_not_yet_due():
    # last service yesterday, interval of 30 days (720h) → not yet due
    recent = (date.today() - timedelta(days=1)).isoformat()
    assert _printer_maintenance_due(
        _pc(maintenance_due=False, last_service_at=recent, maintenance_interval_hours=720)
    ) is False


def test_explicit_next_service_due_wins_over_interval():
    # interval would say "due" (last service long ago), but a future explicit
    # override date must take precedence and clear the due state.
    old = (date.today() - timedelta(days=100)).isoformat()
    future = (date.today() + timedelta(days=30)).isoformat()
    assert _printer_maintenance_due(
        _pc(
            maintenance_due=True,
            last_service_at=old,
            maintenance_interval_hours=24,
            next_service_due=future,
        )
    ) is False


def test_bad_last_service_date_falls_back_to_boolean():
    assert _printer_maintenance_due(
        _pc(maintenance_due=True, last_service_at="not-a-date", maintenance_interval_hours=24)
    ) is True
    assert _printer_maintenance_due(
        _pc(maintenance_due=False, last_service_at="2026-13-99", maintenance_interval_hours=24)
    ) is False


def test_interval_ignored_when_zero_or_missing():
    # interval of 0 or missing → no derivation, fall back to boolean
    old = (date.today() - timedelta(days=100)).isoformat()
    assert _printer_maintenance_due(
        _pc(maintenance_due=False, last_service_at=old, maintenance_interval_hours=0)
    ) is False
    assert _printer_maintenance_due(
        _pc(maintenance_due=True, last_service_at=old)
    ) is True
