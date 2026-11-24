# Methodology

How `jsondoctor` repairs, validates and refuses. This document is the normative
description of the pipeline; the executable contract lives in
[`ACTIONS.md`](../ACTIONS.md) (canonical action vocabulary) and in the fixture
corpus under `fixtures/`.

## Determinism contract

`repair(text, schema=None) -> RepairResult` is a pure function: no network, no
filesystem, no clock, no randomness, no locale dependence and no LLM calls. Two
calls with the same arguments produce equal results. The library never executes
input. The only exception it raises is `JsonDoctorError` (a `ValueError`) for
programmer errors such as unusable input objects; malformed JSON and schema
failures are returned as `ok=False`, never raised.

`RepairResult` fields: `data` (Python value or `None`), `ok` (parsed and, if a
schema was supplied, valid), `repaired` (any action was applied), `actions`
(machine-readable list), `warnings` (human-readable ambiguity/loss notices),
`raw` (input text) and `text` (repaired JSON text). `validate_schema(value,
schema)` returns a list of error strings; an empty list means valid.

## Repair pipeline (fixed order)

The order is part of the contract, not an implementation detail: fixtures assert
exact labels and tests fail if the order changes observable results.

1. **Preclean.** Strip a leading UTF-8 BOM (`stripped_bom`), normalize CRLF/CR
   to LF (`normalized_newlines`), remove control characters other than `\n` and
   `\t` (`stripped_control_chars`).
2. **Candidate extraction.** Build ordered candidate strings from the input,
   preferring fenced code blocks and balanced JSON values embedded in prose.
   Removing a fence is logged as `stripped_code_fence`; recovering a value from
   surrounding text logs `extracted_fragment`.
3. **Fast path.** If a candidate already parses as strict JSON (and satisfies a
   supplied schema), return it unchanged: `repaired=False`, `actions=[]`. Valid
   JSON never acquires repair actions.
4. **Local deterministic rewrites.** Applying at most one rewrite per pass, in
   this order, and re-parsing after each pass (bounded to 12 passes):
   `replaced_smart_quote`, `removed_line_comment` / `removed_block_comment`,
   `removed_trailing_comma`, `converted_single_quotes`, `quoted_bare_key`,
   `replaced_python_literal`, `replaced_nan_infinity`, `replaced_undefined`,
   `fixed_number_sign`, `sanitized_escape`.
5. **Truncation recovery (last).** Only when no token/quote rewrite progressed:
   drop the incomplete trailing token/member and close open containers
   (`closed_truncated_json` + warning). If nothing usable remains, close empty
   containers. Trailing-token deletion is lossy and is always warned about.
6. **Parse.** The result must parse with the standard library JSON parser;
   otherwise the candidate is abandoned.
7. **Schema phase.** Validate. If invalid and a schema was supplied, apply the
   schema-guided coercions in the next section, then re-validate. Validation
   errors become warnings prefixed `schema:`.

If every candidate fails, the call returns `ok=False`, `data=None`,
`repaired=False`, `actions=[]`, and a warning beginning `unparseable: `.

## What counts as a repair action

An action is any transformation that changed the input or the parsed value:
text normalization, structural rewrites, truncation recovery, or schema-driven
coercion. Labels are lowercase snake_case; parameterised labels use
`name:key:value` or `name:detail` (for example
`removed_additional_property:role`). The complete vocabulary and its semantics
are defined in [`ACTIONS.md`](../ACTIONS.md). `repaired` is true if and only if
at least one action was recorded. Warnings record ambiguity or information loss
(truncation, duplicate keys with last-wins, dropped additional properties,
NaN/Infinity mapped to null) and never turn a successful result into a failure.

## Schema subset and coercion policy

The v0.1 schema engine implements a deliberately small subset of JSON Schema:
`type` (single string or list; `object`, `array`, `string`, `number`,
`integer`, `boolean`, `null`), `properties`, `required`,
`additionalProperties` (boolean; `false` drops unknown keys), `items`, `enum`,
`minimum` and `maximum`. Keywords outside this list are not enforced. `$ref`,
`allOf`/`anyOf`/`oneOf`, `pattern`, `format`, conditionals and `unevaluated*`
are out of scope; do not rely on this library for full JSON Schema validation.

Coercions run only when a schema is supplied and the parsed value fails
validation. They are a single deterministic pass (object properties first, then
array items), and the result is re-validated:

