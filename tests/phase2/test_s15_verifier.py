"""S15 epic E15-1: receipt CREATE_DRAFT verifier (stored fact versus oracle expectation)."""
from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from erp_mcp_s15.labels import LABEL_MACHINE_VERIFIED
from erp_mcp_s15.read_interface import ReadIncomplete, ReferenceLookup
from erp_mcp_s15.verifier import (
    SUPPORTED_SHAPE,
    Finding,
    OperationShape,
    VerificationStatus,
    verify_receipt,
)
from tests.phase2._s15_fixtures import (
    COUNTERPARTY,
    DOCUMENT_REF,
    DROP,
    NOMENCLATURE,
    ORGANIZATION,
    OTHER_GUID,
    REFERENCE_PATHS,
    FakeReader,
    make_expected,
    make_stored,
)

V = VerificationStatus


def run(reader=None, expected=None, shape=SUPPORTED_SHAPE, **kw):
    reader = FakeReader() if reader is None else reader
    return verify_receipt(reader, DOCUMENT_REF, expected or make_expected(), shape, **kw)


def paths(result):
    return {f.path for f in result.findings}


# --- happy path ----------------------------------------------------------------------------

def test_matching_document_is_verified_with_label_version_and_no_findings():
    reader = FakeReader()
    result = run(reader)
    assert result.status is V.VERIFIED
    assert result.findings == () and result.unverified_paths == ()
    assert result.label == LABEL_MACHINE_VERIFIED
    assert "not accountant attested" in result.label
    assert reader.read_calls == [DOCUMENT_REF]


def test_every_reference_is_resolved_in_its_expected_catalog():
    reader = FakeReader()
    run(reader)
    assert sorted(reader.lookup_calls) == sorted(
        (catalog, ref) for catalog, ref in REFERENCE_PATHS.values())


def test_numeric_stored_representations_are_all_accepted():
    stored = make_stored(line={"line.quantity": 2.0, "line.price": 10,
                               "line.amount": 20.0, "line.vat_amount": 1.82})
    assert run(FakeReader(stored)).status is V.VERIFIED


# --- assertion 1: shapes --------------------------------------------------------------------

@pytest.mark.parametrize("shape", [
    OperationShape("POST", "RECEIPT", 1),
    OperationShape("UNPOST", "RECEIPT", 1),
    OperationShape("CREATE_DRAFT", "RECEIPT", 2),
    OperationShape("CREATE_DRAFT", "RECEIPT", 0),
    OperationShape("CREATE_DRAFT", "INVOICE", 1),
    OperationShape("UPDATE_DRAFT", "RECEIPT", 1),
], ids=["post", "unpost", "multi_line", "zero_lines", "other_document", "update"])
def test_unsupported_shapes_are_never_verified_and_nothing_is_read(shape):
    reader = FakeReader()  # a perfectly matching document: only the shape can refuse it
    result = run(reader, shape=shape)
    assert result.status is V.UNSUPPORTED_SHAPE
    assert result.status is not V.VERIFIED
    assert reader.read_calls == [] and reader.lookup_calls == []
    assert result.label == LABEL_MACHINE_VERIFIED


# --- assertion 2: every field class ----------------------------------------------------------

