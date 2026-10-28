"""Receipt CREATE_DRAFT verifier (S15, E15-1): expectation versus stored fact.

Only the one-line receipt CREATE_DRAFT shape is supported; every other shape returns
``UNSUPPORTED_SHAPE``. The stored document is read through an injected ``ReceiptReader`` and
compared against the independent oracle. Findings carry field paths and codes, never values.
Output is machine verified, not accountant attested; it is not a production-readiness claim.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
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
    # MISMATCH, EMPTY, NOT_RESOLVING, DELETION_MARKED, INCOMPLETE, EXPECTED_MISSING, READ_ERROR
    # (READ_ERROR: a read raised something other than ReadIncomplete; inconclusive, not red).
    code: str
    detail: str = ""  # exception class name for READ_ERROR only, never a value


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    oracle_version: str
    label: str
    findings: tuple[Finding, ...] = ()
    unverified_paths: tuple[str, ...] = ()
    # True only when writer_declared_types covered every oracle table path and none diverged.
    typing_checked: bool = False


def _result(status: VerificationStatus, findings: list[Finding] | None = None,
            unverified: list[str] | None = None, typing_checked: bool = False
            ) -> VerificationResult:
    return VerificationResult(status, ORACLE_VERSION, LABEL_MACHINE_VERIFIED,
                              tuple(findings or ()), tuple(unverified or ()), typing_checked)


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

    def add(self, path: str, field_class: str, code: str, detail: str = "") -> None:
        self.findings.append(Finding(path, field_class, code, detail))

    def guard(self, path: str, field_class: str, check: Callable[[], None]) -> None:
        """Run one independent check; a failure becomes a finding and never skips the others."""
        try:
            check()
        except ReadIncomplete:
            self.add(path, field_class, "INCOMPLETE")
        except Exception as exc:  # noqa: BLE001 - one failed check must not skip the rest
            self.add(path, field_class, "READ_ERROR", type(exc).__name__)

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
        except Exception as exc:  # noqa: BLE001 - class name only
            self.add(rule.path, "reference", "READ_ERROR", type(exc).__name__)
            return
        if type(lookup) is not ReferenceLookup or type(lookup.exists) is not bool:
            self.add(rule.path, "reference", "INCOMPLETE")
        elif lookup.exists is False:
            self.add(rule.path, "reference", "NOT_RESOLVING")
        elif type(lookup.deletion_mark) is not bool:
            self.add(rule.path, "reference", "INCOMPLETE")
        elif lookup.deletion_mark is True:
            self.add(rule.path, "reference", "DELETION_MARKED")

    def flag_false(self, path: str, value: object) -> None:
        if value is None:
            self.add(path, "flag", "INCOMPLETE")
        elif value is not False:
            self.add(path, "flag", "MISMATCH")


def _check_document(checker: _Checker, expected: ExpectedReceipt, table: TypingTable
                    ) -> list[str]:
    """Run every comparison (each reference field independently guarded); returns the expected
    paths the oracle table does not cover."""
    stored = checker.stored
    uncovered: list[str] = []
    for path in expected.values:
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
            checker.guard(rule.path, rule.field_type.value,
                          lambda r=rule, v=value: checker.field(r, v, stored.header))
        elif len(stored.lines) == 1:
            checker.guard(rule.path, rule.field_type.value,
                          lambda r=rule, v=value: checker.field(r, v, stored.lines[0]))
    # Markers: exact text; an empty or non-text expected value is EXPECTED_MISSING.
    for path, expected_text, found in (
            ("marker.change_id", expected.change_id, stored.change_id),
            ("marker.change_hash", expected.manifest_hash, stored.change_hash)):
        if type(expected_text) is not str or not expected_text:
            checker.add(path, "marker", "EXPECTED_MISSING")
        elif found is None:
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

    ``writer_declared_types`` maps paths to type names as the writer declares them (the caller
    derives it; this module never imports the writer). Any path whose type differs from the
    oracle table is ``TYPING_DIVERGENCE`` (red). When it is omitted or does not cover every
    oracle table path the typing was not checked: the result is at best ``PARTIAL_UNVERIFIED``
    and ``typing_checked`` is False. ``writer_unverified_paths`` that the oracle does not cover
    are reported and prevent VERIFIED. READ_ERROR (a read raised something other than
    ``ReadIncomplete``) is inconclusive like INCOMPLETE, never red and never a pass.
    """
    if shape != SUPPORTED_SHAPE:
        return _result(VerificationStatus.UNSUPPORTED_SHAPE)
    oracle_types = table.types_by_path()
    typing_checked = (writer_declared_types is not None
                      and all(p in writer_declared_types for p in oracle_types))
    if writer_declared_types is not None:
        divergent = [Finding(p, oracle_types.get(p, "unknown"), "TYPING_DIVERGENCE")
                     for p, t in writer_declared_types.items() if oracle_types.get(p) != t]
        if divergent:
            return _result(VerificationStatus.TYPING_DIVERGENCE, divergent,
                           typing_checked=False)
    try:
        stored = reader.read_document(document_ref)
    except ReadIncomplete:
        return _result(VerificationStatus.INCONCLUSIVE,
                       [Finding("document", "read", "INCOMPLETE")], typing_checked=typing_checked)
    except Exception as exc:  # noqa: BLE001 - any failed read is incomplete data, never a pass
        return _result(VerificationStatus.INCONCLUSIVE,
                       [Finding("document", "read", "READ_ERROR", type(exc).__name__)],
                       typing_checked=typing_checked)
    if type(stored) is not StoredDocument:
        return _result(VerificationStatus.INCONCLUSIVE,
                       [Finding("document", "read", "INCOMPLETE")], typing_checked=typing_checked)
    checker = _Checker(reader, stored)
    try:
        uncovered = _check_document(checker, expected, table)
    except Exception as exc:  # noqa: BLE001 - an unexpected failure is incomplete, not a pass
        checker.add("document", "read", "READ_ERROR", type(exc).__name__)
        uncovered = []
    unverified = set(uncovered) | {p for p in writer_unverified_paths if table.get(p) is None}
    if not typing_checked:
        declared = writer_declared_types or {}
        unverified |= {p for p in oracle_types if p not in declared}
    unverified_sorted = sorted(unverified)
    red = [f for f in checker.findings if f.code not in ("INCOMPLETE", "READ_ERROR")]
    if red:
        return _result(VerificationStatus.MISMATCH, checker.findings, unverified_sorted,
                       typing_checked)
    if checker.findings:
        return _result(VerificationStatus.INCONCLUSIVE, checker.findings, unverified_sorted,
                       typing_checked)
    if unverified_sorted or not typing_checked:
        return _result(VerificationStatus.PARTIAL_UNVERIFIED, [], unverified_sorted,
                       typing_checked)
    return _result(VerificationStatus.VERIFIED, typing_checked=True)
