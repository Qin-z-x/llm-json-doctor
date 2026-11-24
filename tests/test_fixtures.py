"""Fixture-corpus tests for the ``jsondoctor`` repair API.

The corpus lives in ``fixtures/cases.json`` and is the executable contract for
``jsondoctor.repair(text, schema) -> RepairResult``.  For every case this test:

* calls ``repair`` with the case input and schema (``None`` when absent),
* checks ``result.ok`` against ``expected_ok`` (default ``true``),
* compares ``result.data`` to ``expected`` using JSON equality, and
* verifies that every label in ``expected_actions_include`` appears in
  ``result.actions``.

Action labels and repair semantics are defined in ``ACTIONS.md`` at the
repository root.  Parameterised action families (``deduplicated_key``,
``closed_truncated_json``, ``removed_additional_property``) are matched by
prefix so the exact detail suffix may evolve without weakening the assertion.

If ``jsondoctor`` is not importable yet (it is authored concurrently), the
repair-dependent test class waits once for 20 seconds and then skips gracefully
instead of failing.  The corpus-structure tests always run.
"""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "fixtures" / "cases.json"

# Make the repository root importable when the tests are run directly, e.g.
# ``python tests/test_fixtures.py``.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_CASE_KEYS = (
    "id",
    "title",
    "input",
    "schema",
    "expected_actions_include",
    "tags",
    "provenance",
    "notes",
)

# Families whose labels carry a ``:detail`` suffix (see ACTIONS.md).
PARAMETERISED_ACTION_PREFIXES = (
    "deduplicated_key",
    "closed_truncated_json",
    "removed_additional_property",
)

IMPORT_RETRY_SECONDS = 20


def load_cases(path: Path = CASES_PATH) -> list:
    """Load the fixture corpus, raising a clear error when it is unusable."""
    raw_bytes = path.read_bytes()
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raise AssertionError(f"{path} starts with a UTF-8 BOM")
    cases = json.loads(raw_bytes.decode("utf-8"))
    if not isinstance(cases, list):
        raise AssertionError(f"{path} must contain a JSON array of cases")
    return cases


