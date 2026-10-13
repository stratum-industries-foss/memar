"""Best-effort inference of Klipper ``[gcode_macro]`` parameters.

Klipper has **no declarative parameter syntax**. A macro's inputs exist only as
Jinja expressions inside its gcode body::

    [gcode_macro PRINT_START]
    variable_category: 'Printing'
    gcode:
      {% set bed = params.BED|default(60)|int %}
      M104 S{params.EXTRUDER|default(200)|int}
      M140 S{params.get('BED_TEMP', 60)|float}

so the only way to offer typed inputs in a UI is to read the body back out of
``configfile.settings`` and infer from it. This is deliberately *best effort*:
conditionals, nested macro calls and computed defaults defeat static analysis.
Anything that cannot be typed falls back to ``"string"``, which the UI renders
as the same free-text field it has always used — a miss degrades to the old
behaviour, it never fails.

Nothing here executes or renders the template. It is pure pattern matching over
text, so a hostile macro body can at worst produce a useless param list.
"""

from __future__ import annotations

import ast
import re
from typing import Any

# Klipper builds its Jinja environment with single-brace delimiters
# (``variable_start_string='{'``), so expressions are ``{params.X}`` and not the
# stock ``{{ params.X }}``. Statements keep the standard ``{% ... %}`` form.
# Matching the enclosing expression first — rather than scanning the raw body —
# is what keeps a filter from being attributed across an expression boundary.
_EXPRESSION_RE = re.compile(r"\{%.*?%\}|\{[^{}]*\}", re.DOTALL)

# ``params.NAME``. The trailing ``\b(?!\s*\()`` rejects method calls
# (``params.get(...)``, ``params.items()``) — the ``\b`` is load-bearing: without
# it the engine happily backtracks the name to ``ge`` so that the lookahead
# passes, and invents a parameter called "ge".
_ATTR_RE = re.compile(r"params\s*\.\s*([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()")
# ``params['NAME']`` / ``params["NAME"]``
_INDEX_RE = re.compile(r"""params\s*\[\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\]""")
# ``params.get('NAME'`` — the default (if any) is parsed from the tail.
_GET_RE = re.compile(r"""params\s*\.\s*get\s*\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]""")

# A Jinja filter that pins the type. ``round`` implies a number even though it
# is not a cast.
_TYPE_FILTER_RE = re.compile(r"\|\s*(int|float|string|round)\b")
# ``|default(<literal>)``, optionally with Jinja's second boolean argument.
_DEFAULT_FILTER_RE = re.compile(r"\|\s*default\s*\(\s*([^()]*?)\s*\)")
# The ``, <literal>)`` tail of ``params.get('NAME', <literal>)``.
_GET_DEFAULT_RE = re.compile(r"^\s*,\s*([^,()]+?)\s*\)")

_FILTER_TO_TYPE = {"int": "int", "float": "float", "string": "string", "round": "float"}

# dict/Jinja builtins that are never parameter names even if they slip past the
# lookahead above (e.g. ``params.items|list``).
_NOT_PARAM_NAMES = frozenset(
    {"get", "items", "keys", "values", "update", "pop", "setdefault", "copy"}
)

# Pathological or hostile configs must not turn macro listing into a CPU sink.
_MAX_BODY_CHARS = 200_000
_MAX_PARAMS = 64
_MAX_CATEGORY_CHARS = 40

# ``color`` is handed to the browser as a CSS colour. Restrict it to hex and
# bare colour keywords so a macro author cannot inject arbitrary CSS through
# printer.cfg.
_COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20})$")


def _parse_literal(text: str) -> Any | None:
    """Return a Python scalar for a Jinja literal, or None if it isn't one.

    ``|default(printer.extruder.target)`` is a perfectly valid macro that has no
    *static* default — returning None there is the correct answer, not a
    failure, and the UI simply shows no placeholder.
    """
    text = (text or "").strip()
    if not text:
        return None
    # Jinja spells the booleans/none in lower case; ast.literal_eval will not.
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("none", "null"):
        return None
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None
    if isinstance(value, bool) or isinstance(value, (int, float, str)):
        return value
    return None


def _default_from_tail(tail: str, kind: str) -> Any | None:
    """Extract a literal default from the text following a param reference."""
    if kind == "get":
        match = _GET_DEFAULT_RE.match(tail)
        if match:
            return _parse_literal(match.group(1))
        return None
    match = _DEFAULT_FILTER_RE.search(tail)
    if not match:
        return None
    # ``default(60, true)`` — the second argument is Jinja's "treat falsy as
    # missing" flag, not part of the value.
    return _parse_literal(match.group(1).split(",")[0])


def _type_from_tail(tail: str) -> str | None:
    match = _TYPE_FILTER_RE.search(tail)
    if not match:
        return None
    return _FILTER_TO_TYPE.get(match.group(1))


