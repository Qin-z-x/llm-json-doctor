"""Unit tests for the ``jsondoctor`` repair engine and schema support.

The executable contract for actions and semantics lives in ``ACTIONS.md`` at
the repository root.  These tests are deliberately organised by repair stage
so a failure points at one part of the pipeline:

* fast path / result contract,
* preprocessing (BOM, newlines, control characters),
* extraction (fences, prose, multiple values),
* quote repairs (smart quotes, single-quoted strings),
* punctuation / bare keys / literals,
* truncation recovery,
* duplicate keys,
* schema validation and schema-guided coercions,
* robustness (large input, determinism, idempotence).

No external services, files, or third-party packages are used.
"""

from __future__ import annotations

import json
import time
import unittest

from jsondoctor import (
    ACTION_LABELS,
    JsonDoctorError,
    RepairResult,
    __version__,
    extract_json,
    repair,
    validate_schema,
)

FENCE_LABELS = ("stripped_code_fence", "extracted_fragment")


def action_matches(action: str, label: str) -> bool:
    """True when ``action`` is exactly ``label`` or ``label:<detail>``."""
    return action == label or action.startswith(label + ":")


class ResultContractTests(unittest.TestCase):
    """Shape of RepairResult and the public package surface."""

    def test_version_is_0_1_0(self):
        self.assertEqual(__version__, "0.1.0")

    def test_repair_result_is_dataclass_with_contract_fields(self):
        fields = RepairResult.__dataclass_fields__
        self.assertEqual(
            list(fields),
            ["data", "ok", "repaired", "actions", "warnings", "raw", "text"],
        )
        empty = RepairResult()
        self.assertIsNone(empty.data)
        self.assertFalse(empty.ok)
        self.assertFalse(empty.repaired)
        self.assertEqual(empty.actions, [])
        self.assertEqual(empty.warnings, [])
        self.assertEqual(empty.raw, "")
        self.assertEqual(empty.text, "")

    def test_action_labels_is_tuple_of_strings(self):
        self.assertIsInstance(ACTION_LABELS, tuple)
        self.assertTrue(ACTION_LABELS)
        for label in ACTION_LABELS:
            self.assertIsInstance(label, str)
            self.assertTrue(label.strip())
            self.assertEqual(label, label.lower())
        for required in (
            "stripped_bom",
            "normalized_newlines",
            "stripped_control_chars",
            "stripped_code_fence",
            "extracted_fragment",
            "replaced_smart_quote",
            "converted_single_quotes",
            "quoted_bare_key",
            "removed_line_comment",
            "removed_block_comment",
            "removed_trailing_comma",
            "replaced_python_literal",
            "replaced_nan_infinity",
            "fixed_number_sign",
            "sanitized_escape",
            "deduplicated_key",
            "closed_truncated_json",
            "replaced_undefined",
            "coerced_string_to_integer",
            "coerced_string_to_number",
            "coerced_string_to_boolean",
            "coerced_number_to_boolean",
            "coerced_string_to_null",
            "wrapped_value_in_array",
            "removed_additional_property",
        ):
            self.assertIn(required, ACTION_LABELS)

    def test_json_doctor_error_is_value_error(self):
        self.assertTrue(issubclass(JsonDoctorError, ValueError))

    def test_every_emitted_action_uses_canonical_vocabulary(self):
        samples = [
            '\ufeff```json\n{"a": 1, "b": [1,],}\n```',
            "{'a': True, 'b': 'x', 'c': None}",
            '{"a": NaN, "b": undefined}',
            '{a: +12, b: "x" /* c */}',
            '{"a": 1, "b": [',
            '{"a": 1, "a": 2}',
            '{"x": "\\x41"}',
        ]
        for sample in samples:
            result = repair(sample)
            for action in result.actions:
                self.assertIsInstance(action, str)
                self.assertTrue(
                    any(action_matches(action, label) for label in ACTION_LABELS),
                    "action {0!r} not in ACTION_LABELS".format(action),
                )

    def test_result_fields_have_expected_types(self):
        result = repair('{"a": 1,}')
        self.assertIsInstance(result, RepairResult)
        self.assertIsInstance(result.raw, str)
        self.assertIsInstance(result.text, str)
        self.assertIsInstance(result.actions, list)
        self.assertIsInstance(result.warnings, list)
        self.assertIsInstance(result.ok, bool)
        self.assertIsInstance(result.repaired, bool)
        self.assertTrue(all(isinstance(item, str) for item in result.actions))
        self.assertTrue(all(isinstance(item, str) for item in result.warnings))


