# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-11-24

First public release. Deterministic repair and validation for malformed LLM
JSON: Python 3.9+, standard library only, no network, no model calls.

### Added

- `repair(text, schema=None) -> RepairResult` with `data`, `ok`, `repaired`,
  `actions` and `warnings`, plus the `raw` input and repaired `text`.
- Deterministic repair pipeline: BOM/CRLF/control-character cleanup, markdown
  fence unwrapping, JSON extraction from surrounding prose, smart quotes,
  `//`/`/* */` comments, trailing commas, single-quoted strings, bare keys,
  Python literals (`True`/`False`/`None`), `NaN`/`Infinity`/`undefined`,
  leading `+` in numbers, invalid escapes, duplicate keys (last wins) and
  truncation recovery by dropping the incomplete trailing token and closing open
  containers.
- Every change is logged as a machine-readable action; lossy or ambiguous
  repairs also emit human-readable warnings. Canonical vocabulary in
  [`ACTIONS.md`](ACTIONS.md).
- `validate_schema(value, schema)` with a deliberately small JSON Schema subset:
  `type`, `properties`, `required`, `additionalProperties`, `items`, `enum`,
  `minimum`, `maximum`.
- Schema-guided coercions applied only on validation failure: numeric strings
  to integer/number, `"true"`/`"false"` and `1`/`0` to boolean, `"null"` to
  null, scalar to single-item array, and dropping unknown properties when
  `additionalProperties` is `false`. Missing required values are never invented.
- CLI: `python -m jsondoctor repair`, `validate` and `demo`, with `--schema`,
  `--out`, `--json`, `--quiet` and documented exit codes (0 success, 1 repair
  failed or invalid, 2 usage/file error).
- 40+ synthetic fixture cases covering repair classes, failure paths and schema
  coercion, with per-case expected actions.
- Documentation: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) (pipeline, safety
  model, threat model, provenance), [`docs/COMPARISON.md`](docs/COMPARISON.md)
  (honest comparison with related tools), [`CONTRIBUTING.md`](CONTRIBUTING.md),
  [`SECURITY.md`](SECURITY.md) and [`CITATION.cff`](CITATION.cff).
- CI on Python 3.9, 3.11 and 3.13: offline unit tests plus CLI smoke tests.

### Known limitations

- Repair is syntactic and deterministic, not semantic: it cannot recover values
  that were never present and does not guess intent.
- Only the small schema subset above is enforced; it is not a general JSON
  Schema validator.
- Truncation recovery can drop an incomplete trailing member; this is always
  accompanied by a warning.
- No input-size cap or timeout: very large inputs can consume arbitrary
  CPU/memory. Callers must bound input size (see
  [`SECURITY.md`](SECURITY.md)).

[Unreleased]: https://github.com/Qin-Z-x/llm-json-doctor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Qin-Z-x/llm-json-doctor/releases/tag/v0.1.0
