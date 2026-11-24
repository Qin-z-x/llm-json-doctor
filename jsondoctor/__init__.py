"""jsondoctor - deterministic repair and validation for malformed LLM JSON.

Stdlib only. No network, no LLM calls, no eval/exec. Every repair is logged.
"""

from __future__ import annotations

from .repair import (
    ACTION_LABELS,
    JsonDoctorError,
    RepairResult,
    extract_json,
    repair,
    validate_schema,
)

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "ACTION_LABELS",
    "JsonDoctorError",
    "RepairResult",
    "extract_json",
    "repair",
    "validate_schema",
]
