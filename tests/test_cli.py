"""Tests for the jsondoctor command line interface.

The CLI is exercised both as a real subprocess (``python -m jsondoctor``,
the way users run it) and through direct ``main()`` calls (the way the
console script calls it).  No network access is required.
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsondoctor.cli import main

ROOT = Path(__file__).resolve().parents[1]

SCHEMA_TEXT = json.dumps(
    {
        "type": "object",
        "required": ["name", "age"],
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
        },
    }
)

VALID_DOC = '{"name": "Ada", "age": 36}'
INVALID_DOC_MISSING = '{"name": "Ada"}'
INVALID_DOC_TYPE = '{"name": 5, "age": 36}'
MALFORMED_DOC = '{"name": "Ada", "tags": ["math", "code",],}'
VALID_AFTER_REPAIR = {"name": "Ada", "tags": ["math", "code"]}
UNPARSEABLE_DOC = "Just some prose about the weather, no JSON here."


def _clean_env(extra):
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONLEGACYWINDOWSSTDIO", None)
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def run_cli(*args, stdin=None, env_extra=None):
    """Run ``python -m jsondoctor`` from the repository root (text mode)."""
    return subprocess.run(
        [sys.executable, "-m", "jsondoctor", *args],
        cwd=str(ROOT),
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_clean_env(env_extra),
        timeout=180,
    )


def run_cli_raw(*args, stdin=None, env_extra=None):
    """Run ``python -m jsondoctor`` and return raw bytes (encoding checks)."""
    return subprocess.run(
        [sys.executable, "-m", "jsondoctor", *args],
        cwd=str(ROOT),
        input=stdin.encode("utf-8") if isinstance(stdin, str) else stdin,
        capture_output=True,
        env=_clean_env(env_extra),
        timeout=180,
    )


class CliTestCase(unittest.TestCase):
    """Shared helpers: temp workspace + direct main() invocation."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name, text, encoding="utf-8"):
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding=encoding, newline="\n") as fh:
            fh.write(text)
        return str(path)

    def write_schema(self, name="schema.json"):
        return self.write(name, SCHEMA_TEXT)

    def run_main(self, argv, stdin_text=None):
        out, err = io.StringIO(), io.StringIO()
        old_stdin = sys.stdin
        try:
            if stdin_text is not None:
                sys.stdin = io.StringIO(stdin_text)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    code = main(argv)
                except SystemExit as exc:  # argparse --help / --version / usage
                    code = exc.code if isinstance(exc.code, int) else 1
        finally:
            sys.stdin = old_stdin
        return code, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Subprocess-level tests: every command, stdin, files, exit codes
# ---------------------------------------------------------------------------