FIELD_CASES = [
    # (id, header override, line override, expected finding path, class)
    ("number_amount", {}, {"line.amount": Decimal(21)}, "line.amount", "number"),
    ("number_quantity", {}, {"line.quantity": 3}, "line.quantity", "number"),
    ("number_as_text", {}, {"line.price": "10"}, "line.price", "number"),
    ("number_bool", {}, {"line.quantity": True}, "line.quantity", "number"),
    ("number_vat_amount", {}, {"line.vat_amount": Decimal(0)}, "line.vat_amount", "number"),
    ("identity_coerced_to_int", {"header.incoming_number": 123}, {},
     "header.incoming_number", "identity_text"),
    ("identity_zero_stripped", {"header.incoming_number": "123"}, {},
     "header.incoming_number", "identity_text"),
    ("identity_empty", {"header.incoming_number": ""}, {},
     "header.incoming_number", "identity_text"),
    ("date_shift_forward", {"header.incoming_date": "2026-03-11T00:00:00"}, {},
     "header.incoming_date", "date"),
    ("date_shift_back", {"header.incoming_date": "2026-03-09T00:00:00"}, {},
     "header.incoming_date", "date"),
    ("date_empty_text", {"header.incoming_date": ""}, {}, "header.incoming_date", "date"),
    ("date_empty_1c_date", {"header.incoming_date": "0001-01-01T00:00:00"}, {},
     "header.incoming_date", "date"),
    ("date_time_of_day_changed", {"header.incoming_date": "2026-03-10T05:00:00"}, {},
     "header.incoming_date", "date"),
    ("date_no_time_part", {"header.incoming_date": "2026-03-10"}, {},
     "header.incoming_date", "date"),
    ("enum_other_member", {}, {"line.vat_rate": "VAT10"}, "line.vat_rate", "enumeration"),
    ("enum_empty", {}, {"line.vat_rate": ""}, "line.vat_rate", "enumeration"),
    ("reference_other_guid", {"header.organization": OTHER_GUID}, {},
     "header.organization", "reference"),
    ("reference_emptied", {"header.counterparty": None}, {}, "header.counterparty",
     "reference"),
    ("line_reference_other", {}, {"line.nomenclature": OTHER_GUID}, "line.nomenclature",
     "reference"),
]


@pytest.mark.parametrize("header,line,path,field_class",
                         [c[1:] for c in FIELD_CASES], ids=[c[0] for c in FIELD_CASES])
def test_a_stored_field_differing_from_the_oracle_is_red_on_exactly_that_field(
        header, line, path, field_class):
    result = run(FakeReader(make_stored(header=header, line=line)))
    assert result.status is V.MISMATCH
    assert result.status is not V.VERIFIED
    assert paths(result) == {path}
    assert result.findings[0].field_class == field_class


@pytest.mark.parametrize("attr,value,path", [
    ("change_id", OTHER_GUID, "marker.change_id"),
    ("change_hash", "ef" * 32, "marker.change_hash"),
    ("change_hash", 12345, "marker.change_hash"),
    ("change_id", None, "marker.change_id"),
    ("change_hash", None, "marker.change_hash"),
])
def test_marker_mismatch_or_absence_is_red(attr, value, path):
    result = run(FakeReader(make_stored(**{attr: value})))
    assert result.status is V.MISMATCH
    assert paths(result) == {path}
    assert result.findings[0].field_class == "marker"


def test_each_expected_value_is_compared_against_the_oracle_not_the_other_way():
    # Expected number differs from what is stored: red on the number field.
    result = run(expected=make_expected(line__quantity="3"))
    assert result.status is V.MISMATCH
    assert paths(result) == {"line.quantity"}


def test_expected_value_missing_from_the_approved_set_is_red_not_skipped():
    result = run(expected=make_expected(line__price=DROP))
    assert result.status is V.MISMATCH
    assert Finding("line.price", "number", "EXPECTED_MISSING") in result.findings


def test_stored_line_count_other_than_one_is_red():
    base = make_stored()
    two = dataclasses.replace(base, lines=base.lines * 2)
    none = dataclasses.replace(base, lines=())
    for doc in (two, none):
        result = run(FakeReader(doc))
        assert result.status is V.MISMATCH
        assert Finding("lines", "rows", "MISMATCH") in result.findings


# --- assertion 3: dates -----------------------------------------------------------------------

@pytest.mark.parametrize("own", [
    "2026-03-11T00:00:00", "2026-03-11T07:00:00", "2026-03-11T23:59:59",
])
def test_document_own_date_ignores_time_of_day(own):
    assert run(FakeReader(make_stored(own_date_text=own))).status is V.VERIFIED


@pytest.mark.parametrize("own", [
    "2026-03-12T07:00:00", "2026-03-10T07:00:00", "2026-03-10T23:59:59",
    "0001-01-01T00:00:00", "", 20260311,
])
def test_document_own_date_shift_or_empty_is_red(own):
    result = run(FakeReader(make_stored(own_date_text=own)))
    assert result.status is V.MISMATCH
    assert paths(result) == {"document.date"}


