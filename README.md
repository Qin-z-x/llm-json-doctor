# llm-json-doctor

**Deterministic repair and validation for malformed LLM JSON.**

[![CI](https://github.com/Qin-Z-x/llm-json-doctor/actions/workflows/ci.yml/badge.svg)](https://github.com/Qin-Z-x/llm-json-doctor/actions/workflows/ci.yml)
[![license](https://img.shields.io/github/license/Qin-Z-x/llm-json-doctor)](LICENSE)
[![python](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)

> **If this is useful, a star or fork helps others find it.** It is a small, unaided project; stars/fork counts are the honest signal that keeps it maintained. No accounts, no telemetry, no paid promotion.

Your LLM returned JSON. Almost.

It wrapped it in a markdown fence, used single quotes, left a trailing comma,
added a comment, printed `True` instead of `true`, or got cut off mid-object.
`llm-json-doctor` repairs that output with a deterministic, auditable pipeline —
and validates the result against a JSON Schema, telling you exactly what it
changed instead of silently guessing. Standard library only. No LLM calls. No
network. No `eval`.

## Quick start (no install, no API key)

```shell
python -m jsondoctor demo
echo '{"name": "Ada", "tags": ["math",], "ok": True,}' | python -m jsondoctor repair
python -m jsondoctor repair response.txt --schema schema.json --json
```

```text
before: {"name": "Ada", "tags": ["math",], "ok": True,}
after:  {"name":"Ada","tags":["math"],"ok":true}   # removed_trailing_comma, replaced_python_literal
```

## What it fixes

| Input problem | Logged action |
| --- | --- |
| markdown fence, prose around the JSON | `stripped_code_fence`, `extracted_fragment` |
| single-quoted strings, curly quotes | `converted_single_quotes`, `replaced_smart_quote` |
| unquoted keys | `quoted_bare_key` |
| trailing commas | `removed_trailing_comma` |
| `//` and `/* */` comments | `removed_line_comment`, `removed_block_comment` |
| `True` / `False` / `None`, `undefined` | `replaced_python_literal`, `replaced_undefined` |
| `NaN` / `Infinity` | `replaced_nan_infinity` (plus a warning) |
| truncated output | `closed_truncated_json` (plus a warning) |
| duplicate keys | `deduplicated_key:last_wins:<key>` (plus a warning) |
| invalid `\x` escapes, leading `+` numbers | `sanitized_escape`, `fixed_number_sign` |

Everything composes, so a reply with a fence, single quotes, Python literals,
comments *and* a trailing comma is repaired in one pass.

## Schema validation and safe coercion

Pass `schema` (library) or `--schema` (CLI) to validate against a minimal JSON
Schema subset: `type`, `properties`, `required`, `additionalProperties`,
`items`, `enum`, `minimum`, `maximum`.

Rather than silently inventing data, `llm-json-doctor` applies only conservative,
logged coercions:

| Schema expects | Observed | Action |
| --- | --- | --- |
| `integer` | `"42"` | `coerced_string_to_integer` |
| `number` | `"1.5"` | `coerced_string_to_number` |
| `boolean` | `"true"` / `1` | `coerced_string_to_boolean` / `coerced_number_to_boolean` |
| `null` | `"null"` | `coerced_string_to_null` |
| `array` | scalar value | `wrapped_value_in_array` |
| `additionalProperties: false` | unknown key | `removed_additional_property:<key>` (plus warning) |

Missing required fields are **reported, never filled in**. If the object still
does not validate, the call fails with explicit `schema:` messages.

## Library API

```python
from jsondoctor import repair, validate_schema

result = repair(llm_output, schema={"type": "object", "required": ["name"]})
result.ok          # True when parsed (and schema-valid, when a schema was given)
result.data        # the repaired value
result.repaired    # True if anything was changed
result.actions     # ["stripped_code_fence", "removed_trailing_comma", ...]
result.warnings    # ambiguities, e.g. "duplicate_key:last_wins:name"
```

`extract_json(text)` is a convenience wrapper returning `(value, error, actions)`.
`validate_schema(value, schema)` returns a list of human-readable errors.

## CLI

```
python -m jsondoctor repair [FILE|-] [--schema PATH] [--out PATH] [--json] [--quiet]
python -m jsondoctor validate [FILE|-] --schema PATH
python -m jsondoctor demo [--json]
python -m jsondoctor --version
```

`repair` exits `0` when the result parsed and validated, `1` when it did not,
and `2` on usage or file errors. `--json` prints a machine-readable object with
`ok`, `repaired`, `actions`, `warnings`, and `data`.

## Safety and limitations

- **No code execution.** The parser never evaluates input; there is no `eval`,
  `exec`, `ast.literal_eval`, or dynamic import.
- **Deterministic.** Same input, same output and same action list; the fast path
  returns already-valid JSON untouched with zero actions.
- **No hidden invention.** Missing required values are reported, not fabricated;
  ambiguous removals are surfaced in `warnings`.
- **Not a JSON parser replacement.** If your provider supports strict structured
  output or a real parser, use that first; this is a repair layer for the cases
  where you cannot.
- **Resource limits are not a security boundary.** Enormous or adversarial inputs
  can be slow; cap input size in untrusted pipelines.
- **Schema subset only.** This is intentionally not a full JSON Schema
  implementation; unsupported keywords are ignored, not silently enforced.

## Relationship to FailBench

This project is the repair half of a pair. Its sibling
**[FailBench](https://github.com/Qin-Z-x/llm-failbench)** contains 100
deterministic, judge-free probes for ten LLM failure classes — including
`structured_output` — plus a cited public evidence atlas and a CI regression
gate. Use FailBench to detect that your endpoint emits malformed structured
output, and `llm-json-doctor` to repair and validate it deterministically. See
FailBench's [mitigation playbook](https://github.com/Qin-Z-x/llm-failbench/blob/main/docs/MITIGATIONS.md)
for the broader picture.

## Similar projects

These are mature, different tools; verify each on its own page and pick what
fits. `llm-json-doctor` is not claiming to be first or best:

- [`json_repair`](https://github.com/mangiucugna/json_repair) — Python (and JS)
  repair library, similar scope; useful when you just need a repaired object.
- [`json5`](https://github.com/dpranke/pyjson5) — strict parser for the JSON5
  superset; parse-only, no diagnostics or schema coercion.
- [`dirty-json`](https://github.com/sonicdoe/dirty-json) — JavaScript tolerant
  parser for dirty JSON-like data.

`llm-json-doctor` focuses on **auditability**: every change is a logged action,
schema invalidity is explained, and coercions are enumerated rather than hidden.

## Development

```shell
python -m unittest discover -s tests -t . -v
python -m jsondoctor demo
```

No third-party dependencies, no network, Python 3.9+. The fixture corpus under
`fixtures/` is synthetic and representative of common LLM output mistakes; see
`fixtures/README.md` for provenance rules.

## Related projects (same author, independent, stdlib-first)

Other tools by the same author covering adjacent LLM failure surfaces. Each is independent: use or fork only the one you need; every README states its own limits.

- [yixin-go](https://github.com/Qin-Z-x/yixin-go) - local-first Windows Go (weiqi/baduk) sparring partner built on KataGo + Human SL.
- [llm-failbench](https://github.com/Qin-Z-x/llm-failbench) - 100 deterministic, judge-free failure probes for LLMs, with a cited evidence atlas and a CI regression gate.
- [llm-invisible-guard](https://github.com/Qin-Z-x/llm-invisible-guard) - detect and sanitize invisible-Unicode prompt injection (zero-width, bidi, Unicode-Tag smuggling).
- [llm-exfil-guard](https://github.com/Qin-Z-x/llm-exfil-guard) - detect data exfiltration through rendered LLM output: image beacons, hidden content, remote loads.
- [slopsquat-guard](https://github.com/Qin-Z-x/slopsquat-guard) - flag hallucinated / typosquatted PyPI and npm dependency names before you install them.
- [regex-redos-guard](https://github.com/Qin-Z-x/regex-redos-guard) - ReDoS (catastrophic backtracking) risk detection for LLM-generated regexes, static + timed probes.

If one of these fits your pipeline, a star/fork on that repo is the only help this project asks for.

## Contributing, security, license

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Report
security issues privately via GitHub's security advisory feature.

MIT licensed. Not affiliated with any model vendor.