class FastPathTests(unittest.TestCase):
    """Valid JSON must be returned untouched with no actions."""

    def test_clean_object_is_not_repaired(self):
        text = '{"a": 1, "b": [true, null], "c": {"d": "e"}}'
        result = repair(text)
        self.assertTrue(result.ok)
        self.assertFalse(result.repaired)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.data, {"a": 1, "b": [True, None], "c": {"d": "e"}})
        self.assertEqual(result.raw, text)
        self.assertEqual(result.text, text)

    def test_clean_top_level_array_is_not_repaired(self):
        result = repair('[1, 2, 3, {"k": "v"}]')
        self.assertTrue(result.ok)
        self.assertFalse(result.repaired)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.data, [1, 2, 3, {"k": "v"}])

    def test_top_level_scalars_parse_without_repairs(self):
        for text, expected in (
            ("true", True),
            ("false", False),
            ("null", None),
            ("42", 42),
            ("-3.5", -3.5),
            ('"hello"', "hello"),
        ):
            with self.subTest(text=text):
                result = repair(text)
                self.assertTrue(result.ok)
                self.assertFalse(result.repaired)
                self.assertEqual(result.actions, [])
                self.assertEqual(result.data, expected)

    def test_surrounding_whitespace_is_not_a_repair(self):
        text = '  \n\t{"a": 1}\n\n  '
        result = repair(text)
        self.assertTrue(result.ok)
        self.assertFalse(result.repaired)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.data, {"a": 1})
        self.assertEqual(result.raw, text)

    def test_fast_path_works_identically_twice(self):
        first = repair('{"a": [1, 2, 3]}')
        second = repair('{"a": [1, 2, 3]}')
        self.assertEqual(first.ok, second.ok)
        self.assertEqual(first.data, second.data)
        self.assertEqual(first.actions, second.actions)
        self.assertEqual(first.warnings, second.warnings)

    def test_unicode_is_preserved(self):
        text = '{"nom": "café", "名前": "太郎", "emoji": "✓"}'
        result = repair(text)
        self.assertTrue(result.ok)
        self.assertFalse(result.repaired)
        self.assertEqual(result.data["nom"], "café")
        self.assertEqual(result.data["名前"], "太郎")

    def test_deeply_nested_valid_json_parses(self):
        text = "[" * 60 + "]" * 60
        result = repair(text)
        self.assertTrue(result.ok)
        self.assertFalse(result.repaired)
        self.assertEqual(result.data, json.loads(text))


class FailureTests(unittest.TestCase):
    """Unparseable input is reported, never raised, and never marked repaired."""

    def test_empty_input(self):
        result = repair("")
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertFalse(result.repaired)
        self.assertEqual(result.actions, [])
        self.assertTrue(result.warnings)
        self.assertTrue(result.warnings[0].startswith("unparseable:"))
        self.assertEqual(result.raw, "")
        self.assertEqual(result.text, "")

    def test_whitespace_only_input(self):
        result = repair("   \n\t  ")
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertEqual(result.actions, [])
        self.assertTrue(result.warnings[0].startswith("unparseable:"))

    def test_prose_without_json(self):
        result = repair("Sure, here is some text but no JSON at all.")
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertFalse(result.repaired)
        self.assertEqual(result.actions, [])
        self.assertTrue(result.warnings[0].startswith("unparseable:"))

    def test_failure_preserves_raw_input(self):
        text = "not json at all"
        result = repair(text)
        self.assertFalse(result.ok)
        self.assertEqual(result.raw, text)
        self.assertEqual(result.text, "")

    def test_unparseable_huge_garbage_returns_result(self):
        result = repair("[" * 5 + "garbage" + "]" * 2)
        self.assertIsInstance(result, RepairResult)
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)

    def test_extract_json_failure_returns_error_string(self):
        value, error, actions = extract_json("no json here")
        self.assertIsNone(value)
        self.assertIsInstance(error, str)
        self.assertTrue(error.startswith("unparseable:"))
        self.assertEqual(actions, [])