def test_document_own_date_absent_is_red_with_empty_code():
    result = run(FakeReader(make_stored(own_date_text=None)))
    assert result.status is V.MISMATCH
    assert result.findings == (Finding("document.date", "date", "EMPTY"),)


def test_empty_date_and_empty_enumeration_report_the_empty_code():
    result = run(FakeReader(make_stored(header={"header.incoming_date": None},
                                        line={"line.vat_rate": ""})))
    assert result.status is V.MISMATCH
    assert {(f.path, f.code) for f in result.findings} == {
        ("header.incoming_date", "EMPTY"), ("line.vat_rate", "EMPTY")}


# --- assertion 4: enumerations and references --------------------------------------------------

def test_reference_not_resolving_is_red():
    reader = FakeReader(lookups={NOMENCLATURE: ReferenceLookup(False, None)})
    result = run(reader)
    assert result.status is V.MISMATCH
    assert result.findings == (Finding("line.nomenclature", "reference", "NOT_RESOLVING"),)


def test_reference_deletion_marked_is_red():
    reader = FakeReader(lookups={COUNTERPARTY: ReferenceLookup(True, True)})
    result = run(reader)
    assert result.status is V.MISMATCH
    assert result.findings == (Finding("header.counterparty", "reference", "DELETION_MARKED"),)


def test_reference_existence_is_checked_even_when_stored_equals_expected():
    # Stored text equals expected text, so only the lookup can reveal the phantom reference.
    reader = FakeReader(lookups={ORGANIZATION: ReferenceLookup(False, None)})
    assert run(reader).status is V.MISMATCH


def test_non_canonical_expected_guid_text_is_red_without_lookup():
    upper = ORGANIZATION.upper()
    reader = FakeReader(make_stored(header={"header.organization": upper}))
    result = run(reader, expected=make_expected(header__organization=upper))
    assert result.status is V.MISMATCH
    assert "header.organization" in paths(result)
    assert all(ref != upper for _, ref in reader.lookup_calls)


def test_non_guid_expected_reference_is_red():
    reader = FakeReader(make_stored(header={"header.organization": "not-a-guid"}))
    result = run(reader, expected=make_expected(header__organization="not-a-guid"))
    assert result.status is V.MISMATCH


# --- assertion 5: flags and totals --------------------------------------------------------------

@pytest.mark.parametrize("attr,path", [("posted", "document.posted"),
                                       ("deletion_mark", "document.deletion_mark")])
def test_posted_or_deletion_marked_draft_is_red(attr, path):
    result = run(FakeReader(make_stored(**{attr: True})))
    assert result.status is V.MISMATCH
    assert result.findings == (Finding(path, "flag", "MISMATCH"),)


@pytest.mark.parametrize("value", [1, "False", 0])
def test_flag_must_be_the_boolean_false(value):
    # 0 / "False" are not the boolean False; treating them as False would be a false pass.
    assert run(FakeReader(make_stored(posted=value))).status is V.MISMATCH


def test_total_off_by_the_vat_amount_is_red_when_vat_not_included():
    result = run(FakeReader(make_stored(total=Decimal(20))))
    assert result.status is V.MISMATCH
    assert result.findings == (Finding("document.total", "number", "MISMATCH"),)


def test_total_equal_to_amount_plus_vat_is_verified_and_when_flag_true_amount_alone():
    assert run(FakeReader(make_stored(total=Decimal("21.82")))).status is V.VERIFIED
    flagged = make_stored(includes_vat=True, total=Decimal(20))
    assert run(FakeReader(flagged), make_expected(includes_vat=True)).status is V.VERIFIED


def test_total_with_vat_included_flag_rejects_amount_plus_vat():
    flagged = make_stored(includes_vat=True, total=Decimal("21.82"))
    result = run(FakeReader(flagged), make_expected(includes_vat=True))
    assert result.status is V.MISMATCH
    assert paths(result) == {"document.total"}


def test_stored_includes_vat_flag_differing_from_approved_is_red():
    result = run(FakeReader(make_stored(includes_vat=True)))
    assert result.status is V.MISMATCH
    assert Finding("document.includes_vat", "flag", "MISMATCH") in result.findings


