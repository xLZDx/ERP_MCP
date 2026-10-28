"""Negative-control set (S15, E15-5): known distortions as data plus a detector entry point.

Each control distorts a synthetic, otherwise correct baseline (a stored receipt, or an observed
movement multiset) and the detector checks that the verifier or the A<->B comparison reports a
red MISMATCH. No control may produce VERIFIED / MATCH. Each control carries a written note naming
the observable value that would differ if the guard were switched off; the guard is never
actually broken (no mutation runs). Movement-level controls run on synthetic fixtures only: no
real-1C movement read exists (S15 plan, A14). Output is machine verified, not accountant attested.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from .ab_compare import (
    ComparisonStatus,
    DiffItem,
    ExpectedDifferences,
    LaneSnapshot,
    compare_ab,
)
from .labels import LABEL_MACHINE_VERIFIED
from .oracle import AMOUNT_PATH, RECEIPT_TYPING_TABLE, VAT_AMOUNT_PATH
from .read_interface import ReadIncomplete, ReferenceLookup, StoredDocument
from .verifier import (
    SUPPORTED_SHAPE,
    ExpectedReceipt,
    VerificationStatus,
    verify_receipt,
)

__all__ = [
    "BASELINE_DOCUMENT_REF",
    "NEGATIVE_CONTROLS",
    "REQUIRED_CONTROL_IDS",
    "Control",
    "ControlOutcome",
    "ControlReport",
    "Movement",
    "MovementOp",
    "Mutation",
    "baseline_expected_receipt",
    "baseline_stored_document",
    "run_all",
    "run_control",
]

BASELINE_DOCUMENT_REF = "00000000-0000-4000-8000-0000000000d1"
_GUID = "00000000-0000-4000-8000-0000000000{:02x}"
_CHANGE_ID = "00000000-0000-4000-8000-0000000000c1"
_MANIFEST_HASH = "ab" * 32


@dataclass(frozen=True, slots=True)
class Mutation:
    """Field-level distortion: ``target`` is header, line, doc or lookup (key = path / attribute)."""

    target: str
    key: str
    value: object


@dataclass(frozen=True, slots=True)
class Movement:
    registrar: str
    period: str
    debit: str
    credit: str
    counterparty: str
    amount: str

    def as_item(self) -> DiffItem:
        key = (f"{self.registrar}|{self.period}|{self.debit}|{self.credit}|"
               f"{self.counterparty}")
        return DiffItem("movement", key, self.amount)


@dataclass(frozen=True, slots=True)
class MovementOp:
    """Movement-level distortion: replace (part, value), drop, duplicate, swap_dt_kt, append."""

    op: str
    index: int = 0
    part: str = ""
    value: object = None


@dataclass(frozen=True, slots=True)
class Control:
    control_id: str
    group: str  # "plan" or "s14_fact"
    description: str
    observable_note: str  # the observable value that would differ if the guard were off
    mutations: tuple[Mutation, ...] = ()
    movement_ops: tuple[MovementOp, ...] = ()

    @property
    def kind(self) -> str:
        return "movement" if self.movement_ops else "field"


def _ref(n: int) -> str:
    return _GUID.format(n)


def baseline_expected_receipt() -> ExpectedReceipt:
    return ExpectedReceipt(
        values={
            "header.organization": _ref(1), "header.counterparty": _ref(2),
            "header.contract": _ref(3), "header.currency": _ref(4),
            "header.incoming_number": "00123", "header.incoming_date": "2026-01-14",
            "line.nomenclature": _ref(5), "line.quantity": "1", "line.price": "20",
            AMOUNT_PATH: "20", "line.vat_rate": "VAT20", VAT_AMOUNT_PATH: "1.82",
        },
        document_day="2026-01-15", change_id=_CHANGE_ID, manifest_hash=_MANIFEST_HASH,
        includes_vat=False)


def baseline_stored_document() -> StoredDocument:
    return StoredDocument(
        header={
            "header.organization": _ref(1), "header.counterparty": _ref(2),
            "header.contract": _ref(3), "header.currency": _ref(4),
            "header.incoming_number": "00123", "header.incoming_date": "2026-01-14T00:00:00",
        },
        lines=({
            "line.nomenclature": _ref(5), "line.quantity": 1, "line.price": Decimal(20),
            AMOUNT_PATH: Decimal(20), "line.vat_rate": "VAT20",
            VAT_AMOUNT_PATH: Decimal("1.82"),
        },),
        own_date_text="2026-01-15T07:00:00", change_id=_CHANGE_ID, change_hash=_MANIFEST_HASH,
        posted=False, deletion_mark=False, includes_vat=False, total=Decimal("21.82"))


class _SyntheticReader:
    def __init__(self, document: StoredDocument, lookups: Mapping[str, ReferenceLookup]) -> None:
        self._document = document
        self._lookups = lookups

    def read_document(self, document_ref: str) -> StoredDocument:
        if document_ref != BASELINE_DOCUMENT_REF:
            raise ReadIncomplete
        return self._document

    def lookup_reference(self, catalog: str, ref_text: str) -> ReferenceLookup:
        return self._lookups.get(ref_text, ReferenceLookup(True, False))


def _apply_field(control: Control) -> _SyntheticReader:
    document = baseline_stored_document()
    header = dict(document.header)
    line = dict(document.lines[0])
    lookups: dict[str, ReferenceLookup] = {}
    changes: dict[str, object] = {}
    for m in control.mutations:
        if m.target == "header":
            header[m.key] = m.value
        elif m.target == "line":
            line[m.key] = m.value
        elif m.target == "doc":
            changes[m.key] = m.value
        elif m.target == "lookup":
            lookups[m.key] = m.value  # type: ignore[assignment]
        else:
            raise ValueError("CONTROL_TARGET_INVALID")
    document = dataclasses.replace(document, header=header, lines=(line,), **changes)
    return _SyntheticReader(document, lookups)


# Baseline observed difference: one document, two movement lines, one balance delta.
_BASE_MOVEMENTS = (
    Movement("D1", "2026-01", "41", "521.1", "CP1", "20.00"),
    Movement("D1", "2026-01", "18", "521.1", "CP1", "1.82"),
)


def _baseline_items() -> list[DiffItem]:
    return ([DiffItem("document", "D1")] + [m.as_item() for m in _BASE_MOVEMENTS]
            + [DiffItem("balance", "521.1|CP1", "21.82")])


def _apply_movement(ops: tuple[MovementOp, ...]) -> list[DiffItem]:
    movements = list(_BASE_MOVEMENTS)
    extra: list[DiffItem] = []
    for op in ops:
        if op.op == "replace":
            movements[op.index] = dataclasses.replace(movements[op.index], **{op.part: op.value})
        elif op.op == "drop":
            del movements[op.index]
        elif op.op == "duplicate":
            movements.append(movements[op.index])
        elif op.op == "swap_dt_kt":
            m = movements[op.index]
            movements[op.index] = dataclasses.replace(m, debit=m.credit, credit=m.debit)
        elif op.op == "append":
            extra.append(op.value)  # type: ignore[arg-type]
        else:
            raise ValueError("CONTROL_OP_INVALID")
    return ([DiffItem("document", "D1")] + [m.as_item() for m in movements] + extra
            + [DiffItem("balance", "521.1|CP1", "21.82")])


_DATE = "header.incoming_date"
_EMPTY_LOOKUP = ReferenceLookup(False, None)

NEGATIVE_CONTROLS: tuple[Control, ...] = (
    # --- plan distortions (movement level, synthetic) ---
    Control("P01_WRONG_ACCOUNT", "plan", "Debit account differs on the first movement line",
            "movement key part 'debit' reads 60 instead of 41; the B-A signed multiset gains an"
            " unexpected item and loses the expected one",
            movement_ops=(MovementOp("replace", 0, "debit", "60"),)),
    Control("P02_WRONG_COUNTERPARTY", "plan", "Counterparty differs on the first movement line",
            "movement key part 'counterparty' reads CP2 instead of CP1",
            movement_ops=(MovementOp("replace", 0, "counterparty", "CP2"),)),
    Control("P03_WRONG_PERIOD", "plan", "Period differs on the first movement line",
            "movement key part 'period' reads 2026-02 instead of 2026-01",
            movement_ops=(MovementOp("replace", 0, "period", "2026-02"),)),
    Control("P04_MISSING_MOVEMENT_LINE", "plan", "One expected movement line is absent",
            "the count of movement items in B is 1 instead of 2 (signed surplus -1)",
            movement_ops=(MovementOp("drop", 1),)),
    Control("P05_SWAPPED_DT_KT", "plan", "Debit and credit are swapped on the first line",
            "movement key parts debit/credit read 521.1/41 instead of 41/521.1",
            movement_ops=(MovementOp("swap_dt_kt", 0),)),
    Control("P06_DISTORTED_AMOUNT", "plan", "Amount differs on the first movement line",
            "movement value reads 20.01 instead of 20.00",
            movement_ops=(MovementOp("replace", 0, "amount", "20.01"),)),
    Control("P07_EXTRA_DOCUMENT", "plan", "An additional unexpected document appears in B",
            "the number of 'document' items in B is 2 instead of 1",
            movement_ops=(MovementOp("append", value=DiffItem("document", "D2")),)),
    Control("P08_DUPLICATED_MOVEMENT_ROW", "plan",
            "An identical movement row is duplicated (a set compare would hide it)",
            "the multiset count of the first movement item is 2 instead of 1",
            movement_ops=(MovementOp("duplicate", 0),)),
    # --- S14-fact distortions (field level) ---
    Control("F01_EMPTY_ENUMERATION", "s14_fact", "Stored VAT-rate enumeration is empty",
            "line.vat_rate reads the empty text instead of the expected member name",
            mutations=(Mutation("line", "line.vat_rate", ""),)),
    Control("F02_EMPTY_DATE", "s14_fact", "Stored incoming date is the empty date",
            "header.incoming_date reads 0001-01-01T00:00:00 instead of 2026-01-14T00:00:00",
            mutations=(Mutation("header", _DATE, "0001-01-01T00:00:00"),)),
    Control("F03_DATE_SHIFT_ONE_DAY", "s14_fact", "Stored incoming date is shifted by one day",
            "header.incoming_date reads 2026-01-15T00:00:00 instead of 2026-01-14T00:00:00",
            mutations=(Mutation("header", _DATE, "2026-01-15T00:00:00"),)),
    Control("F04_OWN_DATE_SHIFT", "s14_fact", "The document's own calendar day is shifted",
            "document own date text starts with 2026-01-16 instead of 2026-01-15",
            mutations=(Mutation("doc", "own_date_text", "2026-01-16T07:00:00"),)),
    Control("F05_NON_RESOLVING_REFERENCE", "s14_fact", "A stored reference resolves to no element",
            "lookup of the nomenclature reference reports exists=False instead of True",
            mutations=(Mutation("lookup", _ref(5), _EMPTY_LOOKUP),)),
    Control("F06_DELETION_MARKED_REFERENCE", "s14_fact", "A referenced element is deletion-marked",
            "lookup of the counterparty reference reports deletion_mark=True instead of False",
            mutations=(Mutation("lookup", _ref(2), ReferenceLookup(True, True)),)),
    Control("F07_TOTAL_OFF_BY_VAT", "s14_fact", "Total equals the amount without the line VAT",
            "document total reads 20 instead of 21.82 (difference equals vat_amount 1.82)",
            mutations=(Mutation("doc", "total", Decimal(20)),)),
    Control("F08_POSTED_DRAFT", "s14_fact", "The draft is stored as posted",
            "document posted flag reads True instead of False",
            mutations=(Mutation("doc", "posted", True),)),
    Control("F09_DELETION_MARKED_DRAFT", "s14_fact", "The draft is stored as deletion-marked",
            "document deletion_mark flag reads True instead of False",
            mutations=(Mutation("doc", "deletion_mark", True),)),
    Control("F10_IDENTITY_TEXT_COERCED_TO_NUMBER", "s14_fact",
            "Identity text '00123' is stored as the number 123",
            "header.incoming_number reads the int 123 instead of the text 00123",
            mutations=(Mutation("header", "header.incoming_number", 123),)),
    Control("F11_MARKER_CHANGED", "s14_fact", "The stored change-id marker differs",
            "marker change_id reads a different GUID text than the approved one",
            mutations=(Mutation("doc", "change_id", _ref(0x99)),)),
)


@dataclass(frozen=True, slots=True)
class ControlOutcome:
    control_id: str
    kind: str
    status: str
    detected: bool
    note: str
    label: str = LABEL_MACHINE_VERIFIED


@dataclass(frozen=True, slots=True)
class ControlReport:
    baseline_ok: bool
    outcomes: tuple[ControlOutcome, ...]
    undetected: tuple[str, ...]
    all_detected: bool
    label: str = LABEL_MACHINE_VERIFIED
    # True only when every plan control (P01-P08) and fact control (F01-F11) id was run.
    covers_required_set: bool = False


def _movement_status(ops: tuple[MovementOp, ...]) -> str:
    empty = LaneSnapshot(True)
    observed = LaneSnapshot(True, tuple(_apply_movement(ops)))
    expected = ExpectedDifferences(added=tuple(_baseline_items()))
    return compare_ab(empty, empty, empty, observed, expected).status.value


def _field_status(control: Control) -> str:
    reader = _apply_field(control)
    # The synthetic writer declaration is the oracle table itself (no divergence by design);
    # without it the verifier can never report VERIFIED.
    return verify_receipt(reader, BASELINE_DOCUMENT_REF, baseline_expected_receipt(),
                          SUPPORTED_SHAPE,
                          writer_declared_types=RECEIPT_TYPING_TABLE.types_by_path()
                          ).status.value


def run_control(control: Control) -> ControlOutcome:
    """Apply one control; detected only when the check reports the red MISMATCH status."""
    if control.kind == "movement":
        status = _movement_status(control.movement_ops)
        red = ComparisonStatus.MISMATCH.value
    else:
        status = _field_status(control)
        red = VerificationStatus.MISMATCH.value
    return ControlOutcome(control.control_id, control.kind, status, status == red,
                          control.observable_note)


REQUIRED_CONTROL_IDS = frozenset(
    {f"P{n:02d}" for n in range(1, 9)} | {f"F{n:02d}" for n in range(1, 12)})


def _covers_required(outcomes: tuple[ControlOutcome, ...]) -> bool:
    prefixes = {o.control_id.split("_", 1)[0] for o in outcomes}
    return REQUIRED_CONTROL_IDS <= prefixes


def run_all(controls: tuple[Control, ...] = NEGATIVE_CONTROLS) -> ControlReport:
    """Run the pre-flight baseline and every control; no control may be VERIFIED / MATCH.

    ``all_detected`` also requires a non-empty outcome list that covers the whole required set
    (plan P01-P08 and fact F01-F11), so an empty or partial control set is never "all detected".
    """
    baseline_ok = (
        _field_status(Control("BASE", "plan", "", "")) == VerificationStatus.VERIFIED.value
        and _movement_status(()) == ComparisonStatus.MATCH.value)
    outcomes = tuple(run_control(c) for c in controls)
    undetected = tuple(o.control_id for o in outcomes if not o.detected)
    covers = _covers_required(outcomes)
    return ControlReport(baseline_ok, outcomes, undetected,
                         baseline_ok and bool(outcomes) and covers and not undetected,
                         covers_required_set=covers)
