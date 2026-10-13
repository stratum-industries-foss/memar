import pytest
from app.adapter_ok import require_adapter_ok


class TestRequireAdapterOk:
    def test_returns_result_when_ok_true(self):
        result = {"ok": True, "data": "test"}
        assert require_adapter_ok(result, action="test") == result

    def test_raises_when_none(self):
        with pytest.raises(RuntimeError, match="no response"):
            require_adapter_ok(None, action="test")

    def test_raises_when_empty(self):
        with pytest.raises(RuntimeError, match="no response"):
            require_adapter_ok({}, action="test")

    def test_raises_when_ok_false_with_error(self):
        result = {"ok": False, "error": "Connection refused"}
        with pytest.raises(RuntimeError, match="Connection refused"):
            require_adapter_ok(result, action="test")

    def test_raises_when_ok_false_with_message(self):
        result = {"ok": False, "message": "Timeout"}
        with pytest.raises(RuntimeError, match="Timeout"):
            require_adapter_ok(result, action="test")

    def test_raises_when_ok_false_with_response(self):
        result = {"ok": False, "response": "Printer offline"}
        with pytest.raises(RuntimeError, match="Printer offline"):
            require_adapter_ok(result, action="test")

    def test_raises_with_action_when_no_error_message(self):
        result = {"ok": False}
        with pytest.raises(RuntimeError, match="test failed"):
            require_adapter_ok(result, action="test")

    def test_passes_when_ok_missing_but_has_data(self):
        # If ok key is missing but result is truthy, we should probably still pass
        # Actually no - we want to be strict. Let's check the impl.
        result = {"data": "test"}  # no 'ok' key
        # This should pass since ok is not explicitly False
        assert require_adapter_ok(result, action="test") == result