class TestCliSubprocess(CliTestCase):
    def test_version(self):
        proc = run_cli("--version")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "jsondoctor 0.1.0")

    def test_help_lists_commands(self):
        proc = run_cli("--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = proc.stdout
        self.assertIn("repair", text)
        self.assertIn("validate", text)
        self.assertIn("demo", text)
        self.assertNotIn("Traceback", proc.stderr)

    def test_no_command_is_usage_error(self):
        proc = run_cli()
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", proc.stderr.lower())
        self.assertNotIn("Traceback", proc.stderr)

    def test_unknown_command_is_usage_error(self):
        proc = run_cli("explode")
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    # -- repair ------------------------------------------------------------

    def test_repair_valid_stdin(self):
        proc = run_cli("repair", stdin=VALID_DOC)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), json.loads(VALID_DOC))

    def test_repair_dash_stdin(self):
        proc = run_cli("repair", "-", stdin=VALID_DOC)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), json.loads(VALID_DOC))

    def test_repair_malformed_becomes_valid(self):
        proc = run_cli("repair", stdin=MALFORMED_DOC)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), VALID_AFTER_REPAIR)

    def test_repair_file_argument(self):
        path = self.write("broken.json", MALFORMED_DOC)
        proc = run_cli("repair", path)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), VALID_AFTER_REPAIR)

    def test_repair_unparseable_exits_one(self):
        proc = run_cli("repair", stdin=UNPARSEABLE_DOC)
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")

    def test_repair_out_file(self):
        out_path = self.tmp / "out.json"
        proc = run_cli("repair", "--out", str(out_path), stdin=MALFORMED_DOC)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        written = out_path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(written), VALID_AFTER_REPAIR)
        self.assertFalse(written.startswith("\ufeff"))
        self.assertNotIn("\r\n", written)

    def test_repair_json_report(self):
        proc = run_cli("repair", "--json", stdin=MALFORMED_DOC)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        report = json.loads(proc.stdout)
        self.assertEqual(
            set(report),
            {"ok", "repaired", "actions", "warnings", "data"},
        )
        self.assertIs(report["ok"], True)
        self.assertIs(report["repaired"], True)
        self.assertIsInstance(report["actions"], list)
        self.assertIsInstance(report["warnings"], list)
        self.assertEqual(report["data"], VALID_AFTER_REPAIR)
        trailing = [a for a in report["actions"] if "trailing_comma" in str(a)]
        self.assertTrue(trailing, report["actions"])

    def test_repair_json_report_valid_is_ascii(self):
        proc = run_cli(
            "repair", "--json", stdin=json.dumps({"note": "\u4e2d\u6587 \U0001f600"})
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsInstance(proc.stdout, str)
        proc.stdout.encode("ascii")  # --json machine output must be ASCII-safe
        report = json.loads(proc.stdout)
        self.assertEqual(report["data"]["note"], "\u4e2d\u6587 \U0001f600")

    def test_repair_quiet_suppresses_notes(self):
        proc = run_cli("repair", "--quiet", stdin=MALFORMED_DOC)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stderr, "")
        self.assertEqual(json.loads(proc.stdout), VALID_AFTER_REPAIR)

    def test_repair_schema_coercion(self):
        schema_path = self.write_schema()
        proc = run_cli(
            "repair",
            "--schema",
            schema_path,
            stdin='{"name": "Ada", "age": "36"}',
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"name": "Ada", "age": 36})

    def test_repair_schema_invalid_still_exits_one(self):
        schema_path = self.write_schema()
        proc = run_cli(
            "repair",
            "--schema",
            schema_path,
            "--json",
            stdin=INVALID_DOC_MISSING,
        )
        self.assertEqual(proc.returncode, 1)
        report = json.loads(proc.stdout)
        self.assertIs(report["ok"], False)

    def test_repair_missing_file_is_usage_error(self):
        proc = run_cli("repair", str(self.tmp / "nope.json"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", proc.stderr.lower())
        self.assertNotIn("Traceback", proc.stderr)

    def test_repair_invalid_utf8_file_is_usage_error(self):
        path = self.tmp / "bad-encoding.json"
        path.write_bytes(b'{"a": 1}\xff\xfe')
        proc = run_cli("repair", str(path))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", proc.stderr.lower())
        self.assertNotIn("Traceback", proc.stderr)

    def test_repair_bad_schema_file_is_usage_error(self):
        schema_path = self.write("bad-schema.json", "{not json}")
        proc = run_cli(
            "repair", "--schema", schema_path, stdin=VALID_DOC
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", proc.stderr.lower())
        self.assertNotIn("Traceback", proc.stderr)

    # -- validate ----------------------------------------------------------

    def test_validate_valid_document(self):
        schema_path = self.write_schema()
        proc = run_cli(
            "validate", "--schema", schema_path, stdin=VALID_DOC
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_validate_valid_document_from_file(self):
        schema_path = self.write_schema()
        doc_path = self.write("doc.json", VALID_DOC)
        proc = run_cli("validate", doc_path, "--schema", schema_path)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_validate_missing_required_field(self):
        schema_path = self.write_schema()
        proc = run_cli(
            "validate", "--schema", schema_path, stdin=INVALID_DOC_MISSING
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error", proc.stdout.lower())
        self.assertNotIn("Traceback", proc.stderr)

    def test_validate_wrong_type(self):
        schema_path = self.write_schema()
        proc = run_cli(
            "validate", "--schema", schema_path, stdin=INVALID_DOC_TYPE
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error", proc.stdout.lower())

    def test_validate_invalid_json_input(self):
        schema_path = self.write_schema()
        proc = run_cli(
            "validate", "--schema", schema_path, stdin=MALFORMED_DOC
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("not valid json", proc.stdout.lower())

    def test_validate_requires_schema(self):
        proc = run_cli("validate", stdin=VALID_DOC)
        self.assertEqual(proc.returncode, 2)
        self.assertNotIn("Traceback", proc.stderr)

    def test_validate_missing_file(self):
        schema_path = self.write_schema()
        proc = run_cli(
            "validate", str(self.tmp / "nope.json"), "--schema", schema_path
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", proc.stderr.lower())

    def test_validate_missing_schema_file(self):
        proc = run_cli("validate", "--schema", str(self.tmp / "nope.json"),
                       stdin=VALID_DOC)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", proc.stderr.lower())
        self.assertNotIn("Traceback", proc.stderr)

    # -- demo --------------------------------------------------------------

    def test_demo_human_output(self):
        proc = run_cli("demo")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = proc.stdout.lower()
        self.assertIn("before", text)
        self.assertIn("after", text)
        self.assertIn("actions", text)
        self.assertIn("ok: true", text)

    def test_demo_json(self):
        proc = run_cli("demo", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc.stdout.encode("ascii")
        report = json.loads(proc.stdout)
        self.assertEqual(
            set(report),
            {"ok", "repaired", "actions", "warnings", "data"},
        )
        self.assertIs(report["ok"], True)
        self.assertIs(report["repaired"], True)
        self.assertIsInstance(report["data"], dict)


# ---------------------------------------------------------------------------
# Direct main() tests (console-script entry point, no subprocess)
# ---------------------------------------------------------------------------


class TestDirectMain(CliTestCase):
    def test_main_version_raises_systemexit_zero(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                main(["--version"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), "jsondoctor 0.1.0")

    def test_main_help_raises_systemexit_zero(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as ctx:
                main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("usage", out.getvalue().lower())

    def test_main_repair_stdin(self):
        code, out, err = self.run_main(["repair"], stdin_text=MALFORMED_DOC)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), VALID_AFTER_REPAIR)

    def test_main_repair_json(self):
        code, out, err = self.run_main(["repair", "--json"], stdin_text=MALFORMED_DOC)
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertIs(report["ok"], True)
        self.assertEqual(report["data"], VALID_AFTER_REPAIR)

    def test_main_repair_unparseable(self):
        code, out, err = self.run_main(["repair"], stdin_text=UNPARSEABLE_DOC)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertNotIn("Traceback", err)

    def test_main_repair_missing_file_returns_two(self):
        code, out, err = self.run_main(
            ["repair", str(self.tmp / "missing.json")]
        )
        self.assertEqual(code, 2)
        self.assertIn("error", err.lower())
        self.assertNotIn("Traceback", err)

    def test_main_validate_valid(self):
        schema_path = self.write_schema()
        doc_path = self.write("doc.json", VALID_DOC)
        code, out, err = self.run_main(
            ["validate", doc_path, "--schema", schema_path]
        )
        self.assertEqual(code, 0, out + err)

    def test_main_validate_invalid(self):
        schema_path = self.write_schema()
        doc_path = self.write("doc.json", INVALID_DOC_MISSING)
        code, out, err = self.run_main(
            ["validate", doc_path, "--schema", schema_path]
        )
        self.assertEqual(code, 1)
        self.assertIn("error", out.lower())

    def test_main_demo(self):
        code, out, err = self.run_main(["demo"])
        self.assertEqual(code, 0, err)
        self.assertIn("before", out.lower())
        self.assertIn("after", out.lower())

    def test_main_demo_json(self):
        code, out, err = self.run_main(["demo", "--json"])
        self.assertEqual(code, 0, err)
        self.assertIs(json.loads(out)["ok"], True)


# ---------------------------------------------------------------------------
# Windows cp936 console safety
# ---------------------------------------------------------------------------


class TestConsoleEncodingSafety(CliTestCase):
    PAYLOAD = '{"note": "\u4e2d\u6587 \u2192 \U0001f600 caf\u00e9"}'

    def test_cp936_human_mode_does_not_crash(self):
        input_path = self.write("unicode.json", self.PAYLOAD)
        proc = run_cli_raw(
            "repair",
            input_path,
            env_extra={"PYTHONIOENCODING": "cp936"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(b"Traceback", proc.stderr)
        decoded = proc.stdout.decode("cp936", errors="replace")
        self.assertIn('"note"', decoded)

    def test_cp936_json_mode_is_ascii_safe(self):
        input_path = self.write("unicode.json", self.PAYLOAD)
        proc = run_cli_raw(
            "repair",
            "--json",
            input_path,
            env_extra={"PYTHONIOENCODING": "cp936"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(b"Traceback", proc.stderr)
        report = json.loads(proc.stdout.decode("cp936"))
        self.assertEqual(report["data"]["note"], "\u4e2d\u6587 \u2192 \U0001f600 caf\u00e9")

    def test_cp936_demo_does_not_crash(self):
        proc = run_cli_raw("demo", env_extra={"PYTHONIOENCODING": "cp936"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(b"Traceback", proc.stderr)


# ---------------------------------------------------------------------------
# Packaging / repository hygiene checks (cheap, dependency-free)
# ---------------------------------------------------------------------------


class TestPackaging(CliTestCase):
    def test_pyproject_metadata(self):
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('name = "jsondoctor"', text)
        self.assertIn('version = "0.1.0"', text)
        self.assertIn('requires-python = ">=3.9"', text)
        self.assertIn('jsondoctor = "jsondoctor.cli:main"', text)
        self.assertIn("MIT", text)
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)
        self.assertIn("dependencies = []", text)

    def test_license(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", text)
        self.assertIn("Copyright (c) 2026 llm-json-doctor contributors", text)

    def test_gitattributes(self):
        text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("* text=auto eol=lf", text)

    def test_gitignore(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in ("__pycache__/", "build/", "dist/", ".venv/", "*.log", "_scratch/"):
            self.assertIn(entry, text)
        # Tests and fixtures must stay tracked.
        for tracked in ("tests/", "fixtures/"):
            self.assertNotIn(tracked, text)

    def test_ci_workflow(self):
        text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertRegex(text, r"runs-on: ubuntu-(22\.04|latest)")
        self.assertIn('"3.9"', text)
        self.assertIn('"3.11"', text)
        self.assertIn('"3.13"', text)
        self.assertIn("contents: read", text)
        self.assertIn("python -m unittest discover -s tests", text)
        self.assertIn("python -m jsondoctor demo", text)
        self.assertIn("python -m jsondoctor --version", text)
        self.assertNotIn("pip install", text)

    def test_version_matches_pyproject(self):
        from jsondoctor import cli

        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(cli.VERSION, match.group(1))

    def test_source_files_utf8_no_bom_lf(self):
        for relative in (
            "jsondoctor/cli.py",
            "jsondoctor/__main__.py",
            "tests/test_cli.py",
            "pyproject.toml",
            "LICENSE",
            ".gitignore",
            ".gitattributes",
            ".github/workflows/ci.yml",
        ):
            data = (ROOT / relative).read_bytes()
            self.assertFalse(data.startswith(b"\xef\xbb\xbf"), relative)
            try:
                data.decode("utf-8")
            except UnicodeDecodeError:
                self.fail("{0} is not valid UTF-8".format(relative))


if __name__ == "__main__":
    unittest.main()
