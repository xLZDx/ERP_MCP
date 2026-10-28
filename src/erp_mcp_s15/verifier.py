"""Receipt CREATE_DRAFT verifier (S15, E15-1): expectation versus stored fact.

Only the one-line receipt CREATE_DRAFT shape is supported; every other shape returns
``UNSUPPORTED_SHAPE``. The stored document is read through an injected ``ReceiptReader`` and
compared against the independent oracle. Findings carry field paths and codes, never values.
Output is machine verified, not accountant attested; it is not a production-readiness claim.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from .labels import LABEL_MACHINE_VERIFIED
from .oracle import (
    AMOUNT_PATH,
    ORACLE_VERSION,
    RECEIPT_TYPING_TABLE,
    VAT_AMOUNT_PATH,
    FieldRule,
    FieldType,
    Scope,
    TypingTable,
    expected_total,
    own_date_matches,
    value_matches,
)
from .read_interface import ReadIncomplete, ReceiptReader, ReferenceLookup, StoredDocument

__all__ = [
    "SUPPORTED_SHAPE",
    "ExpectedReceipt",
    "Finding",
    "OperationShape",
    "VerificationResult",
    "VerificationStatus",
    "verify_receipt",
]

_MISSING = object()


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNSUPPORTED_SHAPE = "UNSUPPORTED_SHAPE"
    TYPING_DIVERGENCE = "TYPING_DIVERGENCE"
    PARTIAL_UNVERIFIED = "PARTIAL_UNVERIFIED"


@dataclass(frozen=True, slots=True)
class OperationShape:
    operation: str
    document_kind: str
    line_count: int


SUPPORTED_SHAPE = OperationShape("CREATE_DRAFT", "RECEIPT", 1)


@dataclass(frozen=True, slots=True)
class ExpectedReceipt:
    """Approved values: ``values`` maps oracle paths to payload text (GUID, decimal, ISO day, ...)."""

    values: Mapping[str, str]
    document_day: str
    change_id: str
    manifest_hash: str
    includes_vat: bool


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    field_class: str
    code: str  # MISMATCH, EMPTY, NOT_RESOLVING, DELETION_MARKED, INCOMPLETE, EXPECTED_MISSING


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    oracle_version: str
    label: str
    findings: tuple[Finding, ...] = ()
    unverified_paths: tuple[str, ...] = ()


def _result(status: VerificationStatus, findings: list[Finding] | None = None,
            unverified: list[str] | None = None) -> VerificationResult:
    return VerificationResult(status, ORACLE_VERSION, LABEL_MACHINE_VERIFIED,
                              tuple(findings or ()), tuple(unverified or ()))


def _canonical_uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


class _Checker:
    def __init__(self, reader: ReceiptReader, stored: StoredDocument) -> None:
        self.reader = reader
        self.stored = stored
        self.findings: list[Finding] = []

    def add(self, path: str, field_class: str, code: str) -> None:
        self.findings.append(Finding(path, field_class, code))

    def field(self, rule: FieldRule, expected: str, source: Mapping[str, object]) -> None:
        stored = source.get(rule.path, _MISSING)
        if stored is _MISSING:
            self.add(rule.path, rule.field_type.value, "INCOMPLETE")
            return
        if not value_matches(rule, expected, stored):
            empty = stored is None or stored == ""
            self.add(rule.path, rule.field_type.value,
                     "EMPTY" if empty and rule.field_type in (
                         FieldType.ENUMERATION, FieldType.DATE, FieldType.REFERENCE)
                     else "MISMATCH")
            return
        if rule.field_type is FieldType.REFERENCE:
            self.reference(rule, expected)

    def reference(self, rule: FieldRule, ref_text: str) -> None:
        if not _canonical_uuid(ref_text):
            self.add(rule.path, "reference", "MISMATCH")
            return
        try:
            lookup = self.reader.lookup_reference(rule.catalog or "", ref_text)
        except ReadIncomplete:
            self.add(rule.path, "reference", "INCOMPLETE")
            return
        if type(lookup) is not ReferenceLookup:
            self.add(rule.path, "reference", "INCOMPLETE")
        elif not lookup.exists:
            self.add(rule.path, "reference", "NOT_RESOLVING")
        elif lookup.deletion_mark is None:
            self.add(rule.path, "reference", "INCOMPLETE")
        elif lookup.deletion_mark is not False:
            self.add(rule.path, "reference", "DELETION_MARKED")

    def flag_false(self, path: str, value: object) -> None:
        if value is None:
            self.add(path, "flag", "INCOMPLETE")
        elif value is not False:
            self.add(path, "flag", "MISMATCH")


def _check_document(checker: _Checker, expected: ExpectedReceipt, table: TypingTable
                    ) -> list[str]:
    """Run every comparison; returns the expected paths the oracle table does not cover."""
    stored = checker.stored
    uncovered: list[str] = []
    for path, value in expected.values.items():
        if table.get(path) is None:
            uncovered.append(path)
    if len(stored.lines) != 1:
        checker.add("lines", "rows", "MISMATCH")
    for rule in table.rules:
        value = expected.values.get(rule.path)
        if value is None:
            checker.add(rule.path, rule.field_type.value, "EXPECTED_MISSING")
            continue
        if rule.scope is Scope.HEADER:
            checker.field(rule, value, stored.header)
        elif len(stored.lines) == 1:
            checker.field(rule, value, stored.lines[0])
    # Markers: exact text.
    for path, expected_text, found in (
            ("marker.change_id", expected.change_id, stored.change_id),
            ("marker.change_hash", expected.manifest_hash, stored.change_hash)):
        if found is None:
            checker.add(path, "marker", "EMPTY")
        elif type(found) is not str or found != expected_text:
            checker.add(path, "marker", "MISMATCH")
    # The document's own date: calendar day only.
    if stored.own_date_text is None:
        checker.add("document.date", "date", "EMPTY")
    elif not own_date_matches(expected.document_day, stored.own_date_text):
        checker.add("document.date", "date", "MISMATCH")
    checker.flag_false("document.posted", stored.posted)
    checker.flag_false("document.deletion_mark", stored.deletion_mark)
    if stored.includes_vat is None:
        checker.add("document.includes_vat", "flag", "INCOMPLETE")
    elif stored.includes_vat is not expected.includes_vat:
        checker.add("document.includes_vat", "flag", "MISMATCH")
    # Total: the oracle rule, with the approved vat_amount and the flag as inputs.
    amount = expected.values.get(AMOUNT_PATH)
    vat = expected.values.get(VAT_AMOUNT_PATH)
    if amount is not None and vat is not None:
        try:
            total_rule = FieldRule("document.total", Scope.HEADER, FieldType.NUMBER)
            wanted = expected_total(amount, vat, expected.includes_vat)
        except ValueError:
            checker.add("document.total", "number", "EXPECTED_MISSING")
        else:
            if stored.total is None:
                checker.add("document.total", "number", "INCOMPLETE")
            elif not value_matches(total_rule, wanted, stored.total):
                checker.add("document.total", "number", "MISMATCH")
    else:
        checker.add("document.total", "number", "EXPECTED_MISSING")
    return uncovered


def verify_receipt(
        reader: ReceiptReader, document_ref: str, expected: ExpectedReceipt,
        shape: OperationShape, *, writer_declared_types: Mapping[str, str] | None = None,
        writer_unverified_paths: tuple[str, ...] = (),
        table: TypingTable = RECEIPT_TYPING_TABLE) -> VerificationResult:
    """Verify one stored receipt draft; any non-VERIFIED status is a failure to verify.

    ``writer_declared_types`` optionally maps paths to type names as the writer declares them
    (the caller derives it; this module never imports the writer). Any path whose type differs
    from the oracle table is ``TYPING_DIVERGENCE`` (red). ``writer_unverified_paths`` that the
    oracle does not cover are reported and prevent VERIFIED.
    """
    if shape != SUPPORTED_SHAPE:
        return _result(VerificationStatus.UNSUPPORTED_SHAPE)
    if writer_declared_types is not None:
        oracle_types = table.types_by_path()
        divergent = [Finding(p, oracle_types.get(p, "unknown"), "TYPING_DIVERGENCE")
                     for p, t in writer_declared_types.items() if oracle_types.get(p) != t]
        if divergent:
            return _result(VerificationStatus.TYPING_DIVERGENCE, divergent)
    try:
        stored = reader.read_document(document_ref)
    except ReadIncomplete:
        return _result(VerificationStatus.INCONCLUSIVE, [Finding("document", "read", "INCOMPLETE")])
    except Exception:  # noqa: BLE001 - any failed read is incomplete data, never a pass
        return _result(VerificationStatus.INCONCLUSIVE, [Finding("document", "read", "INCOMPLETE")])
    if type(stored) is not StoredDocument:
        return _result(VerificationStatus.INCONCLUSIVE, [Finding("document", "read", "INCOMPLETE")])
    checker = _Checker(reader, stored)
    try:
        uncovered = _check_document(checker, expected, table)
    except Exception:  # noqa: BLE001 - an unexpected read-side failure is incomplete, not a pass
        checker.add("document", "read", "INCOMPLETE")
        uncovered = []
    unverified = sorted(set(uncovered) | {p for p in writer_unverified_paths
                                          if table.get(p) is None})
    red = [f for f in checker.findings if f.code != "INCOMPLETE"]
    if red:
        return _result(VerificationStatus.MISMATCH, checker.findings, unverified)
    if checker.findings:
        return _result(VerificationStatus.INCONCLUSIVE, checker.findings, unverified)
    if unverified:
        return _result(VerificationStatus.PARTIAL_UNVERIFIED, [], unverified)
    return _result(VerificationStatus.VERIFIED)
