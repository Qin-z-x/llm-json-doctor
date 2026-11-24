"""Deterministic JSON repair + schema validation for untrusted LLM output.

Design rules (see ACTIONS.md):
- pure functions, stdlib only, no eval/exec, no network;
- every transformation is logged as a machine-readable action;
- ambiguity is reported in warnings and never silently invented;
- idempotent fast path: valid input is returned unchanged with no actions.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ACTION_LABELS: Tuple[str, ...] = (
    "stripped_bom",
    "normalized_newlines",
    "stripped_control_chars",
    "stripped_code_fence",
    "extracted_fragment",
    "replaced_smart_quote",
    "converted_single_quotes",
    "quoted_bare_key",
    "removed_line_comment",
    "removed_block_comment",
    "removed_trailing_comma",
    "replaced_python_literal",
    "replaced_nan_infinity",
    "fixed_number_sign",
    "sanitized_escape",
    "deduplicated_key",
    "closed_truncated_json",
    "replaced_undefined",
    "coerced_string_to_integer",
    "coerced_string_to_number",
    "coerced_string_to_boolean",
    "coerced_number_to_boolean",
    "coerced_string_to_null",
    "wrapped_value_in_array",
    "removed_additional_property",
)


class JsonDoctorError(ValueError):
    """Raised only for programmer errors; data problems are returned, not raised."""


@dataclass
class RepairResult:
    data: Any = None
    ok: bool = False
    repaired: bool = False
    actions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    raw: str = ""
    text: str = ""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

_BOM = "\ufeff"
_SMART = {
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
    "\u00ab": '"',
    "\u00bb": '"',
}


def _strip_control(text: str) -> Tuple[str, bool]:
    out = []
    changed = False
    for ch in text:
        code = ord(ch)
        if ch in ("\n", "\t") or code >= 32:
            out.append(ch)
        elif code == 13:
            out.append("\n")
            changed = True
        else:
            changed = True
    return "".join(out), changed


def _balanced_fragment(text: str, start: int) -> Optional[str]:
    r"""Return the balanced {...} / [...] fragment beginning at ``start``."""
    if text[start] not in "{[":
        return None
    stack: List[str] = []
    in_string = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                return None
            stack.pop()
            if not stack:
                return text[start : index + 1]
    return None


def _candidates(text: str) -> Tuple[List[str], str]:
    """Split a raw model reply into candidate JSON fragments, in preference order."""
    candidates: List[str] = []
    fence = re.compile(r"```(?:json|JSON)?\s*(.*)```", re.S)
    for match in fence.finditer(text):
        body = match.group(1).strip()
        if body:
            candidates.append(body)
    stripped = text.strip()
    if stripped:
        candidates.append(stripped)
        for index, ch in enumerate(stripped):
            if ch not in "{[":
                continue
            fragment = _balanced_fragment(stripped, index)
            if fragment and fragment not in candidates:
                candidates.append(fragment)
    # De-duplicate, preserve order, cap work on pathological input.
    seen, unique = set(), []
    for candidate in candidates[:24]:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique, stripped


def _json_loads_logged(fragment: str, actions: List[str], warnings: List[str]) -> Tuple[Any, bool]:
    """json.loads with duplicate-key reporting. Returns (value, ok)."""
    def hook(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                warnings.append(f"duplicate_key:last_wins:{key}")
                actions.append(f"deduplicated_key:last_wins:{key}")
            result[key] = value
        return result

    def parse_constant(token: str) -> Any:
        warnings.append(f"non_finite_number:{token}")
        actions.append("replaced_nan_infinity")
        return None

    try:
        return json.loads(fragment, object_pairs_hook=hook, parse_constant=parse_constant), True
    except (json.JSONDecodeError, ValueError):
        return None, False


# ---------------------------------------------------------------------------
# String-aware transforms
# ---------------------------------------------------------------------------

def _strip_comments(text: str) -> Tuple[str, List[str]]:
    actions: List[str] = []
    out: List[str] = []
    index, in_string, escape = 0, False, False
    while index < len(text):
        ch = text[index]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            index += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            index += 1
            continue
        if ch == "/" and index + 1 < len(text) and text[index + 1] == "/":
            while index < len(text) and text[index] != "\n":
                index += 1
            actions.append("removed_line_comment")
            continue
        if ch == "/" and index + 1 < len(text) and text[index + 1] == "*":
            end = text.find("*/", index + 2)
            if end == -1:
                index = len(text)
            else:
                index = end + 2
            actions.append("removed_block_comment")
            continue
        out.append(ch)
        index += 1
    return "".join(out), actions


def _replace_smart_quotes(text: str) -> Tuple[str, List[str]]:
    actions: List[str] = []
    out = []
    for ch in text:
        if ch in _SMART:
            out.append(_SMART[ch])
            if "replaced_smart_quote" not in actions:
                actions.append("replaced_smart_quote")
        else:
            out.append(ch)
    return "".join(out), actions


def _convert_single_quotes(text: str) -> Tuple[str, List[str]]:
    """Convert single-quoted JSON-ish strings to double-quoted strings."""
    actions: List[str] = []
    out: List[str] = []
    index, in_double, in_single, escape = 0, False, False, False
    while index < len(text):
        ch = text[index]
        if in_double:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_double = False
            index += 1
            continue
        if in_single:
            if escape:
                out.append(ch if ch != "'" else "'")
                escape = False
            elif ch == "\\":
                out.append(ch)
                escape = True
            elif ch == "'":
                out.append('"')
                in_single = False
                actions.append("converted_single_quotes")
            elif ch == '"':
                out.append('\\"')
            else:
                out.append(ch)
            index += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
        elif ch == "'":
            in_single = True
            out.append('"')
        else:
            out.append(ch)
        index += 1
    return "".join(out), actions


def _quote_bare_keys(text: str) -> Tuple[str, List[str]]:
    """Quote object keys that are not already quoted (string-aware)."""
    actions: List[str] = []
    out: List[str] = []
    index, in_string, escape = 0, False, False
    depth_ok = True
    while index < len(text):
        ch = text[index]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            index += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            index += 1
            continue
        if ch.isalpha() or ch in "_$":
            start = index
            while index < len(text) and (text[index].isalnum() or text[index] in "_$.-"):
                index += 1
            word = text[start:index]
            look = index
            while look < len(text) and text[look] in " \t\r\n":
                look += 1
            if look < len(text) and text[look] == ":":
                out.append('"' + word + '"')
                actions.append("quoted_bare_key")
            else:
                out.append(word)
            continue
        out.append(ch)
        index += 1
    return "".join(out), actions


def _replace_tokens_outside_strings(text: str, mapping: Dict[str, str], action: str) -> Tuple[str, List[str]]:
    actions: List[str] = []
    out: List[str] = []
    index, in_string, escape = 0, False, False
    while index < len(text):
        ch = text[index]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            index += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            index += 1
            continue
        matched = None
        for token in mapping:
            if text.startswith(token, index):
                before = text[index - 1] if index > 0 else ""
                after_index = index + len(token)
                after = text[after_index] if after_index < len(text) else ""
                if (not before.isalnum() and before not in "_$") and (not after.isalnum() and after not in "_$"):
                    matched = token
                break
        if matched is not None:
            out.append(mapping[matched])
            actions.append(action)
            index += len(matched)
        else:
            out.append(ch)
            index += 1
    return "".join(out), actions


def _remove_trailing_commas(text: str) -> Tuple[str, List[str]]:
    actions: List[str] = []
    out: List[str] = []
    in_string, escape = False, False
    pending_comma = -1
    for index, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            out.append(ch)
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            pending_comma = -1
            continue
        if ch == ",":
            pending_comma = len(out)
            out.append(ch)
        elif ch in "}]":
            if pending_comma != -1:
                del out[pending_comma]
                actions.append("removed_trailing_comma")
            pending_comma = -1
            out.append(ch)
        elif ch in " \t\r\n":
            out.append(ch)
        else:
            pending_comma = -1
            out.append(ch)
    return "".join(out), actions


def _fix_number_signs(text: str) -> Tuple[str, List[str]]:
    pattern = re.compile(r"([:\[,]\s*)\+(\d)")

    def repl(match: "re.Match[str]") -> str:
        return match.group(1) + match.group(2)

    new_text, count = pattern.subn(repl, text)
    return new_text, ["fixed_number_sign"] if count else []


def _close_truncated(text: str) -> Tuple[str, List[str]]:
    """Best-effort deterministic recovery for truncated JSON."""
    stack: List[str] = []
    in_string, escape = False, False
    last_outside_comma = -1
    for index, ch in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
        elif ch == ",":
            last_outside_comma = index
    if not stack:
        return text, []
    working = text
    if in_string or working.rstrip().endswith((":", ",")):
        cut = last_outside_comma if last_outside_comma != -1 else max(working.rfind("{"), working.rfind("["))
        if cut == -1:
            return text, []
        working = working[:cut]
        # Strip a dangling key if we cut in the middle of a member.
        working = re.sub(r',\s*"[^"]*"\s*:\s*$', "", working)
        working = working.rstrip().rstrip(",")
    closers = "".join("}" if opener == "{" else "]" for opener in reversed(stack))
    return working + closers, ["closed_truncated_json"]


def _strip_eof_trailing_comma(text: str) -> Tuple[str, List[str]]:
    new_text, count = re.subn(r",\s*$", "", text)
    return new_text, ["removed_trailing_comma"] if count else []


def _sanitize_escapes(text: str) -> Tuple[str, List[str]]:
    pattern = re.compile(r"\\x([0-9a-fA-F]{2})")
    new_text, count = pattern.subn(lambda m: "\\u00" + m.group(1).lower(), text)
    return new_text, ["sanitized_escape"] if count else []


# ---------------------------------------------------------------------------
# Schema validation and coercion
# ---------------------------------------------------------------------------

_SCHEMA_TYPES = ("object", "array", "string", "number", "integer", "boolean", "null")


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def validate_schema(value: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """Validate against the minimal schema subset documented in the README."""
    errors: List[str] = []
    if not isinstance(schema, dict):
        return [f"{path}: schema must be an object"]
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        errors.append(f"{path}: value {value!r} not in enum {enum!r}")
    expected = schema.get("type")
    if expected in _SCHEMA_TYPES and not _type_ok(value, expected):
        errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
        return errors
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        if isinstance(properties, dict):
            for name, subschema in properties.items():
                if name in value:
                    errors.extend(validate_schema(value[name], subschema, f"{path}.{name}"))
        for name in schema.get("required") or []:
            if name not in value:
                errors.append(f"{path}: missing required key {name!r}")
        if schema.get("additionalProperties") is False and isinstance(properties, dict):
            extras = [key for key in value if key not in properties]
            if extras:
                errors.append(f"{path}: unexpected key(s) {sorted(extras)!r}")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(validate_schema(item, schema["items"], f"{path}[{index}]"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} above maximum {schema['maximum']}")
    return errors


def _coerce(value: Any, schema: Dict[str, Any], path: str, actions: List[str], warnings: List[str]) -> Any:
    expected = schema.get("type") if isinstance(schema, dict) else None
    if expected == "array" and not isinstance(value, list):
        value = [value]
        actions.append("wrapped_value_in_array")
    if expected == "integer" and isinstance(value, str) and re.fullmatch(r"[-+]?\d+", value.strip()):
        value = int(value.strip())
        actions.append("coerced_string_to_integer")
    elif expected == "number" and isinstance(value, str) and re.fullmatch(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?", value.strip()):
        number = float(value.strip())
        value = int(number) if number.is_integer() else number
        actions.append("coerced_string_to_number")
    elif expected == "boolean" and isinstance(value, str) and value.strip().lower() in ("true", "false"):
        value = value.strip().lower() == "true"
        actions.append("coerced_string_to_boolean")
    elif expected == "boolean" and isinstance(value, (int, float)) and value in (0, 1):
        value = bool(value)
        actions.append("coerced_number_to_boolean")
    elif expected == "null" and isinstance(value, str) and value.strip().lower() == "null":
        value = None
        actions.append("coerced_string_to_null")
    if expected == "object" and isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key in list(value):
            if isinstance(properties, dict) and key in properties:
                value[key] = _coerce(value[key], properties[key], f"{path}.{key}", actions, warnings)
            elif schema.get("additionalProperties") is False and isinstance(properties, dict):
                del value[key]
                actions.append(f"removed_additional_property:{key}")
                warnings.append(f"removed_additional_property:{key}")
    if expected == "array" and isinstance(value, list) and isinstance(schema.get("items"), dict):
        value = [_coerce(item, schema["items"], f"{path}[{index}]", actions, warnings) for index, item in enumerate(value)]
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _preclean(raw: str) -> Tuple[str, List[str], List[str]]:
    actions: List[str] = []
    warnings: List[str] = []
    text = raw
    if text.startswith(_BOM):
        text = text[1:]
        actions.append("stripped_bom")
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        actions.append("normalized_newlines")
    text, changed = _strip_control(text)
    if changed:
        actions.append("stripped_control_chars")
    return text, actions, warnings


def _repair_fragment(fragment: str, actions: List[str], warnings: List[str]) -> Optional[str]:
    """Apply deterministic repairs until the fragment parses (or give up)."""
    working = fragment
    for _ in range(12):
        value, ok = _json_loads_logged(working, actions, warnings)
        if ok:
            return working
        transforms = [
            _replace_smart_quotes,
            _strip_comments,
            _remove_trailing_commas,
            _convert_single_quotes,
            _quote_bare_keys,
            lambda t: _replace_tokens_outside_strings(t, {"True": "true", "False": "false", "None": "null"}, "replaced_python_literal"),
            lambda t: _replace_tokens_outside_strings(t, {"NaN": "null", "Infinity": "null", "-Infinity": "null"}, "replaced_nan_infinity"),
            lambda t: _replace_tokens_outside_strings(t, {"undefined": "null"}, "replaced_undefined"),
            _fix_number_signs,
            _sanitize_escapes,
            _strip_eof_trailing_comma,
        ]
        progressed = False
        for transform in transforms:
            new_working, new_actions = transform(working)
            if new_working != working:
                working = new_working
                actions.extend(new_actions)
                progressed = True
                break
        if progressed:
            continue
        # Truncation recovery is attempted only after all token/quote repairs.
        new_working, new_actions = _close_truncated(working)
        if new_working != working and new_actions:
            working = new_working
            actions.extend(new_actions)
            warnings.append("repaired truncated JSON by closing open containers")
            continue
        break
    value, ok = _json_loads_logged(working, actions, warnings)
    return working if ok else None


def repair(text: str, schema: Optional[Dict[str, Any]] = None) -> RepairResult:
    """Repair ``text`` into a JSON value and optionally validate/coerce to ``schema``."""
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    raw = text
    cleaned, pre_actions, warnings = _preclean(text)
    candidates, stripped = _candidates(cleaned)
    fenced = {
        match.group(1).strip()
        for match in re.finditer(r"```(?:json|JSON)?\s*(.*)```", cleaned, re.S)
        if match.group(1).strip()
    }
    if not candidates:
        return RepairResult(
            data=None, ok=False, repaired=False, actions=[], warnings=["unparseable: empty input"], raw=raw, text=""
        )

    # Fast path: first candidate that parses cleanly (and validates, if a schema is given).
    for candidate in candidates:
        fast_actions: List[str] = []
        fast_warnings: List[str] = []
        value, ok = _json_loads_logged(candidate, fast_actions, fast_warnings)
        if not ok:
            continue
        if candidate != stripped and candidate not in fenced:
            continue
        actions = list(pre_actions) + fast_actions
        warnings = list(warnings) + fast_warnings
        if candidate != stripped:
            actions.append("stripped_code_fence" if candidate in fenced else "extracted_fragment")
        if schema is None:
            return RepairResult(
                data=value, ok=True, repaired=bool(actions), actions=actions,
                warnings=warnings, raw=raw, text=candidate,
            )
        errors = validate_schema(value, schema)
        if not errors:
            return RepairResult(
                data=value, ok=True, repaired=bool(actions), actions=actions,
                warnings=warnings, raw=raw, text=candidate,
            )

    last_error = "no JSON candidate found"
    schema_errors: List[str] = []
    for candidate in candidates:
        actions: List[str] = list(pre_actions)
        local_warnings: List[str] = list(warnings)
        if candidate != stripped:
            actions.append("stripped_code_fence" if candidate in fenced else "extracted_fragment")
        working = _repair_fragment(candidate, actions, local_warnings)
        if working is None:
            last_error = local_warnings[-1] if local_warnings else "unparseable fragment"
            continue
        value = _json_loads_logged(working, [], [])[0]
        if schema is not None:
            errors = validate_schema(value, schema)
            if errors:
                value = _coerce(value, schema, "$", actions, local_warnings)
                errors = validate_schema(value, schema)
            if errors:
                local_warnings.extend(f"schema: {error}" for error in errors)
                schema_errors = [f"schema: {error}" for error in errors]
                last_error = "schema validation failed"
                continue
        repaired = bool(actions)
        return RepairResult(
            data=value,
            ok=True,
            repaired=repaired,
            actions=actions,
            warnings=local_warnings,
            raw=raw,
            text=working,
        )

    if schema_errors:
        return RepairResult(
            data=None, ok=False, repaired=False, actions=[], warnings=schema_errors, raw=raw, text=""
        )
    return RepairResult(
        data=None,
        ok=False,
        repaired=False,
        actions=[],
        warnings=[f"unparseable: {last_error}"],
        raw=raw,
        text="",
    )


def extract_json(text: str) -> Tuple[Optional[Any], str, List[str]]:
    """Convenience wrapper: returns (value_or_None, error, actions)."""
    result = repair(text)
    if result.ok:
        return result.data, "", result.actions
    return None, result.warnings[0] if result.warnings else "unparseable", result.actions
