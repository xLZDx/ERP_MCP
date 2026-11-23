from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone

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
    def __init__(
        self,
        result: object = True,
        *,
        expected_sha256: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.expected_sha256 = expected_sha256
        self.error = error
        self.calls: list[tuple[tuple[tuple[str, str], ...], str]] = []

    def verify(
        self,
        source_runs: tuple[tuple[str, str], ...],
        evidence_sha256: str,
    ) -> bool:
        self.calls.append((source_runs, evidence_sha256))
        if self.error is not None:
            raise self.error
        if self.expected_sha256 is not None:
            return self.result is True and evidence_sha256 == self.expected_sha256
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


def _receipt_digest(rows: tuple[H3InvoiceEvidence, ...]) -> str:
    verifier = _TrustedReceiptVerifier()
    evaluate_h3(rows, receipt_verifier=verifier)
    assert len(verifier.calls) == 1
    return verifier.calls[0][1]


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
    assert len(verifier.calls) == 1
    source_runs, evidence_sha256 = verifier.calls[0]
    assert source_runs == tuple((row.source_sha256, "run-001") for row in rows)
    assert len(evidence_sha256) == 64
    assert all(char in "0123456789abcdef" for char in evidence_sha256)


@pytest.mark.parametrize(
    "claim",
    [
        "source_sha256",
        "file_format",
        "frozen_at",
        "extraction_started_at",
        "evidence_class",
        "test_lane_run_id",
        "material",
        "semantic_correction",
        "confidently_wrong",
        "human_reviewed",
        "approved",
    ],
)
def test_receipt_digest_changes_when_any_scored_claim_changes(claim: str) -> None:
    rows = list(_sample())
    original = rows[0]
    if claim == "source_sha256":
        rows[0] = replace(original, source_sha256=f"{99:064x}")
    elif claim == "file_format":
        rows[0] = replace(original, file_format=H3FileFormat.XLSX)
    elif claim == "frozen_at":
        rows[0] = replace(original, frozen_at=FROZEN + timedelta(seconds=1))
    elif claim == "extraction_started_at":
        rows[0] = replace(original, extraction_started_at=STARTED + timedelta(seconds=1))
    elif claim == "evidence_class":
        rows[0] = replace(original, evidence_class=H3EvidenceClass.TEST_LANE_REALISTIC)
    elif claim == "test_lane_run_id":
        rows[0] = replace(original, test_lane_run_id="run-002")
    else:
        field = original.fields[0]
        field_value = {
            "material": not field.material,
            "semantic_correction": not field.semantic_correction,
            "confidently_wrong": not field.confidently_wrong,
            "human_reviewed": not field.human_reviewed,
            "approved": not field.approved,
        }[claim]
        rows[0] = replace(original, fields=(replace(field, **{claim: field_value}),))

    assert _receipt_digest(tuple(rows)) != _receipt_digest(_sample())


def test_receipt_digest_is_stable_for_same_instant_in_another_timezone() -> None:
    rows = _sample()
    plus_two = timezone(timedelta(hours=2))
    localized = tuple(
        replace(
            row,
            frozen_at=row.frozen_at.astimezone(plus_two),
            extraction_started_at=row.extraction_started_at.astimezone(plus_two),
        )
        for row in rows
    )

    assert _receipt_digest(localized) == _receipt_digest(rows)


def test_verified_receipt_cannot_be_reused_after_a_review_claim_changes() -> None:
    rows = _sample()
    receipt_digest = _receipt_digest(rows)
    verifier = _TrustedReceiptVerifier(expected_sha256=receipt_digest)
    accepted = evaluate_h3(rows, receipt_verifier=verifier)

    changed = list(rows)
    original = changed[0]
    changed[0] = replace(
        original,
        fields=(replace(original.fields[0], human_reviewed=False),),
    )
    refused = evaluate_h3(tuple(changed), receipt_verifier=verifier)

    assert accepted.status is H3Status.PASS
    assert refused.status is H3Status.NOT_ACCEPTANCE
    assert refused.code == "TEST_LANE_EVIDENCE_UNVERIFIED"
    assert verifier.calls[0][0] == verifier.calls[1][0]
    assert verifier.calls[0][1] == receipt_digest
    assert verifier.calls[1][1] != receipt_digest


def test_receipt_binds_each_source_to_its_exact_run_id() -> None:
    rows = tuple(
        replace(row, test_lane_run_id=f"run-{index:02d}")
        for index, row in enumerate(_sample(), start=1)
    )
    receipt_digest = _receipt_digest(rows)
    verifier = _TrustedReceiptVerifier(expected_sha256=receipt_digest)
    accepted = evaluate_h3(rows, receipt_verifier=verifier)

    swapped_runs = list(rows)
    swapped_runs[0] = replace(swapped_runs[0], test_lane_run_id=rows[1].test_lane_run_id)
    swapped_runs[1] = replace(swapped_runs[1], test_lane_run_id=rows[0].test_lane_run_id)
    refused = evaluate_h3(tuple(swapped_runs), receipt_verifier=verifier)

    expected_pairs = tuple((row.source_sha256, row.test_lane_run_id) for row in rows)
    swapped_pairs = tuple((row.source_sha256, row.test_lane_run_id) for row in swapped_runs)
    assert accepted.status is H3Status.PASS
    assert refused.status is H3Status.NOT_ACCEPTANCE
    assert refused.code == "TEST_LANE_EVIDENCE_UNVERIFIED"
    assert tuple(pair[0] for pair in expected_pairs) == tuple(pair[0] for pair in swapped_pairs)
    assert {pair[1] for pair in expected_pairs} == {pair[1] for pair in swapped_pairs}
    assert expected_pairs != swapped_pairs
    assert verifier.calls[0][0] == expected_pairs
    assert verifier.calls[1][0] == swapped_pairs
    assert verifier.calls[0][1] == receipt_digest
    assert verifier.calls[1][1] != receipt_digest


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