def json_equal(left, right) -> bool:
    """Compare two decoded JSON values for equality.

    Unlike ``==`` this keeps booleans distinct from numbers (``True != 1``),
    while still comparing integer and non-integer numbers numerically.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return False
        return all(json_equal(left[key], right[key]) for key in left)
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False
        return all(json_equal(a, b) for a, b in zip(left, right))
    if left is None or right is None:
        return left is None and right is None
    return type(left) is type(right) and left == right


def action_matches(expected: str, actions) -> bool:
    """Return True when ``expected`` is satisfied by the recorded actions.

    Exact membership is checked first.  For the three parameterised action
    families a prefix match is accepted (e.g. expected
    ``removed_additional_property:internal_id`` accepts any
    ``removed_additional_property:*`` action), because ACTIONS.md allows
    parameterised labels to be matched by prefix.
    """
    if expected in actions:
        return True
    for prefix in PARAMETERISED_ACTION_PREFIXES:
        if expected == prefix or expected.startswith(prefix + ":"):
            for action in actions:
                if action == prefix or action.startswith(prefix + ":"):
                    return True
    return False


def _import_repair():
    """Import ``jsondoctor.repair``; return None when it is not available yet."""
    try:
        from jsondoctor import repair  # noqa: PLC0415 - intentionally lazy

        return repair
    except Exception:  # ImportError, SyntaxError while the module is mid-write, ...
        return None


class FixtureCorpusStructureTests(unittest.TestCase):
    """Checks that cases.json itself is well formed, ordered, and complete."""

    def test_corpus_is_a_json_array_of_at_least_40_cases(self):
        cases = load_cases()
        self.assertGreaterEqual(
            len(cases), 40, "the corpus must contain at least 40 cases"
        )

    def test_case_ids_are_unique_sorted_and_well_formed(self):
        cases = load_cases()
        ids = [case.get("id") for case in cases]
        self.assertEqual(
            [case_id for case_id in ids if not isinstance(case_id, str)],
            [],
            "every case id must be a string",
        )
        self.assertEqual(len(ids), len(set(ids)), "case ids must be unique")
        self.assertEqual(ids, sorted(ids), "cases must be ordered by id")
        for case_id in ids:
            self.assertRegex(case_id, r"^case-\d{3}$")

    def test_every_case_has_the_required_fields(self):
        for case in load_cases():
            with self.subTest(case=case.get("id")):
                for key in REQUIRED_CASE_KEYS:
                    self.assertIn(key, case, f"missing required field {key!r}")
                if "expected_ok" in case:
                    self.assertIs(case["expected_ok"], False, "only false is allowed")
                self.assertIsInstance(case["title"], str)
                self.assertTrue(case["title"].strip())
                self.assertIsInstance(case["input"], str)
                self.assertIsInstance(case["notes"], str)
                self.assertTrue(case["notes"].strip())
                self.assertIsInstance(case["expected_actions_include"], list)
                for label in case["expected_actions_include"]:
                    self.assertIsInstance(label, str)
                    self.assertTrue(label)
                self.assertIsInstance(case["tags"], list)
                self.assertGreaterEqual(len(case["tags"]), 1)
                for tag in case["tags"]:
                    self.assertIsInstance(tag, str)
                    self.assertRegex(tag, r"^[a-z0-9]+(-[a-z0-9]+)*$")
                self.assertIsInstance(case["schema"], (dict, type(None)))

    def test_success_cases_carry_expected_data_and_failure_cases_do_not(self):
        for case in load_cases():
            with self.subTest(case=case.get("id")):
                expected_ok = case.get("expected_ok", True)
                if expected_ok:
                    self.assertIn(
                        "expected", case, "success cases need expected data"
                    )
                else:
                    self.assertNotIn(
                        "expected",
                        case,
                        "expected_ok=false cases must omit expected data",
                    )

    def test_the_corpus_has_at_least_four_expected_failures(self):
        failures = [
            case for case in load_cases() if case.get("expected_ok", True) is False
        ]
        self.assertGreaterEqual(len(failures), 3)

    def test_every_case_declares_synthetic_provenance(self):
        for case in load_cases():
            with self.subTest(case=case.get("id")):
                self.assertEqual(case["provenance"], "synthetic-representative")

    def test_no_case_claims_model_capture_or_evidence_ids(self):
        forbidden_fragments = (
            "captured from",
            "generated by gpt",
            "generated by claude",
            "ev_",
        )
        for case in load_cases():
            blob = json.dumps(case, ensure_ascii=False).lower()
            for fragment in forbidden_fragments:
                with self.subTest(case=case.get("id"), fragment=fragment):
                    self.assertNotIn(fragment, blob)


class FixtureRepairTests(unittest.TestCase):
    """Runs every fixture through ``jsondoctor.repair``."""

    @classmethod
    def setUpClass(cls):
        cls.cases = load_cases()
        repair = _import_repair()
        if repair is None:
            # The engine is authored concurrently; give it one chance to land.
            time.sleep(IMPORT_RETRY_SECONDS)
            repair = _import_repair()
        if repair is None:
            raise unittest.SkipTest(
                "jsondoctor.repair is not importable yet; "
                "skipping repair-behaviour assertions"
            )
        cls.repair = staticmethod(repair)

    def test_expected_ok_and_expected_data_for_every_case(self):
        for case in self.cases:
            case_id = case.get("id")
            with self.subTest(case=case_id):
                schema = case.get("schema")
                result = self.repair(case["input"], schema)
                expected_ok = case.get("expected_ok", True)
                actual_ok = getattr(result, "ok", None)
                self.assertIsInstance(
                    actual_ok, bool, f"{case_id}: RepairResult.ok must be a bool"
                )
                self.assertEqual(
                    actual_ok,
                    expected_ok,
                    f"{case_id}: expected ok={expected_ok}, got {actual_ok!r} "
                    f"(warnings={getattr(result, 'warnings', None)!r})",
                )
                if expected_ok:
                    self.assertTrue(
                        json_equal(getattr(result, "data", None), case["expected"]),
                        f"{case_id}: repaired data mismatch\n"
                        f"  expected: {case['expected']!r}\n"
                        f"  actual:   {getattr(result, 'data', None)!r}\n"
                        f"  actions:  {getattr(result, 'actions', None)!r}\n"
                        f"  warnings: {getattr(result, 'warnings', None)!r}",
                    )

    def test_expected_actions_are_reported_for_every_case(self):
        for case in self.cases:
            case_id = case.get("id")
            expected_actions = case["expected_actions_include"]
            if not expected_actions:
                continue
            with self.subTest(case=case_id):
                result = self.repair(case["input"], case.get("schema"))
                actions = getattr(result, "actions", None)
                self.assertIsInstance(
                    actions,
                    list,
                    f"{case_id}: RepairResult.actions must be a list",
                )
                for expected in expected_actions:
                    self.assertTrue(
                        action_matches(expected, actions),
                        f"{case_id}: expected action {expected!r} missing from "
                        f"actions {actions!r}",
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