class PreprocessingTests(unittest.TestCase):
    """BOM, newline normalisation and control-character stripping."""

    def test_bom_is_stripped_and_logged(self):
        result = repair('\ufeff{"a": 1}')
        self.assertTrue(result.ok)
        self.assertTrue(result.repaired)
        self.assertIn("stripped_bom", result.actions)
        self.assertEqual(result.data, {"a": 1})
        self.assertTrue(result.raw.startswith("\ufeff"))

    def test_crlf_is_normalized_and_logged(self):
        result = repair('{\r\n  "a": 1\r\n}')
        self.assertTrue(result.ok)
        self.assertIn("normalized_newlines", result.actions)
        self.assertEqual(result.data, {"a": 1})

    def test_lone_cr_is_normalized(self):
        result = repair('{"a":\r1}')
        self.assertTrue(result.ok)
        self.assertIn("normalized_newlines", result.actions)
        self.assertEqual(result.data, {"a": 1})

    def test_bom_and_crlf_together(self):
        result = repair('\ufeff{"a": 1}\r\n')
        self.assertTrue(result.ok)
        self.assertIn("stripped_bom", result.actions)
        self.assertIn("normalized_newlines", result.actions)
        self.assertEqual(result.data, {"a": 1})

    def test_control_characters_outside_strings_are_stripped(self):
        result = repair('{"a":\u0001 1}')
        self.assertTrue(result.ok)
        self.assertIn("stripped_control_chars", result.actions)
        self.assertEqual(result.data, {"a": 1})

    def test_control_characters_inside_strings_are_stripped(self):
        result = repair('{"text": "he\u0001llo"}')
        self.assertTrue(result.ok)
        self.assertIn("stripped_control_chars", result.actions)
        self.assertEqual(result.data, {"text": "hello"})


class ExtractionTests(unittest.TestCase):
    """Finding JSON inside fences and prose."""

    def test_fenced_json_is_extracted(self):
        result = repair('```json\n{"a": 1}\n```')
        self.assertTrue(result.ok)
        self.assertFalse(result.repaired is False)  # extraction is an action
        self.assertEqual(result.data, {"a": 1})
        self.assertTrue(any(label in result.actions for label in FENCE_LABELS))
        self.assertEqual(result.text, '{"a": 1}')

    def test_fence_with_language_tag(self):
        result = repair('```JSON\n[1, 2, 3]\n```')
        self.assertTrue(result.ok)
        self.assertEqual(result.data, [1, 2, 3])
        self.assertTrue(any(label in result.actions for label in FENCE_LABELS))

    def test_fenced_json_with_prose_around_it(self):
        text = 'Sure! Here you go:\n```json\n{"a": 1}\n```\nEnjoy.'
        result = repair(text)
        self.assertTrue(result.ok)
        self.assertTrue(result.repaired)
        self.assertEqual(result.data, {"a": 1})
        self.assertIn("stripped_code_fence", result.actions)
        self.assertEqual(result.text, '{"a": 1}')

    def test_fenced_malformed_json_is_repaired(self):
        text = 'Here is the JSON:\n```json\n{"a": 1,}\n```'
        result = repair(text)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": 1})
        self.assertIn("stripped_code_fence", result.actions)
        self.assertIn("removed_trailing_comma", result.actions)

    def test_json_extracted_from_prose(self):
        result = repair('The answer is {"a": 1, "b": [2, 3]} as requested.')
        self.assertTrue(result.ok)
        self.assertTrue(result.repaired)
        self.assertIn("extracted_fragment", result.actions)
        self.assertEqual(result.data, {"a": 1, "b": [2, 3]})

    def test_multiple_values_first_fence_wins(self):
        text = '```json\n{"a": 1}\n```\nthen\n```json\n{"b": 2}\n```'
        result = repair(text)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": 1})

    def test_two_objects_in_prose_first_wins(self):
        text = 'Example: {"name": "Ada"}. Final: {"name": "Bob"}.'
        result = repair(text)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"name": "Ada"})

    def test_concatenated_objects_first_wins(self):
        result = repair('{"a": 1}{"b": 2}')
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": 1})
        self.assertIn("extracted_fragment", result.actions)

    def test_json_lines_first_value_wins(self):
        result = repair('{"a": 1}\n{"b": 2}\n')
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": 1})

    def test_trailing_prose_after_json_is_ignored(self):
        result = repair('{"a": 1} done!')
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": 1})


