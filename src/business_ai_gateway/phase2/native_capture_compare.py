"""Pure, offline comparison of caller-supplied canonical capture observations.

This module implements only the synthetic equivalence part of S5 TC064. It does
not read artifacts, establish their origin or completeness, invoke 1C, authorize
capture, or attest native equivalence. A MATCH is evaluation evidence only.
Values are compared exactly as supplied; normalization belongs to the caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "CaptureComparison",
    "CaptureComparisonState",
    "CanonicalCaptureObservation",
    "compare_capture_observations",
]

_MAX_ID_LENGTH = 256
_MAX_PARAMETER_COUNT = 128
_MAX_COLUMN_COUNT = 256
_MAX_ROW_COUNT = 10_000
_MAX_CELL_LENGTH = 4_096
_MAX_TOTAL_CELLS = 1_000_000
_MAX_CAPTURE_TEXT = 8_000_000
_MAX_DIFFERENCES = 64


@dataclass(frozen=True, slots=True)
class CanonicalCaptureObservation:
    """One already-normalized observation supplied by an offline caller.

    The immutable tuple representation is intentional: this comparator neither
    parses native files nor decides how report values should be normalized.
    ``normalized_rows`` preserves order, and parameter/total pairs must be sorted
    by their exact names. Constructing this value is not evidence of native origin.
    """

    tenant_id: str
    source_id: str
    database_id: str
    configuration_id: str
    company_id: str
    report_object: str
    variant: str
    normalized_parameters: tuple[tuple[str, str], ...]
    columns: tuple[str, ...]
    normalized_totals: tuple[tuple[str, str], ...]
    normalized_rows: tuple[tuple[str, ...], ...]


class CaptureComparisonState(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class CaptureComparison:
    state: CaptureComparisonState
    reason_code: str
    differences: tuple[str, ...] = ()
    differences_truncated: bool = False
    authority: str = field(default="SYNTHETIC_EVALUATION_ONLY", init=False)
    native_equivalence_established: bool = field(default=False, init=False)


def _bounded_text(value: object, *, allow_empty: bool = False) -> bool:
    return (
        type(value) is str
        and (allow_empty or bool(value))
        and len(value) <= _MAX_CELL_LENGTH
        and "\x00" not in value
    )


def _bounded_identity(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and len(value) <= _MAX_ID_LENGTH
        and value == value.strip()
        and "\x00" not in value
    )


def _valid_pairs(value: object, *, max_count: int) -> bool:
    if type(value) is not tuple or len(value) > max_count:
        return False
    previous: str | None = None
    for pair in value:
        if type(pair) is not tuple or len(pair) != 2:
            return False
        key, item = pair
        if not _bounded_text(key) or not _bounded_text(item, allow_empty=True):
            return False
        if previous is not None and key <= previous:
            return False
        previous = key
    return True


def _valid_observation(value: object) -> bool:
    if type(value) is not CanonicalCaptureObservation:
        return False
    # Read each field once and accept only exact immutable built-ins. This keeps
    # caller-defined equality, iteration, and coercion out of the comparison path.
    tenant, source, database, configuration, company, report, variant = (
        value.tenant_id,
        value.source_id,
        value.database_id,
        value.configuration_id,
        value.company_id,
        value.report_object,
        value.variant,
    )
    parameters, columns, totals, rows = (
        value.normalized_parameters,
        value.columns,
        value.normalized_totals,
        value.normalized_rows,
    )
    if not all(_bounded_identity(v) for v in (
        tenant, source, database, configuration, company, report, variant,
    )):
        return False
    if not _valid_pairs(parameters, max_count=_MAX_PARAMETER_COUNT):
        return False
    if type(columns) is not tuple or not 1 <= len(columns) <= _MAX_COLUMN_COUNT:
        return False
    if any(not _bounded_text(column) for column in columns) or len(set(columns)) != len(columns):
        return False
    if type(totals) is not tuple or not totals or not _valid_pairs(totals, max_count=_MAX_COLUMN_COUNT):
        return False
    text_size = sum(map(len, (tenant, source, database, configuration, company, report, variant)))
    text_size += sum(len(key) + len(item) for key, item in parameters)
    text_size += sum(map(len, columns))
    text_size += sum(len(key) + len(item) for key, item in totals)
    if text_size > _MAX_CAPTURE_TEXT:
        return False
    if type(rows) is not tuple or len(rows) > _MAX_ROW_COUNT:
        return False
    cells = 0
    for row in rows:
        if type(row) is not tuple or len(row) != len(columns):
            return False
        cells += len(row)
        if cells > _MAX_TOTAL_CELLS or any(not _bounded_text(cell, allow_empty=True) for cell in row):
            return False
        text_size += sum(map(len, row))
        if text_size > _MAX_CAPTURE_TEXT:
            return False
    return True


def _inconclusive(code: str) -> CaptureComparison:
    return CaptureComparison(CaptureComparisonState.INCONCLUSIVE, code)


def compare_capture_observations(left: object, right: object) -> CaptureComparison:
    """Compare two canonical inputs without claiming capture completeness or native equivalence.

    Malformed, oversized, or noncanonical inputs fail closed as INCONCLUSIVE.
    MATCH means only that the supplied representations are equal. Differences identify
    fields or bounded row/column positions,
    never returning business values.
    """
    try:
        if not _valid_observation(left) or not _valid_observation(right):
            return _inconclusive("CAPTURE_INPUT_UNVERIFIED")

        assert type(left) is CanonicalCaptureObservation
        assert type(right) is CanonicalCaptureObservation
        identity_left = (
            left.tenant_id,
            left.source_id,
            left.database_id,
            left.configuration_id,
            left.company_id,
            left.report_object,
            left.variant,
            left.normalized_parameters,
        )
        identity_right = (
            right.tenant_id,
            right.source_id,
            right.database_id,
            right.configuration_id,
            right.company_id,
            right.report_object,
            right.variant,
            right.normalized_parameters,
        )
        if identity_left != identity_right:
            return _inconclusive("CAPTURE_CONTEXT_MISMATCH")

        labels: list[str] = []
        truncated = False

        def note(label: str) -> None:
            nonlocal truncated
            if len(labels) < _MAX_DIFFERENCES:
                labels.append(label)
            else:
                truncated = True

        if left.columns != right.columns:
            note("columns")
        if left.normalized_totals != right.normalized_totals:
            note("totals")
        if len(left.normalized_rows) != len(right.normalized_rows):
            note("row_count")
        for row_index, (left_row, right_row) in enumerate(
            zip(left.normalized_rows, right.normalized_rows)
        ):
            for column_index, (left_cell, right_cell) in enumerate(zip(left_row, right_row)):
                if left_cell != right_cell:
                    note(f"rows[{row_index}][{column_index}]")
        if labels or truncated:
            return CaptureComparison(
                CaptureComparisonState.MISMATCH,
                "CAPTURE_CONTENT_DIFFERS",
                tuple(labels),
                truncated,
            )
        return CaptureComparison(CaptureComparisonState.MATCH, "SYNTHETIC_CAPTURE_VALUES_EQUAL")
    except Exception:  # fixed fail-closed result; no caller data or exception text escapes
        return _inconclusive("CAPTURE_INPUT_UNVERIFIED")
