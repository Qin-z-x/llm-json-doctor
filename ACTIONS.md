# jsondoctor canonical action vocabulary (v0.1)

`repair(text, schema=None) -> RepairResult` logs deterministic, machine-readable actions.
Action strings are lowercase snake_case; parameterised actions use `name:key:value` or
`name:detail`. Fixtures assert exact labels via `expected_actions_include`.

| action | meaning |
|---|---|
| `stripped_bom` | removed a UTF-8 BOM |
| `normalized_newlines` | CRLF/CR converted to LF |
| `stripped_control_chars` | removed control chars other than \n and \t |
| `stripped_code_fence` | removed a markdown ```json / ``` fence wrapper |
| `extracted_fragment` | parsed a JSON value out of surrounding prose |
| `replaced_smart_quote` | curly quotes “ ” ‘ ’ normalized |
| `converted_single_quotes` | single-quoted strings converted to double-quoted |
| `quoted_bare_key` | unquoted object key was quoted |
| `removed_line_comment` | // comment removed |
| `removed_block_comment` | /* */ comment removed |
| `removed_trailing_comma` | trailing comma removed |
| `replaced_python_literal` | True/False/None replaced by true/false/null |
| `replaced_nan_infinity` | NaN/Infinity/-Infinity replaced by null (warning too) |
| `fixed_number_sign` | leading + removed from a number |
| `sanitized_escape` | invalid backslash escape repaired |
| `deduplicated_key:last_wins:<key>` | duplicate object key collapsed (warning too) |
| `closed_truncated_json` | unterminated trailing token dropped, open brackets closed (warning too) |
| `replaced_undefined` | JS `undefined` replaced by null |
| `coerced_string_to_integer` | "123" -> 123 for integer schema type |
| `coerced_string_to_number` | "1.5" -> 1.5 for number schema type |
| `coerced_string_to_boolean` | "true"/"false" -> true/false for boolean schema type |
| `coerced_number_to_boolean` | 1/0 -> true/false for boolean schema type |
| `coerced_string_to_null` | "null" -> null for null schema type |
| `wrapped_value_in_array` | scalar wrapped as [scalar] for array schema type |
| `removed_additional_property:<key>` | unknown key dropped because additionalProperties=false (warning too) |

Semantics:
- Fast path: if the extracted fragment already parses and (when a schema is given) validates, `repaired=False`, `actions=[]`.
- `ok=True` only when the resulting data parses and validates against the schema if one was supplied.
- `repaired=True` iff any action was applied (including coercions).
- Truncation repair is deterministic: drop only the incomplete trailing token/member, then close open
  containers; if nothing usable remains, close empty containers. Log `closed_truncated_json` + warning.
- Failures: `ok=False`, `data=None`, `repaired=False`, `actions=[]`, `warnings` contains
  `unparseable: <short reason>` (e.g. `unparseable: prose without JSON`).
- Warnings (human text) do not affect success; they record ambiguity. Never invent field values.

Fixture assertions use only labels from this table (parameterised labels may be matched by prefix:
`deduplicated_key`, `closed_truncated_json`, `removed_additional_property`).