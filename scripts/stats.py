#!/usr/bin/env python3
"""Print statistics about the synthetic fixture corpus.

Reads ``fixtures/cases.json`` and writes a human-readable summary to stdout.
The script is read-only: it never creates, modifies, or deletes files.

Usage::

    python scripts/stats.py
    python scripts/stats.py --cases fixtures/cases.json

Exit codes: 0 on success, 2 when the fixture file is missing or malformed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

# Repository root is the parent of this script's directory.
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES = ROOT / "fixtures" / "cases.json"

CASE_KEYS = (
    "id",
    "title",
    "input",
    "schema",
    "expected_actions_include",
    "tags",
    "provenance",
    "notes",
)


def load_cases(path: Path) -> list:
    """Load and minimally check the case list."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"error: fixture file not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    try:
        cases = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
        raise SystemExit(2)
    if not isinstance(cases, list):
        print(f"error: {path} must contain a JSON array of cases", file=sys.stderr)
        raise SystemExit(2)
    return cases


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Print statistics for the jsondoctor synthetic fixture corpus."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES,
        help=f"path to cases.json (default: {DEFAULT_CASES})",
    )
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)

    total = len(cases)
    ok_cases = [case for case in cases if case.get("expected_ok", True)]
    fail_cases = [case for case in cases if case.get("expected_ok", True) is False]

    tag_counts = Counter()
    for case in cases:
        tags = case.get("tags")
        if isinstance(tags, list):
            tag_counts.update(tag for tag in tags if isinstance(tag, str))

    provenance_counts = Counter(
        str(case.get("provenance", "<missing>")) for case in cases
    )
    ok_with_data = sum(1 for case in ok_cases if "expected" in case)
    ok_without_data = len(ok_cases) - ok_with_data

    print("jsondoctor synthetic fixture corpus")
    print("=" * 40)
    print(f"file: {args.cases}")
    print(f"cases: {total}")
    print(f"  expected_ok = true:  {len(ok_cases)}")
    print(f"  expected_ok = false: {len(fail_cases)}")
    print(f"  ok cases with expected data:    {ok_with_data}")
    print(f"  ok cases without expected data: {ok_without_data}")
    print()
    print(f"distinct tags: {len(tag_counts)}")
    for tag in sorted(tag_counts):
        print(f"  {tag}: {tag_counts[tag]}")
    print()
    print("provenance:")
    for provenance in sorted(provenance_counts):
        print(f"  {provenance}: {provenance_counts[provenance]}")
    print()

    known_keys = set(CASE_KEYS)
    if cases:
        extra_keys = sorted({key for case in cases for key in case} - known_keys)
        if extra_keys:
            print(f"optional extra case fields: {', '.join(extra_keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