def test_unusable_vat_inputs_are_red_not_skipped():
    result = run(expected=make_expected(line__vat_amount="abc"))
    assert result.status is V.MISMATCH
    assert Finding("document.total", "number", "EXPECTED_MISSING") in result.findings


# --- assertion 6: INCONCLUSIVE fault injection on the read path ----------------------------------

INCONCLUSIVE_FINDING = Finding("document", "read", "INCOMPLETE")


@pytest.mark.parametrize("error", [ReadIncomplete(), RuntimeError("boom"), TimeoutError(),
                                   OSError("pipe")])
def test_failed_document_read_is_inconclusive(error):
    result = run(FakeReader(read_error=error))
    assert result.status is V.INCONCLUSIVE
    assert result.status is not V.VERIFIED
    assert result.findings == (INCONCLUSIVE_FINDING,)


@pytest.mark.parametrize("payload", [None, {}, "doc", object()])
def test_read_returning_a_non_document_is_inconclusive(payload):
    reader = FakeReader()
    reader.document = payload
    assert run(reader).status is V.INCONCLUSIVE


def test_failed_reference_lookup_is_inconclusive():
    result = run(FakeReader(lookup_errors={NOMENCLATURE: ReadIncomplete()}))
    assert result.status is V.INCONCLUSIVE
    assert result.findings == (Finding("line.nomenclature", "reference", "INCOMPLETE"),)


def test_unexpected_exception_in_lookup_is_inconclusive_not_a_crash_or_pass():
    result = run(FakeReader(lookup_errors={ORGANIZATION: RuntimeError("socket")}))
    assert result.status is V.INCONCLUSIVE


def test_lookup_returning_garbage_is_inconclusive():
    result = run(FakeReader(lookups={ORGANIZATION: None}))
    assert result.status is V.INCONCLUSIVE
    assert result.findings == (Finding("header.organization", "reference", "INCOMPLETE"),)


def test_lookup_with_unread_deletion_mark_is_inconclusive():
    result = run(FakeReader(lookups={ORGANIZATION: ReferenceLookup(True, None)}))
    assert result.status is V.INCONCLUSIVE


@pytest.mark.parametrize("header,line,path", [
    ({"header.currency": DROP}, {}, "header.currency"),
    ({"header.incoming_date": DROP}, {}, "header.incoming_date"),
    ({}, {"line.amount": DROP}, "line.amount"),
    ({}, {"line.vat_rate": DROP}, "line.vat_rate"),
])
def test_value_absent_from_the_read_is_inconclusive_not_empty(header, line, path):
    result = run(FakeReader(make_stored(header=header, line=line)))
    assert result.status is V.INCONCLUSIVE
    assert [(f.path, f.code) for f in result.findings] == [(path, "INCOMPLETE")]


@pytest.mark.parametrize("attr", ["posted", "deletion_mark", "includes_vat", "total"])
def test_unread_flags_or_total_are_inconclusive(attr):
    result = run(FakeReader(make_stored(**{attr: None})))
    assert result.status is V.INCONCLUSIVE
    assert result.status is not V.VERIFIED


def test_a_definite_mismatch_outranks_an_incomplete_read():
    stored = make_stored(posted=True, deletion_mark=None)
    result = run(FakeReader(stored))
    assert result.status is V.MISMATCH
    assert {f.code for f in result.findings} == {"MISMATCH", "INCOMPLETE"}


# --- output carries no values ----------------------------------------------------------------------

def test_findings_name_fields_and_codes_but_never_stored_or_expected_values():
    stored = make_stored(header={"header.incoming_number": 987654, "header.organization":
                                 OTHER_GUID}, line={"line.amount": Decimal("777.77")})
    result = run(FakeReader(stored))
    text = repr(result)
    for secret in ("987654", OTHER_GUID, "777.77", "00123", ORGANIZATION):
        assert secret not in text


# --- the verifier stays read-only and fresh ---------------------------------------------------------

def test_every_verification_reads_the_document_afresh():
    reader = FakeReader()
    run(reader)
    run(reader)
    assert reader.read_calls == [DOCUMENT_REF, DOCUMENT_REF]
