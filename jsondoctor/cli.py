"""Command line interface for :mod:`jsondoctor`.

Commands
--------
``repair``    repair a malformed JSON document (stdin or file)
``validate``  validate a JSON document against a schema file
``demo``      run a small built-in malformed sample and show the repair

The CLI is intentionally dependency free (standard library only), Python
3.9+, and safe to run on consoles whose encoding cannot represent every
Unicode character (for example Windows cp936): output streams are switched
to ``errors="replace"`` and ``--json`` output is ASCII escaped.
"""

import argparse
import dataclasses
import json
import sys

from . import repair as _repair
from . import validate_schema as _validate_schema

__all__ = ["main", "build_parser", "VERSION"]

PROG = "jsondoctor"
VERSION = "0.1.0"

#: Small deterministic malformed sample used by the ``demo`` command.
DEMO_INPUT = '{"name": "Ada", "tags": ["math", "code",], "active": true,}'


class CliError(Exception):
    """An ordinary usage/input/file error reported as one line, exit code 2."""


# ---------------------------------------------------------------------------
# Console safety helpers
# ---------------------------------------------------------------------------


def _configure_stdio():
    """Make stdout/stderr tolerant of characters the console cannot encode."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (AttributeError, OSError, ValueError):
            # Exotic replacement stream (e.g. StringIO in tests): nothing to do.
            pass


def _write_stdout(text):
    stream = sys.stdout
    if stream is None:
        raise CliError("stdout is not available")
    _write_stream(stream, text)


def _write_stderr(text):
    stream = sys.stderr
    if stream is None:
        return
    _write_stream(stream, text)


def _write_stream(stream, text):
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        safe = text.encode(encoding, "replace").decode(encoding, "replace")
        stream.write(safe)
    try:
        stream.flush()
    except (AttributeError, OSError, ValueError):
        pass


def _error(message):
    _write_stderr("{0}: error: {1}\n".format(PROG, message))


def _notice(message):
    _write_stderr("{0}: {1}\n".format(PROG, message))


# ---------------------------------------------------------------------------
# Small serialization / formatting helpers
# ---------------------------------------------------------------------------


def _jsonable(value, depth=0):
    """Best-effort conversion of arbitrary engine values to JSON-safe data."""
    if depth > 32:
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item, depth + 1) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item, depth + 1) for item in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value), depth + 1)
    fields = getattr(value, "__dict__", None)
    if isinstance(fields, dict):
        return {
            str(key): _jsonable(item, depth + 1)
            for key, item in fields.items()
            if not str(key).startswith("_")
        }
    return str(value)


def _dumps(value, ensure_ascii):
    return json.dumps(
        _jsonable(value),
        ensure_ascii=ensure_ascii,
        separators=(",", ":"),
    )


def _format_item(item):
    """Render one action/warning/error as a single line."""
    if isinstance(item, str):
        return " ".join(item.split())
    if isinstance(item, dict):
        message = item.get("message") or item.get("detail") or item.get("action")
        path = item.get("path") or item.get("pointer")
        if message is not None:
            text = " ".join(str(message).split())
            if path:
                return "{0}: {1}".format(path, text)
            return text
    return " ".join(_dumps(item, ensure_ascii=False).split())


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        return [value] if value else []
    return [value]


# ---------------------------------------------------------------------------
# Input / output helpers
# ---------------------------------------------------------------------------


def _quoted(path):
    return "'{0}'".format(path)


def _read_stdin():
    stream = sys.stdin
    if stream is None:
        raise CliError("no input file given and stdin is not available")
    try:
        return stream.read()
    except UnicodeDecodeError:
        raise CliError("cannot read stdin: input is not valid text")
    except OSError as exc:
        raise CliError("cannot read stdin: {0}".format(exc.strerror or exc))


def _read_text_file(path, kind):
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return handle.read()
    except FileNotFoundError:
        raise CliError("cannot read {0} {1}: file not found".format(kind, _quoted(path)))
    except IsADirectoryError:
        raise CliError("cannot read {0} {1}: is a directory".format(kind, _quoted(path)))
    except PermissionError:
        raise CliError(
            "cannot read {0} {1}: permission denied".format(kind, _quoted(path))
        )
    except UnicodeDecodeError:
        raise CliError(
            "cannot read {0} {1}: file is not valid UTF-8 text".format(
                kind, _quoted(path)
            )
        )
    except OSError as exc:
        raise CliError(
            "cannot read {0} {1}: {2}".format(kind, _quoted(path), exc.strerror or exc)
        )


def _read_input(path):
    if path is None or path == "-":
        return _read_stdin()
    return _read_text_file(path, "input")


def _read_schema(path):
    if path is None or path == "-":
        return _read_stdin()
    text = _read_text_file(path, "schema file")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(
            "schema file {0} is not valid JSON: {1}".format(_quoted(path), exc)
        )


def _write_output_file(path, text):
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
    except OSError as exc:
        raise CliError(
            "cannot write output {0}: {1}".format(_quoted(path), exc.strerror or exc)
        )


# ---------------------------------------------------------------------------
# Engine adapters (kept in one place so the CLI only touches the public API)
# ---------------------------------------------------------------------------


def _field(result, name, default=None):
    if isinstance(result, dict):
        return result.get(name, default)
    return getattr(result, name, default)


def _run_repair(text, schema):
    result = _repair(text, schema)
    data = _field(result, "data")
    actions = _as_list(_field(result, "actions"))
    warnings = _as_list(_field(result, "warnings"))
    ok = _field(result, "ok")
    if ok is None:
        ok = data is not None
    ok = bool(ok)
    repaired = _field(result, "repaired")
    if repaired is None:
        repaired = bool(actions)
    return data, ok, bool(repaired), actions, warnings


def _validation_errors(data, schema):
    try:
        outcome = _validate_schema(data, schema)
    except CliError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface engine validation errors
        return _errors_from_outcome(exc)
    return _errors_from_outcome(outcome)


def _errors_from_outcome(outcome):
    if outcome is None:
        return []
    if isinstance(outcome, bool):
        return [] if outcome else ["document does not satisfy the schema"]
    if isinstance(outcome, str):
        return [outcome] if outcome.strip() else []
    if isinstance(outcome, dict):
        for key in ("errors", "messages", "problems"):
            if key in outcome:
                return _error_lines(outcome[key]) or ["document does not satisfy the schema"]
        for key in ("valid", "ok"):
            if key in outcome:
                if outcome[key]:
                    return []
                return _error_lines(outcome.get("message") or outcome) or [
                    "document does not satisfy the schema"
                ]
        return (
            _error_lines(outcome)
            if outcome
            else []
        )
    errors = getattr(outcome, "errors", None)
    if errors is not None:
        return _error_lines(errors)
    ok = getattr(outcome, "ok", None)
    if ok is not None:
        if ok:
            return []
        errors = getattr(outcome, "messages", None) or getattr(outcome, "errors", None)
        return _error_lines(errors) or ["document does not satisfy the schema"]
    if isinstance(outcome, (list, tuple)):
        return _error_lines(outcome)
    return _error_lines(outcome)


def _error_lines(errors):
    return [_format_item(item) for item in _as_list(errors) if _format_item(item)]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _machine_report(data, ok, repaired, actions, warnings):
    report = {
        "ok": ok,
        "repaired": repaired,
        "actions": _jsonable(actions),
        "warnings": _jsonable(warnings),
        "data": _jsonable(data),
    }
    return _dumps(report, ensure_ascii=True)


def _cmd_repair(args):
    text = _read_input(args.file)
    schema = _read_schema(args.schema) if args.schema is not None else None
    data, ok, repaired, actions, warnings = _run_repair(text, schema)

    repaired_text = None
    if data is not None:
        repaired_text = _dumps(data, ensure_ascii=False)

    wrote_output = False
    if args.out is not None and repaired_text is not None:
        _write_output_file(args.out, repaired_text)
        wrote_output = True

    if args.json_output:
        _write_stdout(_machine_report(data, ok, repaired, actions, warnings) + "\n")
    elif repaired_text is not None and args.out is None:
        _write_stdout(repaired_text + "\n")

    quiet = args.quiet or args.json_output
    if not quiet:
        if wrote_output:
            _notice("wrote {0}".format(_quoted(args.out)))
        for warning in warnings:
            line = _format_item(warning)
            if line:
                _notice("warning: {0}".format(line))
        for action in actions:
            line = _format_item(action)
            if line:
                _notice("action: {0}".format(line))
        if not ok and repaired_text is None:
            _notice("could not repair input: no JSON value was recovered")
        elif not ok:
            _notice("result is not valid for the supplied schema")

    return 0 if ok else 1


def _cmd_validate(args):
    text = _read_input(args.file)
    schema = _read_schema(args.schema)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        _write_stdout("error: input is not valid JSON: {0}\n".format(exc))
        return 1
    errors = _validation_errors(data, schema)
    if errors:
        for line in errors:
            _write_stdout("error: {0}\n".format(line))
        return 1
    return 0


def _cmd_demo(args):
    data, ok, repaired, actions, warnings = _run_repair(DEMO_INPUT, None)
    after = _dumps(data, ensure_ascii=False) if data is not None else None

    if args.json_output:
        _write_stdout(_machine_report(data, ok, repaired, actions, warnings) + "\n")
        return 0 if ok else 1

    lines = [
        "jsondoctor demo: repair a small malformed JSON sample",
        "",
        "before:",
        DEMO_INPUT,
        "",
        "after:",
        after if after is not None else "(not repaired)",
    ]
    if actions:
        lines.append("")
        lines.append("actions:")
        for action in actions:
            line = _format_item(action)
            if line:
                lines.append("  - {0}".format(line))
    if warnings:
        lines.append("")
        lines.append("warnings:")
        for warning in warnings:
            line = _format_item(warning)
            if line:
                lines.append("  - {0}".format(line))
    lines.append("")
    lines.append(
        "ok: {0}  repaired: {1}".format(str(ok).lower(), str(repaired).lower())
    )
    _write_stdout("\n".join(lines) + "\n")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Argument parser / entry point
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Deterministic repair and validation for malformed LLM JSON.",
        epilog=(
            "exit codes: 0 = success/valid, 1 = repair failed or validation "
            "errors, 2 = usage or file error.\n"
            "examples: jsondoctor repair broken.json --json; "
            "jsondoctor validate data.json --schema schema.json; "
            "jsondoctor demo"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version="{0} {1}".format(PROG, VERSION)
    )
    subparsers = parser.add_subparsers(
        dest="command", metavar="{repair,validate,demo}", required=True
    )

    repair_parser = subparsers.add_parser(
        "repair",
        help="repair a malformed JSON document",
        description=(
            "Read a document, repair it, and write compact JSON. "
            "Exit 0 when the result is ok, 1 otherwise."
        ),
    )
    repair_parser.add_argument(
        "file",
        nargs="?",
        default="-",
        metavar="FILE",
        help="input file; use '-' or omit it to read stdin (default: stdin)",
    )
    repair_parser.add_argument(
        "--schema",
        metavar="PATH",
        default=None,
        help="JSON Schema file used to check/guide the repaired result",
    )
    repair_parser.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="write the repaired compact JSON to PATH instead of stdout",
    )
    repair_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="print an ASCII-safe machine report: ok, repaired, actions, warnings, data",
    )
    repair_parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress warning and action notes on stderr",
    )
    repair_parser.set_defaults(func=_cmd_repair)

    validate_parser = subparsers.add_parser(
        "validate",
        help="validate a JSON document against a schema file",
        description=(
            "Validate a JSON document against a schema and print every "
            "validation error. Exit 0 when valid, 1 otherwise."
        ),
    )
    validate_parser.add_argument(
        "file",
        nargs="?",
        default="-",
        metavar="FILE",
        help="input file; use '-' or omit it to read stdin (default: stdin)",
    )
    validate_parser.add_argument(
        "--schema",
        metavar="PATH",
        required=True,
        help="JSON Schema file to validate against (required)",
    )
    validate_parser.set_defaults(func=_cmd_validate)

    demo_parser = subparsers.add_parser(
        "demo",
        help="run a small built-in malformed sample",
        description=(
            "Repair a small built-in malformed JSON sample and print the "
            "before/after document plus the actions taken. Needs no files."
        ),
    )
    demo_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="print the demo result as one ASCII-safe JSON report",
    )
    demo_parser.set_defaults(func=_cmd_demo)

    return parser


def main(argv=None):
    """Run the CLI and return a process exit code."""
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CliError as exc:
        _error(str(exc))
        return 2
    except BrokenPipeError:
        return 1
    except OSError as exc:
        _error(exc.strerror or str(exc))
        return 2
