"""Tests for the Spoolman `extra`-field parser (real Spoolman API shape)."""
from app.spoolman import _extra


def test_extra_reads_json_encoded_dict():
    # Real Spoolman: extra is a dict of JSON-encoded strings.
    spool = {"id": 1, "extra": {"printer_id": '"voron-1"', "printer_name": '"Voron 2.4"'}}
    assert _extra(spool, "printer_id") == "voron-1"
    assert _extra(spool, "printer_name") == "Voron 2.4"


def test_extra_populated_dict_does_not_crash():
    # Regression: the old list-iteration raised AttributeError ('str' has no
    # attribute 'get') on ANY spool with extras set.
    spool = {"id": 2, "extra": {"printer_id": '"p1"'}}
    assert _extra(spool, "printer_id") == "p1"


def test_extra_missing_or_empty_returns_none():
    assert _extra({"extra": {}}, "printer_id") is None
    assert _extra({}, "printer_id") is None
    assert _extra({"extra": {"other": '"x"'}}, "printer_id") is None