class QuoteRepairTests(unittest.TestCase):
    """Smart quotes and single-quoted strings."""

    def test_smart_double_quotes(self):
        result = repair("{\u201ca\u201d: \u201cb\u201d}")
        self.assertTrue(result.ok)
        self.assertIn("replaced_smart_quote", result.actions)
        self.assertEqual(result.data, {"a": "b"})

    def test_smart_single_quotes(self):
        result = repair("{\u2018a\u2019: \u2018b\u2019}")
        self.assertTrue(result.ok)
        self.assertIn("replaced_smart_quote", result.actions)
        self.assertEqual(result.data, {"a": "b"})

    def test_single_quoted_object(self):
        result = repair("{'a': 1, 'b': 'hi'}")
        self.assertTrue(result.ok)
        self.assertIn("converted_single_quotes", result.actions)
        self.assertEqual(result.data, {"a": 1, "b": "hi"})

    def test_single_quoted_top_level_array(self):
        result = repair("['a', 'b', 'c']")
        self.assertTrue(result.ok)
        self.assertEqual(result.data, ["a", "b", "c"])
        self.assertIn("converted_single_quotes", result.actions)

    def test_mixed_quote_styles(self):
        result = repair("{'a': \"x\", \"b\": 'y'}")
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": "x", "b": "y"})

    def test_unicode_inside_repaired_strings(self):
        result = repair("{'name': 'café', 'city': '東京'}")
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"name": "café", "city": "東京"})


