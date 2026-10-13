"""Helper to enforce adapter result contracts."""


def require_adapter_ok(result: dict | None, *, action: str) -> dict:
    """Validate adapter result and raise RuntimeError if ok is False or missing.
    
    Args:
        result: The adapter response dict, expected to have 'ok' key
        action: Description of the action for error messages
        
    Returns:
        The result dict if ok is truthy
        
    Raises:
        RuntimeError: If result is None, empty, or ok is False
    """
    if not result:
        raise RuntimeError(f"{action}: no response from adapter")
    
    if result.get("ok") is False:
        # Extract error message from various possible keys
        msg = (
            result.get("error")
            or result.get("message")
            or result.get("response")
            or f"{action} failed"
        )
        raise RuntimeError(str(msg))
    
    return result
