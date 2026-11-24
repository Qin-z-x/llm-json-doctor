# Comparison with related tools

`llm-json-doctor` is not the only way to deal with malformed JSON, and it is not
the right tool for every job. This page states factual differences so you can
pick the right dependency. It is a comparison, not a ranking: there is no
"first", "best" or "fastest" claim here.

**Method and access date.** Every external URL below was fetched on
**2026-11-24**; the HTTP status observed is recorded in the table. Feature
statements come from each project's own README/documentation as it read on that
date, not from benchmarks. Projects change; check the current docs before
deciding. Entries describe documented behaviour only and are not exhaustive.

## Table

| Project | Language / install | Dependencies | Schema validation | Schema-guided coercion | Repair provenance / warnings | CLI | Maintainer activity evidence (2026-11-24) | When to choose it |
|---|---|---|---|---|---|---|---|---|
| **llm-json-doctor** (this project) — <https://github.com/Qin-Z-x/llm-json-doctor> | Python 3.9+, stdlib only | none (standard library) | small subset: `type`, `properties`, `required`, `additionalProperties`, `items`, `enum`, `minimum`, `maximum` | yes, narrow and logged: numeric strings, boolean strings/0-1, `"null"`, scalar→array, drop unknown properties; never invents missing values | yes: every change is a machine-readable action; lossy/ambiguous repairs also warn | yes (`repair`, `validate`, `demo`) | repository will be public at release; no activity metrics asserted | You want a dependency-free, deterministic repair step that tells you exactly what it changed, with a small schema contract for structured-output shapes, and you are fine with a deliberately narrow schema subset. |
| **json_repair** — <https://github.com/mangiucugna/json_repair> | Python; pip `json-repair` | not asserted here; optional `schema` extra for schema mode | schema-guided repair is documented as beta; not presented as a general JSON Schema validator | yes, documented schema-guided repairs (drops disallowed properties/items, array↔object mapping, fills missing required values from `default`/`const`/first `enum` in safe cases) | no action/warning provenance API documented in the README as read | yes | repository page reachable (HTTP 200); README documents an actively evolving feature set (schema mode beta) — no commit metrics fetched | You want the most featureful Python repair path, schema guidance is welcome, and you do not need per-change provenance or a strict "never invent a field" policy. |
| **jsonrepair** — <https://github.com/josdejong/jsonrepair> | TypeScript/JavaScript; npm `jsonrepair` | npm package | no schema validation documented | no | repair only; no action/warning log documented | yes, plus a streaming API for large documents | repository page reachable (HTTP 200) | Your pipeline is Node.js/TypeScript, or you need the streaming repair API for very large documents. |
| **pyjson5 (json5)** — <https://github.com/dpranke/pyjson5> | Python; `json5` | none | no schema validation | no | no: it is a parser, not a repairer | not asserted here | repository page reachable (HTTP 200) | The input is expected to be valid JSON5 (comments, trailing commas, single quotes, unquoted keys, `NaN`/`Infinity`) and you want a strict JSON5 parser rather than best-effort recovery from arbitrary prose or truncation. |
| **dirty-json** — <https://github.com/sonicdoe/dirty-json> | JavaScript; npm `dirty-json` | npm package | no schema validation documented | no | no documented action/warning log | not asserted here | **not verified:** the canonical GitHub URL failed through the verification proxy on 2026-11-24 (connection closed on the repository page; branch README requests returned HTTP 404), and the GitHub API was rate-limited (HTTP 403); treat availability and details as unverified | Historical option for best-effort parsing of dirty JSON in JavaScript; if you need it today, confirm the package and its docs are available from your registry first. |

## What the differences mean in practice

- **Diagnostic-first vs. repair-only.** This project's differentiator is
  provenance: `repair()` returns `actions` and `warnings`, so a caller can log,
  audit, gate or reject a repair instead of accepting a silently rewritten value.
  The other Python options documented above do not expose a per-change action
  log in their READMEs.
- **Schema policy.** This project validates a small subset and only coerces
  values in documented ways; in particular it refuses to fill in missing
  required fields. `json_repair` documents optional schema-guided repair that
  can fill safe defaults for missing required fields. Choose according to which
  policy you want; neither is universally correct.
- **Overlap is real.** All repair tools handle fences, comments, trailing
  commas, single quotes and truncation to varying degrees. If your only need is
  "turn this broken JSON into an object", the other projects may be simpler
  choices. Use this one when you need deterministic diagnostics, a zero-dependency
  install, or the fixture-backed action contract.
- **Zero dependencies.** Only this project and `pyjson5` are documented here as
  standard-library/no-runtime-dependency Python options; this project is the one
  that repairs malformed input rather than requiring valid JSON5.
- **Complement, don't replace, validators.** None of these tools is a
  substitute for a full JSON Schema validator in a security-sensitive path. This
  project's schema layer is explicitly a small subset.

## Related ecosystem context

If you need full JSON Schema validation, use a dedicated validator (for example
the `jsonschema` package) after repair. If you need to measure how often models
produce malformed structured output in the first place, use the sibling
benchmark [FailBench](https://github.com/Qin-Z-x/llm-failbench), whose
`structured_output` class covers this failure family and whose mitigation
playbook section is the companion reading:
<https://github.com/Qin-Z-x/llm-failbench/blob/main/docs/MITIGATIONS.md>.
