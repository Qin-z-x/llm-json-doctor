# Fixture corpus

`cases.json` is a synthetic, representative corpus of malformed LLM JSON outputs
used to test the repair pipeline deterministically. It is **not** captured model
output, contains no real user data, and carries no PII or secrets.

## Case schema

Each case is one JSON object:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | `case-NNN`, unique, sorted |
| `title` | yes | short description of the failure |
| `input` | yes | the malformed text passed to `repair()` |
| `schema` | no | JSON Schema subset used for validation/coercion, or `null` |
| `expected_ok` | no | defaults to `true`; `false` marks an expected failure |
| `expected` | only for ok cases | exact repaired value (JSON-equal) |
| `expected_actions_include` | yes | action labels that must appear (prefix match allowed) |
| `tags` | yes | at least one filter tag |
| `provenance` | yes | always `synthetic-representative` |
| `notes` | yes | why the case exists / what must not happen |

Cases with `expected_ok: false` must omit `expected` and are expected to return
`ok=False`, `data=None`, `actions=[]`, with a warning explaining the failure
(`unparseable: ...` for unparseable input, `schema: ...` for schema failures).

## Rules for adding a case

1. Use only synthetic or clearly generic content. Never paste real customer data,
   prompts from private systems, credentials, or a captured model transcript.
2. State the expected repaired data exactly; if the repair is ambiguous, add a
   warning expectation in `notes` and discuss it in the PR.
3. Keep the case one failure at a time where possible, so a regression points at
   one rule.
4. Run the suite: `python -m unittest discover -s tests -t . -v`.
5. Action labels must come from `ACTIONS.md`; parameterised labels may be
   asserted by prefix (`deduplicated_key`, `closed_truncated_json`,
   `removed_additional_property`).
6. Seed the file from `fixtures/cases.json`; do not hand-edit counts in
   `scripts/stats.py` (it computes them).

## Coverage

Current corpus: 44 cases covering fences, prose extraction, single/smart quotes,
bare keys, trailing commas (object, array, end-of-input), comments, Python
literals, `NaN`/`Infinity`, truncation, duplicate keys, BOM, JSONL/first-value,
unicode values, deep nesting, schema coercions, additionalProperties removal,
missing required, enum/minimum failures, empty input and prose-only failures.

Provenance link: these failure shapes correspond to the public
`structured_output` evidence collected in the companion
[FailBench atlas](https://github.com/Qin-Z-x/llm-failbench). The atlas links real
public reports of these failures; the fixtures themselves are synthetic.
