"""Value-free, fail-closed scorecard for the frozen S17 H3 evaluation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

__all__ = [
    "H3EvidenceClass", "H3FileFormat", "H3FieldEvidence", "H3InvoiceEvidence",
    "H3Scorecard", "H3Status", "H3Stratum", "evaluate_h3",
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
    status: H3Status
    code: str
    document_count: int = 0
    material_field_count: int = 0
    corrected_material_field_count: int = 0
    unreviewed_material_field_count: int = 0
    confidently_wrong_unreviewed_approved_count: int = 0
    strata: tuple[H3Stratum, ...] = ()


def evaluate_h3(evidence: object) -> H3Scorecard:
    """Evaluate counts only; never retain values, filenames, actors, or document content."""
    if type(evidence) is not tuple or any(type(row) is not H3InvoiceEvidence for row in evidence):
        return H3Scorecard(H3Status.INVALID, "EVIDENCE_SHAPE_INVALID")
    if len(evidence) != H3_SAMPLE_SIZE:
        return H3Scorecard(H3Status.NOT_READY, "SAMPLE_SIZE_NOT_30", document_count=len(evidence))
    hashes: set[str] = set()
    synthetic_only = False
    for row in evidence:
        if not _invoice_valid(row):
            return H3Scorecard(H3Status.INVALID, "INVOICE_EVIDENCE_INVALID")
        if row.source_sha256 in hashes:
            return H3Scorecard(H3Status.INVALID, "DUPLICATE_SOURCE_HASH")
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
                           strata=tuple(strata))
    if synthetic_only:
        status, code = H3Status.NOT_ACCEPTANCE, "SYNTHETIC_ONLY_EVIDENCE"
    elif any(row.test_lane_run_id is None for row in evidence):
        status, code = H3Status.NOT_ACCEPTANCE, "TEST_LANE_EVIDENCE_MISSING"
    elif unreviewed_count:
        status, code = H3Status.FAIL, "MATERIAL_FIELD_NOT_HUMAN_REVIEWED"
    elif unsafe_count:
        status, code = H3Status.FAIL, "CONFIDENTLY_WRONG_FIELD_APPROVED_UNREVIEWED"
    elif corrected_count * 10 > material_count:
        status, code = H3Status.FAIL, "CORRECTED_FIELD_RATE_OVER_10_PERCENT"
    else:
        status, code = H3Status.PASS, "H3_THRESHOLD_MET"
    return H3Scorecard(status, code, H3_SAMPLE_SIZE, material_count, corrected_count,
                       unreviewed_count, unsafe_count, tuple(strata))


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
