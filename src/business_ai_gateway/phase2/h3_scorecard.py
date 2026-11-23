"""Value-free, fail-closed scorecard for the frozen S17 H3 evaluation."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol

__all__ = [
    "H3EvidenceClass", "H3EvidenceReceiptVerifier", "H3FileFormat", "H3FieldEvidence",
    "H3InvoiceEvidence", "H3MetricStatus", "H3Scorecard", "H3Status", "H3Stratum",
    "evaluate_h3",
]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
H3_SAMPLE_SIZE = 30


class H3FileFormat(StrEnum):
    XLSX = "xlsx"
    CSV = "csv"
    PDF = "pdf"
    IMAGE = "image"


class H3EvidenceClass(StrEnum):
    TEST_LANE_REAL = "TEST_LANE_REAL"
    TEST_LANE_REALISTIC = "TEST_LANE_REALISTIC"
    SYNTHETIC_ONLY = "SYNTHETIC_ONLY"


class H3Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_READY = "NOT_READY"
    NOT_ACCEPTANCE = "NOT_ACCEPTANCE"
    INVALID = "INVALID"


class H3MetricStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_READY = "NOT_READY"
    INVALID = "INVALID"


class H3EvidenceReceiptVerifier(Protocol):
    """Verify an authenticated receipt binding source/run pairs and digest to frozen bytes
    and authenticated human-review evidence. Mock/test verifiers exercise the contract only;
    they cannot establish H3 acceptance.
    """

    def verify(
        self,
        source_runs: tuple[tuple[str, str], ...],
        evidence_sha256: str,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class H3FieldEvidence:
    material: bool
    semantic_correction: bool
    confidently_wrong: bool
    human_reviewed: bool
    approved: bool


@dataclass(frozen=True, slots=True)
class H3InvoiceEvidence:
    source_sha256: str
    file_format: H3FileFormat
    frozen_at: datetime
    extraction_started_at: datetime
    evidence_class: H3EvidenceClass
    test_lane_run_id: str | None
    fields: tuple[H3FieldEvidence, ...]


@dataclass(frozen=True, slots=True)
class H3Stratum:
    file_format: H3FileFormat
    document_count: int
    material_field_count: int
    corrected_material_field_count: int
    unreviewed_material_field_count: int
    confidently_wrong_unreviewed_approved_count: int

    @property
    def within_correction_threshold(self) -> bool:
        return (self.material_field_count > 0
                and self.corrected_material_field_count * 10 <= self.material_field_count)


@dataclass(frozen=True, slots=True)
class H3Scorecard:
    """Acceptance status is separate from `metric_status`, which describes arithmetic only."""

    status: H3Status
    code: str
    document_count: int = 0
    material_field_count: int = 0
    corrected_material_field_count: int = 0
    unreviewed_material_field_count: int = 0
    confidently_wrong_unreviewed_approved_count: int = 0
    strata: tuple[H3Stratum, ...] = ()
    metric_status: H3MetricStatus = H3MetricStatus.NOT_READY


def evaluate_h3(
    evidence: object, *, receipt_verifier: H3EvidenceReceiptVerifier | None = None,
) -> H3Scorecard:
    """Score counts; require a trusted receipt verifier before reporting acceptance status."""
    if type(evidence) is not tuple or any(type(row) is not H3InvoiceEvidence for row in evidence):
        return H3Scorecard(H3Status.INVALID, "EVIDENCE_SHAPE_INVALID",
                           metric_status=H3MetricStatus.INVALID)
    if len(evidence) != H3_SAMPLE_SIZE:
        return H3Scorecard(H3Status.NOT_READY, "SAMPLE_SIZE_NOT_30",
                           document_count=len(evidence), metric_status=H3MetricStatus.NOT_READY)
    hashes: set[str] = set()
    synthetic_only = False
    for row in evidence:
        if not _invoice_valid(row):
            return H3Scorecard(H3Status.INVALID, "INVOICE_EVIDENCE_INVALID",
                               metric_status=H3MetricStatus.INVALID)
        if row.source_sha256 in hashes:
            return H3Scorecard(H3Status.INVALID, "DUPLICATE_SOURCE_HASH",
                               metric_status=H3MetricStatus.INVALID)
        hashes.add(row.source_sha256)
        synthetic_only |= row.evidence_class is H3EvidenceClass.SYNTHETIC_ONLY

    formats = tuple(H3FileFormat)
    strata: list[H3Stratum] = []
    for file_format in formats:
        rows = tuple(row for row in evidence if row.file_format is file_format)
        if not rows:
            continue
        fields = tuple(field for row in rows for field in row.fields if field.material)
        strata.append(H3Stratum(
            file_format=file_format,
            document_count=len(rows),
            material_field_count=len(fields),
            corrected_material_field_count=sum(field.semantic_correction for field in fields),
            unreviewed_material_field_count=sum(not field.human_reviewed for field in fields),
            confidently_wrong_unreviewed_approved_count=sum(
                field.confidently_wrong and field.approved and not field.human_reviewed
                for field in fields
            ),
        ))

    material_count = sum(item.material_field_count for item in strata)
    corrected_count = sum(item.corrected_material_field_count for item in strata)
    unreviewed_count = sum(item.unreviewed_material_field_count for item in strata)
    unsafe_count = sum(item.confidently_wrong_unreviewed_approved_count for item in strata)
    if material_count == 0:
        return H3Scorecard(H3Status.NOT_READY, "NO_MATERIAL_FIELDS", H3_SAMPLE_SIZE,
                           strata=tuple(strata), metric_status=H3MetricStatus.NOT_READY)
    if synthetic_only:
        acceptance_status, code = H3Status.NOT_ACCEPTANCE, "SYNTHETIC_ONLY_EVIDENCE"
    elif any(row.test_lane_run_id is None for row in evidence):
        acceptance_status, code = H3Status.NOT_ACCEPTANCE, "TEST_LANE_EVIDENCE_MISSING"
    elif receipt_verifier is None:
        acceptance_status, code = H3Status.NOT_ACCEPTANCE, "TEST_LANE_EVIDENCE_UNVERIFIED"
    else:
        try:
            receipt_verified = receipt_verifier.verify(
                _source_run_pairs(evidence),
                _evidence_sha256(evidence),
            ) is True
        except Exception:  # noqa: BLE001 - an unavailable verifier cannot establish acceptance
            receipt_verified = False
        if receipt_verified:
            if unreviewed_count:
                acceptance_status, code = H3Status.FAIL, "MATERIAL_FIELD_NOT_HUMAN_REVIEWED"
            elif unsafe_count:
                acceptance_status, code = H3Status.FAIL, "CONFIDENTLY_WRONG_FIELD_APPROVED_UNREVIEWED"
            elif corrected_count * 10 > material_count:
                acceptance_status, code = H3Status.FAIL, "CORRECTED_FIELD_RATE_OVER_10_PERCENT"
            else:
                acceptance_status, code = H3Status.PASS, "H3_THRESHOLD_MET"
        else:
            acceptance_status, code = H3Status.NOT_ACCEPTANCE, "TEST_LANE_EVIDENCE_UNVERIFIED"

    if unreviewed_count:
        metric_status = H3MetricStatus.FAIL
    elif unsafe_count:
        metric_status = H3MetricStatus.FAIL
    elif corrected_count * 10 > material_count:
        metric_status = H3MetricStatus.FAIL
    else:
        metric_status = H3MetricStatus.PASS
    return H3Scorecard(acceptance_status, code, H3_SAMPLE_SIZE, material_count, corrected_count,
                       unreviewed_count, unsafe_count, tuple(strata), metric_status)


def _invoice_valid(row: H3InvoiceEvidence) -> bool:
    try:
        if (type(row.source_sha256) is not str or _SHA256.fullmatch(row.source_sha256) is None
                or type(row.file_format) is not H3FileFormat
                or type(row.evidence_class) is not H3EvidenceClass
                or not _aware(row.frozen_at) or not _aware(row.extraction_started_at)
                or row.frozen_at >= row.extraction_started_at
                or (row.test_lane_run_id is not None
                    and (type(row.test_lane_run_id) is not str
                         or not row.test_lane_run_id.strip()))
                or type(row.fields) is not tuple
                or any(not _field_valid(field) for field in row.fields)):
            return False
    except Exception:  # noqa: BLE001 - malformed slotted evidence must fail closed
        return False
    return True


def _source_run_pairs(
    evidence: tuple[H3InvoiceEvidence, ...],
) -> tuple[tuple[str, str], ...]:
    """Keep each frozen source bound to the run that processed that source."""
    pairs: list[tuple[str, str]] = []
    for row in evidence:
        run_id = row.test_lane_run_id
        if run_id is not None:
            pairs.append((row.source_sha256, run_id))
    return tuple(pairs)


def _evidence_sha256(evidence: tuple[H3InvoiceEvidence, ...]) -> str:
    """Digest every scorecard claim so a receipt must attest the exact scored payload.

    The digest deliberately excludes invoice contents: source hashes identify the frozen files,
    while the per-field booleans and run metadata bind the metric and review claims to the
    verifier's authenticated lane receipt.
    """
    payload = {
        "domain": "ERP_MCP/S17-06/H3_EVIDENCE/v1",
        "invoices": [
            {
                "source_sha256": row.source_sha256,
                "file_format": row.file_format.value,
                "frozen_at": row.frozen_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
                "extraction_started_at": row.extraction_started_at.astimezone(timezone.utc).isoformat(
                    timespec="microseconds"
                ),
                "evidence_class": row.evidence_class.value,
                "test_lane_run_id": row.test_lane_run_id,
                "fields": [
                    {
                        "material": field.material,
                        "semantic_correction": field.semantic_correction,
                        "confidently_wrong": field.confidently_wrong,
                        "human_reviewed": field.human_reviewed,
                        "approved": field.approved,
                    }
                    for field in row.fields
                ],
            }
            for row in evidence
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _field_valid(field: object) -> bool:
    if type(field) is not H3FieldEvidence:
        return False
    try:
        return all(type(value) is bool for value in (
            field.material, field.semantic_correction, field.confidently_wrong,
            field.human_reviewed, field.approved))
    except Exception:  # noqa: BLE001 - malformed slotted evidence must fail closed
        return False


def _aware(value: object) -> bool:
    return type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None
