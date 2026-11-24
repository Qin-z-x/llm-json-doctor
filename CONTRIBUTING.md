# Contributing

Thanks for helping. This project is small on purpose: a deterministic repair
engine, a small schema layer, a CLI and a fixture corpus. Changes should keep it
that way.

## Development environment

- Python 3.9 or newer, standard library only. There are no requirements files
  and no runtime or dev dependencies to install.
- Clone the repository and run the commands below from the repository root. The
  package is importable in place (`python -m jsondoctor ...`), no install step is
  required for development.
- CI runs the same suite on Python 3.9, 3.11 and 3.13. Keep syntax compatible
  with the oldest supported version.

## Tests to run before opening a pull request

```shell
python -m unittest discover -s tests -t . -v
python -m jsondoctor demo
python -m jsondoctor --version
```

The first command must pass offline. The other two are cheap smoke checks for
the CLI. To exercise schema validation by hand, pass any JSON document and
schema file of your own: `python -m jsondoctor validate document.json --schema
schema.json`.

## Adding a fixture case

Fixtures live in `fixtures/cases.json` and are the primary regression harness.
Add one JSON object per case with:

| key | required | meaning |
|---|---|---|
| `id` | yes | stable, unique, lowercase-with-dashes identifier |
| `title` | yes | short human description of the defect |
| `input` | yes | the malformed document, exactly as the model might emit it |
| `schema` | no | JSON Schema object used for schema-guided repair |
| `expected_ok` | yes | `true` if a value must be recovered, `false` if repair must fail |
| `expected` | no | exact expected Python value when meaningful |
| `expected_actions_include` | no | labels that must appear in `result.actions` |
| `tags` | no | list of short category tags |
| `provenance` | yes | `synthetic-representative` for hand-authored cases |
| `notes` | no | why the case matters |

Use action labels only from [`ACTIONS.md`](ACTIONS.md). Assertions are about
observable behaviour: prefer `expected_actions_include` over internal details.
Run `python scripts/stats.py` to see corpus counts and tags.

**Provenance rules.** Fixtures must be synthetic and representative: hand-write
small documents that mirror a failure class. Do not paste captured model
outputs, customer data, prompts, secrets, personal data, or third-party text you
do not have the right to redistribute. If a real incident motivates a case,
reduce it to an invented minimal example and say so in `notes`. Cases must not
contain harmful payloads or content that would need moderation.

## Adding or changing a repair rule

1. Open an issue describing the input, the observed result and the expected
   result, or include it in the pull request description.
2. Add the action label to the canonical vocabulary in `ACTIONS.md` and to
   `ACTION_LABELS` in `jsondoctor/repair.py` before wiring it up. Parameterised
   labels use `name:key:value`.
3. Implement the rule as a pure, local, deterministic text transformation. No
   network, no filesystem, no `eval`/`exec`, no third-party imports, no clock or
   randomness. It must run in bounded time and must not loop unboundedly.
4. If the rule can lose information or is ambiguous, append a human-readable
   warning in addition to the action. Never invent a value the input does not
   contain; schema-driven coercions are the only place where values are
   normalised, and they must follow the policy in
   [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).
5. Keep the pipeline order in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) up to
   date, add fixtures for both the success and the failure path, and update the
   relevant table in the README if it lists repair classes.
6. Run the test suite above. A rule without fixtures and a documented action
   label will not be merged.

## Code style

- Standard library only. Do not add runtime dependencies; this is a core
  project promise, not a preference.
- Follow the existing style: type hints on public functions, short docstrings
  that state the contract, small helpers, `snake_case`, focused modules.
- Keep the library free of I/O. File and stream handling belongs in the CLI.
- Errors that are the caller's fault (bad argument types) may raise
  `JsonDoctorError`; malformed *data* must be returned as `ok=False`, never
  raised.
- Documentation is Markdown, UTF-8 without BOM, LF line endings.

## Commits and licensing

- Write clear commit messages that explain the why, not just the what.
- A Developer Certificate of Origin (DCO) sign-off is **not** required; there is
  no CLA either.
- By contributing you agree that your contribution is released under the MIT
  license of this repository (see [`LICENSE`](LICENSE)).
- Keep pull requests focused. One rule, one fixture batch or one documentation
  change per pull request is easier to review.
- Security issues must not be reported in a public issue; see
  [`SECURITY.md`](SECURITY.md).