class PunctuationAndKeyTests(unittest.TestCase):
    """Comments, trailing commas, bare keys, literals and escapes."""

    def test_trailing_comma_in_object(self):
        result = repair('{"a": 1,}')
        self.assertTrue(result.ok)
        self.assertIn("removed_trailing_comma", result.actions)
        self.assertEqual(result.data, {"a": 1})

    def test_trailing_commas_in_nested_containers(self):
        result = repair('{"a": [1, 2,], "b": {"c": 3,},}')
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": [1, 2], "b": {"c": 3}})
        self.assertGreaterEqual(result.actions.count("removed_trailing_comma"), 1)

    def test_trailing_comma_in_top_level_array(self):
        result = repair("[1, 2, 3,]")
        self.assertTrue(result.ok)
        self.assertEqual(result.data, [1, 2, 3])

    def test_line_comment_is_removed(self):
        result = repair('{"a": 1 // explanation\n}')
        self.assertTrue(result.ok)
        self.assertIn("removed_line_comment", result.actions)
        self.assertEqual(result.data, {"a": 1})

    def test_block_comment_is_removed(self):
        result = repair('{"a": /* explanation */ 1}')
        self.assertTrue(result.ok)
        self.assertIn("removed_block_comment", result.actions)
        self.assertEqual(result.data, {"a": 1})

    def test_comment_like_sequence_inside_string_is_preserved(self):
        text = '{"url": "https://example.com/path"}'
        result = repair(text)
        self.assertTrue(result.ok)
        self.assertFalse(result.repaired)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.data["url"], "https://example.com/path")

    def test_bare_object_keys_are_quoted(self):
        result = repair("{a: 1, b: 2}")
        self.assertTrue(result.ok)
        self.assertGreaterEqual(result.actions.count("quoted_bare_key"), 1)
        self.assertEqual(result.data, {"a": 1, "b": 2})

    def test_python_literals_are_replaced(self):
        result = repair('{"a": True, "b": False, "c": None}')
        self.assertTrue(result.ok)
        self.assertIn("replaced_python_literal", result.actions)
        self.assertIs(result.data["a"], True)
        self.assertIs(result.data["b"], False)
        self.assertIsNone(result.data["c"])

    def test_js_undefined_becomes_null(self):
        result = repair('{"a": undefined}')
        self.assertTrue(result.ok)
        self.assertIn("replaced_undefined", result.actions)
        self.assertIsNone(result.data["a"])

    def test_nan_and_infinity_become_null(self):
        result = repair('{"a": NaN, "b": Infinity, "c": -Infinity}')
        self.assertTrue(result.ok)
        self.assertIn("replaced_nan_infinity", result.actions)
        self.assertTrue(result.warnings)
        self.assertEqual(result.data, {"a": None, "b": None, "c": None})

    def test_leading_plus_on_number_is_removed(self):
        result = repair('{"n": +12}')
        self.assertTrue(result.ok)
        self.assertIn("fixed_number_sign", result.actions)
        self.assertEqual(result.data, {"n": 12})

    def test_leading_plus_in_array_and_object(self):
        result = repair('{"a": [+1, +2], "b": +3}')
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": [1, 2], "b": 3})

    def test_invalid_hex_escape_is_sanitized(self):
        result = repair('{"c": "\\x41"}')
        self.assertTrue(result.ok)
        self.assertIn("sanitized_escape", result.actions)
        self.assertEqual(result.data, {"c": "A"})


class TruncationTests(unittest.TestCase):
    """Deterministic recovery of truncated JSON."""

    def _assert_closed(self, text, expected):
        result = repair(text)
        self.assertTrue(result.ok, "failed to recover {0!r}".format(text))
        self.assertEqual(result.data, expected)
        self.assertIn("closed_truncated_json", result.actions)
        self.assertTrue(result.warnings)

    def test_truncated_after_open_array(self):
        self._assert_closed('{"a": 1, "b": [', {"a": 1, "b": []})

    def test_truncated_nested_object(self):
        self._assert_closed(
            '{"user": {"name": "Ada", "score": 42',
            {"user": {"name": "Ada", "score": 42}},
        )

    def test_truncated_inside_string_drops_partial_member(self):
        self._assert_closed('{"a": 1, "b": "hel', {"a": 1})

    def test_truncated_after_comma(self):
        self._assert_closed('{"a": 1,', {"a": 1})

    def test_truncated_array_with_object_element(self):
        self._assert_closed('[1, 2, {"x": 1', [1, 2, {"x": 1}])

    def test_truncated_empty_containers(self):
        self._assert_closed('[', [])
        self._assert_closed('{"a": [', {"a": []})

    def test_truncated_object_with_array(self):
        self._assert_closed('{"a": [1, 2', {"a": [1, 2]})

    def test_truncated_inside_fence(self):
        text = 'Here:\n```json\n{"a": 1, "b": [1, 2,]\n```'
        result = repair(text)
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": 1, "b": [1, 2]})

    def test_repaired_truncated_output_is_idempotent(self):
        result = repair('{"a": 1, "b": [')
        self.assertTrue(result.ok)
        second = repair(json.dumps(result.data))
        self.assertTrue(second.ok)
        self.assertFalse(second.repaired)