| Schema expects | Input | Result | Action |
|---|---|---|---|
| `integer` | string `"123"` (optionally signed) | `123` | `coerced_string_to_integer` |
| `number` | numeric string `"1.5"` / `"1e3"` | `1.5` / `1000` | `coerced_string_to_number` |
| `boolean` | string `"true"` / `"false"` (case-insensitive) | `true` / `false` | `coerced_string_to_boolean` |
| `boolean` | number `1` / `0` | `true` / `false` | `coerced_number_to_boolean` |
| `null` | string `"null"` | `null` | `coerced_string_to_null` |
| `array` | any non-array scalar | `[scalar]` | `wrapped_value_in_array` |
| `object` | key not in `properties` and `additionalProperties: false` | key removed | `removed_additional_property:<key>` (+ warning) |

The policy is deliberately narrow: no fuzzy booleans (`"yes"`, `"on"`), no
key-name guessing, no filling of missing required values, no type inference for
unsupported target types. Missing required keys always fail validation. This is
the line between repair and invention.

## Testing and determinism checks

- **Fixture corpus.** 40+ synthetic cases in `fixtures/cases.json`, each
  asserting `expected_ok`, optionally `expected` data, and
  `expected_actions_include`. Fixtures are the primary regression harness for
  the action vocabulary and pipeline order.
- **Unit tests.** `python -m unittest discover -s tests -t . -v` covers the
  public API, the CLI (streams, exit codes, `--json`, `--schema`, `--out`), the
  fast path (valid input must yield no actions), lossy-warning paths, and
  schema validation/coercion.
- **Determinism checks.** Each fixture case is executed through the public API;
  results are compared for exact equality across repeated calls and must contain
  no clock/random/locale-dependent data. No code path may read the environment.
- **Fuzzing policy.** Any mutation/fuzz harness must be seeded and committed,
  must feed arbitrary `str` input (including invalid Unicode escapes and
  pathological nesting), and may only assert invariants: no exception escapes
  `repair()` for `str` input, `repaired` is consistent with `actions`, and
  failures return `ok=False` with an `unparseable:` warning. Fuzzing is a bug
  detector, not a correctness proof.
- **CI.** GitHub Actions runs the suite on Python 3.9, 3.11 and 3.13 plus CLI
  smoke tests (`python -m jsondoctor demo`, `--version`).

## Safety model

Repair operates on strings, uses only local deterministic text rewrites and the
standard library `json` parser, and never calls `eval`/`exec`, `pickle`,
`subprocess`, the filesystem or the network. Parsed values are plain Python
objects (`dict`, `list`, `str`, `int`, `float`, `bool`, `None`). The library does
not import third-party code, so its dependency surface is the standard library.
It does not protect the caller from bad data: repaired values should still be
treated as untrusted model output and validated/escaped at the sink.

## Threat model

Assets: the host application's integrity and availability. Adversary: an
untrusted model (or attacker who can shape model output) supplying arbitrary
text to `repair()`. Goals: (a) data is never executed; (b) parser bugs are
reported rather than hidden; (c) the caller can tell exactly what changed and
what was lost.

- **No code execution.** Input is data. There is no template, import, format or
  command path from input to execution.
- **No network or file access.** The library performs no I/O; the CLI is the
  only component that reads files/stdin and writes stdout/files.
- **Fail closed.** Unrecoverable input yields `ok=False` and no data, never a
  guessed value. Lossy repairs are logged as warnings so a caller can reject
  them.
- **Resource exhaustion is an accepted known limitation, not a security
  boundary.** There is no hard input-size cap, timeout or memory limit. Work is
  proportional to input size (with a bounded 12-pass rewrite loop and bounded
  nesting for candidate scanning), but a very large or deeply nested document
  can consume arbitrary CPU/memory. Applications processing untrusted LLM output
  should enforce their own size and time limits before calling the library. This
  is documented again in [`SECURITY.md`](../SECURITY.md); reports of a
  crash/uncaught exception are welcome, reports that a huge input is slow are
  expected.
- **Schema is not a security control.** A schema constrains shape, not content
  meaning; `additionalProperties: false` is not an authorization check.

## Fixture provenance and ethics

Fixtures are **synthetic-representative**: small, hand-authored documents that
mirror failure patterns reported for structured-output models (fences, prose
wrappers, single quotes, trailing commas, truncation, schema drift, and so on).
They are **not captured model outputs**, contain no PII, secrets or third-party
text, and are not a statistical sample of any model's behaviour. Counts in the
corpus describe test coverage, not failure rates. Every case records a
`provenance` field stating this.

## Adding a case

Add an object to `fixtures/cases.json` with `id`, `title`, `input`, optional
`schema`, `expected_ok`, optional `expected`, `expected_actions_include`,
`tags`, `provenance` and `notes`; use labels only from
[`ACTIONS.md`](../ACTIONS.md); then run the test command above. See
[`CONTRIBUTING.md`](../CONTRIBUTING.md) for the review checklist.