def _references(expression: str) -> list[tuple[int, int, str, str]]:
    """All ``params`` references in one expression, ordered by position.

    Returns ``(start, end, name, kind)``. The three patterns are mutually
    exclusive by construction, so no de-duplication is needed.
    """
    found: list[tuple[int, int, str, str]] = []
    for pattern, kind in ((_GET_RE, "get"), (_INDEX_RE, "index"), (_ATTR_RE, "attr")):
        for match in pattern.finditer(expression):
            name = match.group(1)
            if name in _NOT_PARAM_NAMES:
                continue
            found.append((match.start(), match.end(), name, kind))
    found.sort(key=lambda item: item[0])
    return found


def infer_macro_params(gcode_body: str | None) -> dict[str, dict[str, Any]]:
    """Infer the parameters a Klipper macro body reads.

    Returns ``{"TEMP": {"type": "int", "default": 200}, ...}``. ``type`` is one
    of ``int`` / ``float`` / ``string`` and is never None; ``default`` is None
    when the macro has no statically-known default.

    Type comes from an explicit Jinja cast filter (``|int``, ``|float``,
    ``|string``, ``|round``). Failing that it is taken from the *literal type of
    the default* — ``{params.BED|default(60)}`` feeding ``M140 S...`` is a
    number by any reasonable reading — and failing that it falls back to
    ``"string"``, the untyped free-text case.

    A parameter referenced more than once with different filters keeps the first
    concrete answer for each of type and default rather than raising; macros
    that do this are ambiguous by nature and a wrong guess still renders.
    """
    if not gcode_body:
        return {}
    body = gcode_body[:_MAX_BODY_CHARS]
    if "params" not in body:
        return {}

    collected: dict[str, dict[str, Any]] = {}
    for expression_match in _EXPRESSION_RE.finditer(body):
        expression = expression_match.group(0)
        if "params" not in expression:
            continue
        references = _references(expression)
        for index, (_start, end, name, kind) in enumerate(references):
            # The tail runs to the next reference so a filter is never
            # attributed to the wrong parameter in a multi-param expression
            # such as ``{params.A|int + params.B|default(2)|float}``.
            tail_end = references[index + 1][0] if index + 1 < len(references) else len(expression)
            tail = expression[end:tail_end]

            spec = collected.setdefault(name, {"type": None, "default": None})
            if spec["type"] is None:
                spec["type"] = _type_from_tail(tail)
            if spec["default"] is None:
                spec["default"] = _default_from_tail(tail, kind)
            if len(collected) >= _MAX_PARAMS:
                break
        if len(collected) >= _MAX_PARAMS:
            break

    result: dict[str, dict[str, Any]] = {}
    for name, spec in collected.items():
        inferred = spec["type"]
        if inferred is None:
            default = spec["default"]
            # bool is a subclass of int — check it first so a boolean default
            # does not masquerade as an integer field.
            if isinstance(default, bool):
                inferred = "string"
            elif isinstance(default, int):
                inferred = "int"
            elif isinstance(default, float):
                inferred = "float"
            else:
                inferred = "string"
        result[name] = {"type": inferred, "default": spec["default"]}
    return result


def parse_config_value(raw: Any) -> str | None:
    """Normalise a raw ``configfile.settings`` value into a plain string.

    Klipper's ``variable_*`` options are recorded in ``configfile.settings`` as
    the *raw config text*, which for a string variable includes the quotes that
    ``ast.literal_eval`` needs (``variable_category: 'Printing'`` is reported as
    ``"'Printing'"``). Strip them when present, pass the text through when not.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        if isinstance(raw, bool):
            return None
        if isinstance(raw, (int, float)):
            return str(raw)
        return None
    text = raw.strip()
    if not text:
        return None
    parsed = _parse_literal(text)
    if isinstance(parsed, str):
        return parsed.strip() or None
    if isinstance(parsed, bool):
        return None
    if isinstance(parsed, (int, float)):
        return str(parsed)
    return text


def clean_category(value: str | None) -> str | None:
    if not value:
        return None
    # Control characters would corrupt the grouping headers in the UI.
    cleaned = "".join(char for char in value if char.isprintable()).strip()
    if not cleaned:
        return None
    return cleaned[:_MAX_CATEGORY_CHARS]


def clean_color(value: str | None) -> str | None:
    """Accept only hex colours and bare colour keywords.

    The value ends up in an inline ``style`` attribute; anything else is dropped
    rather than sanitised, because a partially-valid CSS value is not worth the
    risk for a cosmetic feature.
    """
    if not value:
        return None
    candidate = value.strip()
    if not _COLOR_RE.match(candidate):
        return None
    return candidate


def macro_metadata(section: Any) -> tuple[dict[str, dict[str, Any]], str | None, str | None]:
    """Derive ``(params, category, color)`` from one ``gcode_macro`` section.

    ``section`` is the dict Klipper reports under
    ``configfile.settings["gcode_macro <name>"]``. A missing or malformed
    section yields empty metadata rather than an error — macro listing must keep
    working on printers whose configfile query fails or returns a shape we did
    not expect.
    """
    if not isinstance(section, dict):
        return {}, None, None
    gcode = section.get("gcode")
    params = infer_macro_params(gcode if isinstance(gcode, str) else None)
    category = clean_category(parse_config_value(section.get("variable_category")))
    color = clean_color(parse_config_value(section.get("variable_color")))
    return params, category, color
