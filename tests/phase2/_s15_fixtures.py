"""Shared fixtures of the S15 functional tests (independent of the production negative controls).

The baseline here is a hand-written, correct supplier-receipt draft; the tests distort it one
field at a time. Nothing in this module imports the S15 negative-control module.
"""
from __future__ import annotations

import dataclasses
from decimal import Decimal

from erp_mcp_s15.oracle import AMOUNT_PATH, RECEIPT_TYPING_TABLE, VAT_AMOUNT_PATH
from erp_mcp_s15.read_interface import ReferenceLookup, StoredDocument
from erp_mcp_s15.verifier import ExpectedReceipt

DOCUMENT_REF = "11111111-1111-4111-8111-111111111111"
CHANGE_ID = "22222222-2222-4222-8222-222222222222"
MANIFEST_HASH = "cd" * 32
DROP = object()  # remove a path from the stored mapping (value was not read)


def full_declared_types() -> dict[str, str]:
    """A complete writer type declaration (every oracle path, no divergence).

    Without a complete declaration the verifier cannot report VERIFIED (typing not checked).
    """
    return dict(RECEIPT_TYPING_TABLE.types_by_path())


ORGANIZATION = "aaaaaaaa-0000-4000-8000-000000000001"
COUNTERPARTY = "aaaaaaaa-0000-4000-8000-000000000002"
CONTRACT = "aaaaaaaa-0000-4000-8000-000000000003"
CURRENCY = "aaaaaaaa-0000-4000-8000-000000000004"
NOMENCLATURE = "aaaaaaaa-0000-4000-8000-000000000005"
OTHER_GUID = "bbbbbbbb-0000-4000-8000-0000000000ff"

REFERENCE_PATHS = {
    "header.organization": ("Organizations", ORGANIZATION),
    "header.counterparty": ("Counterparties", COUNTERPARTY),
    "header.contract": ("Contracts", CONTRACT),
    "header.currency": ("Currencies", CURRENCY),
    "line.nomenclature": ("Nomenclature", NOMENCLATURE),
}


def make_expected(*, includes_vat: bool = False, **value_overrides: object) -> ExpectedReceipt:
    values: dict[str, str] = {
        "header.organization": ORGANIZATION, "header.counterparty": COUNTERPARTY,
        "header.contract": CONTRACT, "header.currency": CURRENCY,
        "header.incoming_number": "00123", "header.incoming_date": "2026-03-10",
        "line.nomenclature": NOMENCLATURE, "line.quantity": "2", "line.price": "10",
        AMOUNT_PATH: "20", "line.vat_rate": "VAT20", VAT_AMOUNT_PATH: "1.82",
    }
    for key, val in value_overrides.items():
        path = key.replace("__", ".")
        if val is DROP:
            values.pop(path, None)
        else:
            values[path] = val  # type: ignore[assignment]
    return ExpectedReceipt(values=values, document_day="2026-03-11", change_id=CHANGE_ID,
                           manifest_hash=MANIFEST_HASH, includes_vat=includes_vat)


def make_stored(header: dict | None = None, line: dict | None = None, **doc: object
                ) -> StoredDocument:
    base_header: dict[str, object] = {
        "header.organization": ORGANIZATION, "header.counterparty": COUNTERPARTY,
        "header.contract": CONTRACT, "header.currency": CURRENCY,
        "header.incoming_number": "00123", "header.incoming_date": "2026-03-10T00:00:00",
    }
    base_line: dict[str, object] = {
        "line.nomenclature": NOMENCLATURE, "line.quantity": 2, "line.price": Decimal(10),
        AMOUNT_PATH: Decimal(20), "line.vat_rate": "VAT20",
        VAT_AMOUNT_PATH: Decimal("1.82"),
    }
    for target, over in ((base_header, header), (base_line, line)):
        for key, val in (over or {}).items():
            if val is DROP:
                target.pop(key, None)
            else:
                target[key] = val
    stored = StoredDocument(
        header=base_header, lines=(base_line,), own_date_text="2026-03-11T07:00:00",
        change_id=CHANGE_ID, change_hash=MANIFEST_HASH, posted=False, deletion_mark=False,
        includes_vat=False, total=Decimal("21.82"))
    return dataclasses.replace(stored, **doc) if doc else stored


class FakeReader:
    """Fake 1C read port; records every call, can inject read faults."""

    def __init__(self, document: StoredDocument | object | None = None, *,
                 lookups: dict[str, object] | None = None,
                 read_error: BaseException | None = None,
                 lookup_errors: dict[str, BaseException] | None = None) -> None:
        self.document = make_stored() if document is None else document
        self.lookups = lookups or {}
        self.read_error = read_error
        self.lookup_errors = lookup_errors or {}
        self.read_calls: list[str] = []
        self.lookup_calls: list[tuple[str, str]] = []

    def read_document(self, document_ref: str):
        self.read_calls.append(document_ref)
        if self.read_error is not None:
            raise self.read_error
        return self.document

    def lookup_reference(self, catalog: str, ref_text: str):
        self.lookup_calls.append((catalog, ref_text))
        if ref_text in self.lookup_errors:
            raise self.lookup_errors[ref_text]
        return self.lookups.get(ref_text, ReferenceLookup(True, False))


class ExplodingMapping(dict):
    """Stored header/line mapping whose ``get`` fails for chosen keys (an unexpected read fault)."""

    def __init__(self, data: dict, fail_on: dict[str, BaseException]) -> None:
        super().__init__(data)
        self.fail_on = fail_on

    def get(self, key, default=None):
        if key in self.fail_on:
            raise self.fail_on[key]
        return super().get(key, default)