class DuplicateKeyTests(unittest.TestCase):
    """Duplicated keys are collapsed last-wins with an action and warning."""

    def test_duplicate_keys_fast_path(self):
        result = repair('{"a": 1, "a": 2}')
        self.assertTrue(result.ok)
        self.assertTrue(result.repaired)
        self.assertEqual(result.data, {"a": 2})
        self.assertTrue(
            any(action.startswith("deduplicated_key:last_wins:") for action in result.actions)
        )
        self.assertTrue(
            any(warning.startswith("duplicate_key:last_wins:") for warning in result.warnings)
        )

    def test_duplicate_keys_after_other_repairs(self):
        result = repair('{a: 1, a: 2}')
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": 2})
        self.assertTrue(
            any(action.startswith("deduplicated_key:last_wins:") for action in result.actions)
        )

    def test_duplicate_keys_distinct_names_all_reported(self):
        result = repair('{"a": 1, "b": 1, "a": 2, "b": 3}')
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": 2, "b": 3})
        self.assertGreaterEqual(
            len([w for w in result.warnings if w.startswith("duplicate_key:last_wins:")]), 2
        )


class ValidateSchemaTests(unittest.TestCase):
    """The minimal JSON Schema subset validator."""

    def test_valid_document_returns_empty_list(self):
        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        self.assertEqual(validate_schema({"name": "Ada"}, schema), [])

    def test_valid_document_with_nested_arrays(self):
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"n": {"type": "number"}},
                    },
                }
            },
        }
        self.assertEqual(validate_schema({"items": [{"n": 1}, {"n": 2.5}]}, schema), [])

    def test_type_error_message(self):
        errors = validate_schema(
            {"a": 1}, {"type": "object", "properties": {"a": {"type": "string"}}}
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("$.a", errors[0])
        self.assertIn("expected string", errors[0])

    def test_nested_item_path_is_reported(self):
        schema = {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                    },
                }
            },
        }
        errors = validate_schema(
            {"items": [{"name": "a"}, {"name": "b"}, {"name": 3}]}, schema
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("$.items[2].name", errors[0])
        self.assertIn("expected string", errors[0])

    def test_missing_required_property(self):
        errors = validate_schema({}, {"type": "object", "required": ["a"]})
        self.assertTrue(any("missing required" in error for error in errors))
        self.assertTrue(any("$" in error for error in errors))

    def test_enum_violation(self):
        schema = {"type": "object", "properties": {"color": {"enum": ["red", "green"]}}}
        errors = validate_schema({"color": "blue"}, schema)
        self.assertTrue(any("enum" in error for error in errors))

    def test_minimum_violation(self):
        schema = {"type": "object", "properties": {"age": {"type": "integer", "minimum": 5}}}
        errors = validate_schema({"age": 3}, schema)
        self.assertEqual(len(errors), 1)
        self.assertIn("minimum", errors[0])

    def test_maximum_violation(self):
        schema = {"type": "object", "properties": {"age": {"type": "integer", "maximum": 7}}}
        errors = validate_schema({"age": 9}, schema)
        self.assertEqual(len(errors), 1)
        self.assertIn("maximum", errors[0])

    def test_additional_properties_false(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "integer"}},
            "additionalProperties": False,
        }
        errors = validate_schema({"a": 1, "extra": 2}, schema)
        self.assertTrue(any("extra" in error for error in errors))

    def test_boolean_is_not_an_integer(self):
        errors = validate_schema(True, {"type": "integer"})
        self.assertEqual(len(errors), 1)
        self.assertIn("expected integer", errors[0])

    def test_number_accepts_integer_and_float(self):
        self.assertEqual(validate_schema(3, {"type": "number"}), [])
        self.assertEqual(validate_schema(3.5, {"type": "number"}), [])

    def test_multiple_independent_errors_are_collected(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        }
        errors = validate_schema({"a": "x", "b": "y"}, schema)
        self.assertEqual(len(errors), 2)

    def test_validator_does_not_mutate_input(self):
        value = {"items": [{"n": 1}]}
        snapshot = json.loads(json.dumps(value))
        schema = {"type": "object", "properties": {"items": {"type": "array"}}}
        validate_schema(value, schema)
        self.assertEqual(value, snapshot)


