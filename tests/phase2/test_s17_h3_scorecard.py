from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from business_ai_gateway.phase2.h3_scorecard import (
    H3EvidenceClass,
    H3EvidenceReceiptVerifier,
    H3FieldEvidence,
    H3FileFormat,
    H3InvoiceEvidence,
    H3MetricStatus,
    H3Status,
    evaluate_h3,
)


FROZEN = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
STARTED = FROZEN + timedelta(minutes=1)


class _TrustedReceiptVerifier:
    def __init__(self, result: object = True, *, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[tuple[str, ...], tuple[str, ...]]] = []

    def verify(self, source_hashes: tuple[str, ...], run_ids: tuple[str, ...]) -> bool:
        self.calls.append((source_hashes, run_ids))
        if self.error is not None:
            raise self.error
        return self.result  # type: ignore[return-value]


def _verifier(result: object = True, *, error: Exception | None = None) -> H3EvidenceReceiptVerifier:
    return _TrustedReceiptVerifier(result, error=error)


def _invoice(
    index: int,
    *,
    corrected: bool = False,
    reviewed: bool = True,
    confidently_wrong: bool = False,
    approved: bool = False,
    file_format: H3FileFormat | None = None,
    evidence_class: H3EvidenceClass = H3EvidenceClass.TEST_LANE_REAL,
    run_id: str | None = "run-001",
    fields: tuple[H3FieldEvidence, ...] | None = None,
) -> H3InvoiceEvidence:
    return H3InvoiceEvidence(
        source_sha256=f"{index:064x}",
        file_format=file_format or H3FileFormat.CSV,
        frozen_at=FROZEN,
        extraction_started_at=STARTED,
        evidence_class=evidence_class,
        test_lane_run_id=run_id,
        fields=fields if fields is not None else (
            H3FieldEvidence(True, corrected, confidently_wrong, reviewed, approved),
        ),
    )


def _sample(*, corrected_count: int = 0, **overrides: object) -> tuple[H3InvoiceEvidence, ...]:
    return tuple(
        _invoice(index, corrected=index <= corrected_count, **overrides)
        for index in range(1, 31)
    )


def test_exact_ten_percent_passes_and_strata_are_reported_separately() -> None:
    formats = tuple(H3FileFormat)
    rows = tuple(
        _invoice(index, corrected=index <= 3, file_format=formats[(index - 1) % len(formats)])
        for index in range(1, 31)
    )

    verifier = _TrustedReceiptVerifier()
    result = evaluate_h3(rows, receipt_verifier=verifier)

    assert result.status is H3Status.PASS
    assert result.code == "H3_THRESHOLD_MET"
    assert result.document_count == 30
    assert result.material_field_count == 30
    assert result.corrected_material_field_count == 3
    assert result.metric_status is H3MetricStatus.PASS
    assert {stratum.file_format for stratum in result.strata} == set(formats)
    assert sum(stratum.document_count for stratum in result.strata) == 30
    assert verifier.calls == [(tuple(row.source_sha256 for row in rows), ("run-001",) * 30)]


def test_more_than_ten_percent_semantic_corrections_fails_without_rounding() -> None:
    result = evaluate_h3(_sample(corrected_count=4), receipt_verifier=_verifier())

    assert result.status is H3Status.FAIL
    assert result.code == "CORRECTED_FIELD_RATE_OVER_10_PERCENT"
    assert result.corrected_material_field_count == 4
    assert result.metric_status is H3MetricStatus.FAIL


@pytest.mark.parametrize(
    ("evidence_class", "run_id", "expected_code"),
    [
        (H3EvidenceClass.SYNTHETIC_ONLY, "run-001", "SYNTHETIC_ONLY_EVIDENCE"),
        (H3EvidenceClass.TEST_LANE_REALISTIC, None, "TEST_LANE_EVIDENCE_MISSING"),
    ],
)
def test_synthetic_or_missing_lane_evidence_never_accepts(
    evidence_class: H3EvidenceClass, run_id: str | None, expected_code: str,
) -> None:
    result = evaluate_h3(_sample(evidence_class=evidence_class, run_id=run_id))

    assert result.status is H3Status.NOT_ACCEPTANCE
    assert result.code == expected_code


