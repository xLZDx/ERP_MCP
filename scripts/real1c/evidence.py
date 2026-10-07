"""Evidence classes and the validate-guard.

Policy: NATIVE_COM_QUERY and NATIVE_ENGINE_REPORT are comparison-only classes. They can never reach
``scripts/semantic_profiles.py`` validate and can never yield VALIDATED_NATIVE,
PROFILE_EVIDENCE_ON_FILE or PROFILE_VALIDATED. Only genuine native 1C UI
reports (NATIVE_UI_REPORT, each with a 64-hex report sha256) count, and at
least ten distinct cases are needed before validate may be called.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

EVIDENCE_CLASSES = frozenset(
    {
        "GATEWAY_OBSERVATION",
        "NATIVE_COM_QUERY",
        "NATIVE_ENGINE_REPORT",
        "CONTROL_PLANE_ROWS",
        "REPO_STATIC",
        "NATIVE_UI_REPORT",
        "NONE",
    }
)
NATIVE_REPORT_CLASS = "NATIVE_UI_REPORT"
MIN_NATIVE_CASES = 10
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class ValidateRefused(Exception):
    """The evidence manifest is not enough to call profile validate."""


def _counting_cases(manifest: Mapping[str, Any]) -> set[str]:
    cases = manifest.get("cases") if isinstance(manifest, Mapping) else None
    if not isinstance(cases, list):
        return set()
    ids: set[str] = set()
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        case_id = case.get("case_id")
        sha = case.get("native_report_sha256")
        if (
            isinstance(case_id, str)
            and case_id
            and case.get("evidence_class") == NATIVE_REPORT_CLASS
            and isinstance(sha, str)
            and _HEX64.match(sha)
        ):
            ids.add(case_id)
    return ids


def assert_can_validate(evidence_manifest: Mapping[str, Any]) -> None:
    n = len(_counting_cases(evidence_manifest))
    if n < MIN_NATIVE_CASES:
        raise ValidateRefused(
            f"{n} distinct NATIVE_UI_REPORT cases with report sha256; need {MIN_NATIVE_CASES}"
        )


def would_validate(manifest: Mapping[str, Any]) -> bool:
    try:
        assert_can_validate(manifest)
    except ValidateRefused:
        return False
    return True


def guarded_validate(manifest: Mapping[str, Any], validate_callable: Callable[[], Any]) -> Any:
    """Call ``validate_callable`` only after the guard passed."""
    assert_can_validate(manifest)
    return validate_callable()
