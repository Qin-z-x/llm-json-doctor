# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |

## Reporting a vulnerability

Please report security issues **privately** through GitHub's security advisory
feature:

<https://github.com/Qin-Z-x/llm-json-doctor/security/advisories/new>

Open the "Security" tab of the repository and choose "Report a vulnerability" if
the link above is not available yet (the repository will be public at release).
Do not open a public issue, discussion or pull request for a suspected
vulnerability.

No email address is listed because this project does not maintain one for
security reports; the GitHub advisory channel is the designated private channel.

Include, if you can: the affected version, a minimal input, the observed
behaviour (uncaught exception, hang, memory growth, wrong data), and the Python
version. Please avoid attaching third-party or personal data.

## What is in scope

This project parses untrusted text (typically model output) and returns repaired
data. Security-relevant issues include:

- **Parser safety.** Any path that executes input or escapes the sandbox-free
  design: `eval`/`exec`, dynamic imports, shell or subprocess use, network
  access, or filesystem access from the library (the CLI necessarily reads the
  files you give it). The library must stay pure: standard library only, no
  third-party code.
- **Uncaught exceptions on untrusted input.** `repair()` on a `str` must never
  raise for malformed data; failures must be returned as `ok=False` with a
  warning. A crash or internal error reachable from crafted input is a bug worth
  reporting.
- **Silent data corruption.** A repair that changes data without logging an
  action or warning, or a schema coercion that invents values, is a correctness
  and safety bug. Repairs must be attributable.
- **Dependency or build supply chain.** The project declares no third-party
  runtime dependencies; unexpected imports or packaging changes are in scope.

## What is not a vulnerability

- **Resource exhaustion / denial of service from very large or deeply nested
  input.** There is no input-size cap, timeout or memory limit; work scales with
  input size. Applications must bound the size of text they pass to `repair()`.
  Reports that a huge input is slow or memory-hungry are expected behaviour, not
  a vulnerability (they are a documented known limitation).
- **Semantic correctness of your data.** Repair is syntactic. It cannot know
  that a model meant `42` instead of `41`, and it does not validate business
  rules.
- **Prompt injection or model misuse.** This library never sends prompts and
  makes no model calls; those risks belong to the system that produced the text.
- **Misuse of `additionalProperties: false` as an authorization control.** The
  schema layer constrains shape, not meaning; it is not a security boundary.
- **Vulnerabilities in the application that consumes repaired data.** Validate
  and escape repaired values at the sink as you would any model output.

## Disclosure process

Reports are handled on a best-effort basis by the project contributors. There is
no bug bounty and no response-time guarantee. We will confirm receipt through the
advisory thread, discuss impact and scope, prepare a fix and credit the reporter
in the release notes unless you prefer to stay anonymous. Please allow time for
a release before public disclosure.

## Handling of repaired data

Repair does not make output trustworthy: it makes it parseable. Treat the
returned value as untrusted model output. Check `result.ok`, inspect
`result.actions` and `result.warnings` (lossy repairs are warned), validate the
value against your own schema, and only then pass it to downstream sinks with
normal escaping and authorization checks.