@pytest.mark.parametrize(
    ("verifier", "expected_metric"),
    [
        (None, H3MetricStatus.PASS),
        (_verifier(False), H3MetricStatus.PASS),
        (_verifier(error=TimeoutError("unavailable")), H3MetricStatus.PASS),
    ],
)
def test_unverified_or_unavailable_receipt_is_not_acceptance(
    verifier: H3EvidenceReceiptVerifier | None, expected_metric: H3MetricStatus,
) -> None:
    result = evaluate_h3(_sample(), receipt_verifier=verifier)

    assert result.status is H3Status.NOT_ACCEPTANCE
    assert result.code == "TEST_LANE_EVIDENCE_UNVERIFIED"
    assert result.metric_status is expected_metric


@pytest.mark.parametrize("invalid_result", [1, "true", None])
def test_receipt_verifier_requires_literal_true(invalid_result: object) -> None:
    result = evaluate_h3(_sample(), receipt_verifier=_verifier(invalid_result))

    assert result.status is H3Status.NOT_ACCEPTANCE
    assert result.code == "TEST_LANE_EVIDENCE_UNVERIFIED"
    assert result.metric_status is H3MetricStatus.PASS


def test_empty_material_denominator_is_not_ready() -> None:
    rows = tuple(
        _invoice(index, fields=(H3FieldEvidence(False, False, False, True, False),))
        for index in range(1, 31)
    )

    result = evaluate_h3(rows, receipt_verifier=_verifier())

    assert result.status is H3Status.NOT_READY
    assert result.code == "NO_MATERIAL_FIELDS"
    assert result.material_field_count == 0
    assert result.metric_status is H3MetricStatus.NOT_READY


@pytest.mark.parametrize("field", [
    H3FieldEvidence(True, False, False, False, False),
    H3FieldEvidence(True, False, True, False, True),
])
def test_unreviewed_material_field_fails_even_below_correction_threshold(
    field: H3FieldEvidence,
) -> None:
    rows = tuple(_invoice(index, fields=(field,)) for index in range(1, 31))

    result = evaluate_h3(rows, receipt_verifier=_verifier())

    assert result.status is H3Status.FAIL
    assert result.unreviewed_material_field_count == 30
    assert result.metric_status is H3MetricStatus.FAIL


@pytest.mark.parametrize("malformed", ["invoice", "field"])
def test_incomplete_slotted_evidence_fails_with_fixed_invalid_result(malformed: str) -> None:
    rows = list(_sample())
    if malformed == "invoice":
        partial = object.__new__(H3InvoiceEvidence)
        object.__setattr__(partial, "source_sha256", f"{1:064x}")
        rows[0] = partial
    else:
        partial_field = object.__new__(H3FieldEvidence)
        object.__setattr__(partial_field, "material", True)
        object.__setattr__(partial_field, "semantic_correction", False)
        object.__setattr__(partial_field, "confidently_wrong", False)
        object.__setattr__(partial_field, "human_reviewed", True)
        rows[0] = _invoice(1, fields=(partial_field,))

    result = evaluate_h3(tuple(rows))

    assert result.status is H3Status.INVALID
    assert result.code == "INVOICE_EVIDENCE_INVALID"
    assert result.document_count == 0
    assert result.strata == ()


def test_duplicate_hash_and_freeze_after_start_are_invalid() -> None:
    duplicate = list(_sample())
    duplicate[1] = _invoice(1)
    bad_time = list(_sample())
    row = bad_time[0]
    bad_time[0] = H3InvoiceEvidence(
        row.source_sha256,
        row.file_format,
        row.extraction_started_at,
        row.frozen_at,
        row.evidence_class,
        row.test_lane_run_id,
        row.fields,
    )

    duplicate_result = evaluate_h3(tuple(duplicate))
    time_result = evaluate_h3(tuple(bad_time))

    assert duplicate_result.status is H3Status.INVALID
    assert duplicate_result.code == "DUPLICATE_SOURCE_HASH"
    assert time_result.status is H3Status.INVALID
    assert time_result.code == "INVOICE_EVIDENCE_INVALID"