class SchemaRepairTests(unittest.TestCase):
    """Schema validation + schema-guided coercions inside ``repair``."""

    STRICT_SCHEMA = {
        "type": "object",
        "required": ["a"],
        "properties": {"a": {"type": "integer"}},
    }

    def test_schema_valid_fast_path(self):
        result = repair('{"a": 1}', self.STRICT_SCHEMA)
        self.assertTrue(result.ok)
        self.assertFalse(result.repaired)
        self.assertEqual(result.actions, [])
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.data, {"a": 1})

    def test_string_to_integer_coercion(self):
        result = repair(
            '{"a": "123"}', {"type": "object", "properties": {"a": {"type": "integer"}}}
        )
        self.assertTrue(result.ok)
        self.assertTrue(result.repaired)
        self.assertIn("coerced_string_to_integer", result.actions)
        self.assertEqual(result.data, {"a": 123})

    def test_string_to_number_coercion(self):
        result = repair(
            '{"a": "1.5"}', {"type": "object", "properties": {"a": {"type": "number"}}}
        )
        self.assertTrue(result.ok)
        self.assertIn("coerced_string_to_number", result.actions)
        self.assertEqual(result.data, {"a": 1.5})

    def test_string_to_boolean_coercion(self):
        result = repair(
            '{"a": "true"}', {"type": "object", "properties": {"a": {"type": "boolean"}}}
        )
        self.assertTrue(result.ok)
        self.assertIn("coerced_string_to_boolean", result.actions)
        self.assertIs(result.data["a"], True)

    def test_number_to_boolean_coercion(self):
        result = repair(
            '{"a": 1}', {"type": "object", "properties": {"a": {"type": "boolean"}}}
        )
        self.assertTrue(result.ok)
        self.assertIn("coerced_number_to_boolean", result.actions)
        self.assertIs(result.data["a"], True)

    def test_string_to_null_coercion(self):
        result = repair(
            '{"a": "null"}', {"type": "object", "properties": {"a": {"type": "null"}}}
        )
        self.assertTrue(result.ok)
        self.assertIn("coerced_string_to_null", result.actions)
        self.assertIsNone(result.data["a"])

    def test_scalar_wrapped_in_array(self):
        result = repair(
            '{"tags": "solo"}',
            {"type": "object", "properties": {"tags": {"type": "array"}}},
        )
        self.assertTrue(result.ok)
        self.assertIn("wrapped_value_in_array", result.actions)
        self.assertEqual(result.data, {"tags": ["solo"]})

    def test_array_items_are_coerced(self):
        result = repair(
            '{"nums": ["1", 2]}',
            {
                "type": "object",
                "properties": {
                    "nums": {"type": "array", "items": {"type": "integer"}}
                },
            },
        )
        self.assertTrue(result.ok)
        self.assertIn("coerced_string_to_integer", result.actions)
        self.assertEqual(result.data, {"nums": [1, 2]})

    def test_nested_object_coercion(self):
        result = repair(
            '{"user": {"age": "30"}}',
            {
                "type": "object",
                "properties": {
                    "user": {
                        "type": "object",
                        "properties": {"age": {"type": "integer"}},
                    }
                },
            },
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"user": {"age": 30}})

    def test_additional_properties_are_dropped(self):
        result = repair(
            '{"a": 1, "secret": 2}',
            {
                "type": "object",
                "properties": {"a": {"type": "integer"}},
                "additionalProperties": False,
            },
        )
        self.assertTrue(result.ok)
        self.assertTrue(result.repaired)
        self.assertEqual(result.data, {"a": 1})
        self.assertTrue(
            any(
                action.startswith("removed_additional_property")
                for action in result.actions
            )
        )
        self.assertTrue(
            any("removed_additional_property" in warning for warning in result.warnings)
        )

    def test_missing_required_is_a_failure(self):
        result = repair('{"a": 1}', {"type": "object", "required": ["a", "b"]})
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertFalse(result.repaired)
        self.assertEqual(result.actions, [])
        self.assertTrue(result.warnings)
        self.assertTrue(result.warnings[0].startswith("schema:"))

    def test_enum_violation_is_a_failure(self):
        result = repair(
            '{"color": "red"}',
            {"type": "object", "properties": {"color": {"enum": ["green", "blue"]}}},
        )
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertTrue(result.warnings[0].startswith("schema:"))

    def test_minimum_violation_is_a_failure(self):
        result = repair(
            '{"age": 3}',
            {
                "type": "object",
                "properties": {"age": {"type": "integer", "minimum": 5}},
            },
        )
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertTrue(any("minimum" in warning for warning in result.warnings))

    def test_schema_type_violation_is_a_failure(self):
        result = repair(
            '{"a": 1}',
            {"type": "object", "properties": {"a": {"type": "string"}}},
        )
        self.assertFalse(result.ok)
        self.assertIsNone(result.data)
        self.assertIn("expected string", result.warnings[0])


