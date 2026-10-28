"""Independent versioned oracle for the supplier-receipt draft (S15, E15-2).

The typing table below is a reviewed table of its own. It is NOT derived from the writer's
destination sets, and this module imports nothing from the writer, preview or normalization code.
The total rule takes the includes-VAT flag and the approved ``vat_amount`` as inputs and never
recomputes VAT (measured on the clone: the platform does not compute line VAT).

All values here are machine verified, not accountant attested. The property paths in the receipt
table are logical names (assumption: they match the payload property paths of the reviewed
binding set; the divergence check in the verifier is what detects a mismatch).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

__all__ = [
    "AMOUNT_PATH",
    "EMPTY_DATE_DAYS",
    "ORACLE_VERSION",
    "RECEIPT_TYPING_TABLE",
    "VAT_AMOUNT_PATH",
    "FieldRule",
    "FieldType",
    "Scope",
    "TypingTable",
    "expected_total",
    "own_date_matches",
    "value_matches",
]

# Changing this string changes the value recorded in every verification result.
ORACLE_VERSION = "s15-oracle-1"

AMOUNT_PATH = "line.amount"
VAT_AMOUNT_PATH = "line.vat_amount"

# Calendar days that 1C uses for the empty date; an expected date may never be one of them.
EMPTY_DATE_DAYS = frozenset({"0001-01-01", "0100-01-01"})

_DECIMAL_TEXT = re.compile(r"-?[0-9]+(\.[0-9]+)?\Z")
_ISO_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_DATE_SUFFIX = "T00:00:00"
_XML_DATETIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\Z")


class FieldType(str, Enum):
    NUMBER = "number"
    IDENTITY_TEXT = "identity_text"
    DATE = "date"
    ENUMERATION = "enumeration"
    REFERENCE = "reference"
    FLAG = "flag"


class Scope(str, Enum):
    HEADER = "header"
    LINE = "line"


@dataclass(frozen=True, slots=True)
class FieldRule:
    """One typed field; ``catalog`` is the expected catalog for references only."""

    path: str
    scope: Scope
    field_type: FieldType
    catalog: str | None = None

    def __post_init__(self) -> None:
        if (self.field_type is FieldType.REFERENCE) != (self.catalog is not None):
            raise ValueError("ORACLE_RULE_INVALID")


@dataclass(frozen=True, slots=True)
class TypingTable:
    rules: tuple[FieldRule, ...]

    def __post_init__(self) -> None:
        paths = [r.path for r in self.rules]
        if not self.rules or len(paths) != len(set(paths)):
            raise ValueError("ORACLE_TABLE_INVALID")

    def get(self, path: str) -> FieldRule | None:
        for rule in self.rules:
            if rule.path == path:
                return rule
        return None

    def types_by_path(self) -> dict[str, str]:
        return {r.path: r.field_type.value for r in self.rules}


# Reviewed typing of the supplier-receipt draft with one line (assumed logical paths).
RECEIPT_TYPING_TABLE = TypingTable((
    FieldRule("header.organization", Scope.HEADER, FieldType.REFERENCE, "Organizations"),
    FieldRule("header.counterparty", Scope.HEADER, FieldType.REFERENCE, "Counterparties"),
    FieldRule("header.contract", Scope.HEADER, FieldType.REFERENCE, "Contracts"),
    FieldRule("header.currency", Scope.HEADER, FieldType.REFERENCE, "Currencies"),
    FieldRule("header.incoming_number", Scope.HEADER, FieldType.IDENTITY_TEXT),
    FieldRule("header.incoming_date", Scope.HEADER, FieldType.DATE),
    FieldRule("line.nomenclature", Scope.LINE, FieldType.REFERENCE, "Nomenclature"),
    FieldRule("line.quantity", Scope.LINE, FieldType.NUMBER),
    FieldRule("line.price", Scope.LINE, FieldType.NUMBER),
    FieldRule(AMOUNT_PATH, Scope.LINE, FieldType.NUMBER),
    FieldRule("line.vat_rate", Scope.LINE, FieldType.ENUMERATION),
    FieldRule(VAT_AMOUNT_PATH, Scope.LINE, FieldType.NUMBER),
))


def _real_day(text: str) -> bool:
    """True for a YYYY-MM-DD text that is an existing calendar date."""
    if _ISO_DAY.fullmatch(text) is None:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _decimal_of(value: object) -> Decimal | None:
    if type(value) is float:
        number = Decimal(repr(value))
    elif type(value) is int:
        number = Decimal(value)
    elif type(value) is Decimal:
        number = value
    else:
        return None
    return number if number.is_finite() else None


def expected_total(amount_text: str, vat_amount_text: str, includes_vat: bool) -> str:
    """Expected document total: amount alone when VAT is included, otherwise amount plus VAT."""
    if (type(amount_text) is not str or type(vat_amount_text) is not str
            or type(includes_vat) is not bool
            or _DECIMAL_TEXT.fullmatch(amount_text) is None
            or _DECIMAL_TEXT.fullmatch(vat_amount_text) is None):
        raise ValueError("ORACLE_TOTAL_INPUT_INVALID")
    amount = Decimal(amount_text)
    total = amount if includes_vat else amount + Decimal(vat_amount_text)
    return format(total, "f")


def value_matches(rule: FieldRule, expected: object, stored: object) -> bool:
    """True when ``stored`` equals ``expected`` under the rule of the field type; no coercion.

    Dates, enumerations and references are compared as read text (XMLString date text, member
    name, canonical GUID text); numbers exactly as numbers; identity text as exact ``str``.
    """
    kind = rule.field_type
    if kind is FieldType.FLAG:
        return type(expected) is bool and stored is expected
    if type(expected) is not str:
        return False
    if kind is FieldType.NUMBER:
        if _DECIMAL_TEXT.fullmatch(expected) is None:
            return False
        found = _decimal_of(stored)
        return found is not None and found == Decimal(expected)
    if kind is FieldType.IDENTITY_TEXT:
        return type(stored) is str and bool(expected) and stored == expected
    if kind is FieldType.DATE:
        if not _real_day(expected) or expected in EMPTY_DATE_DAYS:
            return False
        return type(stored) is str and stored == expected + _DATE_SUFFIX
    # ENUMERATION and REFERENCE: non-empty text identity.
    return bool(expected) and type(stored) is str and stored == expected


def own_date_matches(expected_day: str, stored_text: object) -> bool:
    """The document's own date is compared by calendar day only (the time of day is normalized).

    Both sides must be real calendar dates; the stored text must be the full XMLString form
    ``YYYY-MM-DDTHH:MM:SS`` (trailing garbage or an impossible date or time is red).
    """
    if (type(expected_day) is not str or not _real_day(expected_day)
            or expected_day in EMPTY_DATE_DAYS or type(stored_text) is not str
            or _XML_DATETIME.fullmatch(stored_text) is None
            or not _real_day(stored_text[:10])):
        return False
    hour, minute, second = (int(part) for part in stored_text[11:].split(":"))
    if hour > 23 or minute > 59 or second > 59:
        return False
    return stored_text[:10] == expected_day
