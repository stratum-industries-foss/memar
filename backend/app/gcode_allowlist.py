"""Single-line G/M/T command or MACRO=value allowlist for console input."""
import re

_LINE = re.compile(
    r"^(?:[GMT]\d+(?:\.\d+)?(?:\s+[A-Z]-?\d+(?:\.\d+)?){0,16}|[A-Za-z][A-Za-z0-9_]{0,48}(?:\s+[A-Za-z0-9_]+=[A-Za-z0-9._-]{1,32}){0,8})$"
)
_MAX_LENGTH = 240
_BLOCKED = frozenset({"SAVE_CONFIG", "FIRMWARE_RESTART", "RESTART", "M112"})


def validate_console_script(script: str) -> str:
    """Validate and normalize a console G-code command.
    
    Raises ValueError if the script is invalid, too long, multiline,
    or contains blocked commands.
    
    Returns the stripped script on success.
    """
    s = (script or "").strip()
    if not s:
        raise ValueError("script must not be empty")
    if len(s) > _MAX_LENGTH:
        raise ValueError(f"script exceeds {_MAX_LENGTH} characters")
    if "\n" in s or "\r" in s or ";" in s:
        raise ValueError("script must be a single line without semicolons")
    if s.upper() in _BLOCKED:
        raise ValueError(f"command {s.upper()} is blocked")
    if not _LINE.match(s):
        raise ValueError("script rejected: must be G/M/T command or MACRO with params")
    return s