class RobustnessTests(unittest.TestCase):
    """Huge inputs, determinism and idempotence."""

    def test_huge_valid_document_fast_path_performance(self):
        payload = {
            "items": [
                {
                    "id": index,
                    "name": "item-{0}".format(index),
                    "tags": ["alpha", "beta"],
                    "value": index * 0.5,
                }
                for index in range(1500)
            ]
        }
        text = json.dumps(payload)
        self.assertGreaterEqual(len(text), 100_000)
        started = time.perf_counter()
        result = repair(text)
        elapsed = time.perf_counter() - started
        self.assertTrue(result.ok)
        self.assertFalse(result.repaired)
        self.assertEqual(result.actions, [])
        self.assertEqual(len(result.data["items"]), 1500)
        self.assertLess(elapsed, 5.0)

    def test_repair_is_deterministic(self):
        text = '```json\n{a: True, "b": [1, 2,], /*c*/}\n```'
        first = repair(text)
        second = repair(text)
        self.assertEqual(first.ok, second.ok)
        self.assertEqual(first.repaired, second.repaired)
        self.assertEqual(first.actions, second.actions)
        self.assertEqual(first.warnings, second.warnings)
        self.assertEqual(first.data, second.data)
        self.assertEqual(first.text, second.text)

    def test_repaired_output_round_trips_without_new_actions(self):
        samples = [
            "{'a': True, 'b': [1, 2,], /* hi */}",
            '{"a": +1, "b": "\\x41",}',
            '\ufeff{"a": 1}\r\n',
            'Here: {"a": 1,}',
        ]
        for sample in samples:
            with self.subTest(sample=sample):
                first = repair(sample)
                self.assertTrue(first.ok)
                serialized = json.dumps(first.data, ensure_ascii=False)
                second = repair(serialized)
                self.assertTrue(second.ok)
                self.assertFalse(second.repaired)
                self.assertEqual(second.actions, [])
                self.assertEqual(second.warnings, [])
                self.assertEqual(second.data, first.data)

    def test_independent_containers_after_repair(self):
        result = repair('{a: 1, b: [2, 3,], c: {d: None,}}')
        self.assertTrue(result.ok)
        self.assertEqual(result.data, {"a": 1, "b": [2, 3], "c": {"d": None}})
        self.assertIsNone(result.data["c"]["d"])


if __name__ == "__main__":
    unittest.main()
