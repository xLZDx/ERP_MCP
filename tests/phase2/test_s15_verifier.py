"""S15 epic E15-1: receipt CREATE_DRAFT verifier (stored fact versus oracle expectation)."""
from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from erp_mcp_s15.labels import LABEL_MACHINE_VERIFIED
from erp_mcp_s15.oracle import RECEIPT_TYPING_TABLE
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
    ExplodingMapping,
    FakeReader,
    full_declared_types,
    make_expected,
    make_stored,
)

V = VerificationStatus


def run(reader=None, expected=None, shape=SUPPORTED_SHAPE, **kw):
    """Verify with a complete writer type declaration unless the caller passes its own.

    VERIFIED needs the typing to have been checked, so a plain call without a declaration can
    never be VERIFIED (see the typing_checked tests below).
    """
    reader = FakeReader() if reader is None else reader
    kw.setdefault("writer_declared_types", full_declared_types())
    return verify_receipt(reader, DOCUMENT_REF, expected or make_expected(), shape, **kw)


def paths(result):
    return {f.path for f in result.findings}


# --- happy path ----------------------------------------------------------------------------

def test_matching_document_is_verified_with_label_version_and_no_findings():
    reader = FakeReader()
    result = run(reader)
    assert result.status is V.VERIFIED
    assert result.findings == () and result.unverified_paths == ()
    assert result.typing_checked is True
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
    # Strict form: the full XMLString text and a real calendar date and time are required.
    "2026-03-11", "2026-03-11T07:00", "2026-03-11T07:00:00Z", "2026-03-11T07:00:00junk",
    "2026-03-11T07:00:00\n", "2026-03-11T24:00:00", "2026-03-11T07:60:00", "2026-03-11T07:00:60",
    "2026-02-30T07:00:00", "2026-13-11T07:00:00", "2026-3-11T07:00:00",
    chr(0xFF12) + "026-03-11T07:00:00",  # a non-ASCII digit is not a digit here
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

def test_incomplete_document_read_is_inconclusive_with_the_incomplete_code():
    result = run(FakeReader(read_error=ReadIncomplete()))
    assert result.status is V.INCONCLUSIVE
    assert result.status is not V.VERIFIED
    assert result.findings == (Finding("document", "read", "INCOMPLETE"),)


@pytest.mark.parametrize("error", [RuntimeError("boom"), TimeoutError(), OSError("pipe")])
def test_unexpected_document_read_failure_is_read_error_inconclusive_with_class_name_only(error):
    result = run(FakeReader(read_error=error))
    assert result.status is V.INCONCLUSIVE
    assert result.status is not V.VERIFIED
    assert result.findings == (Finding("document", "read", "READ_ERROR", type(error).__name__),)


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
    assert result.findings == (
        Finding("header.organization", "reference", "READ_ERROR", "RuntimeError"),)


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


# --- CR-388: empty or non-text expected markers are red, never a pass ----------------------------

@pytest.mark.parametrize("stored_equals_expected", [True, False],
                         ids=["stored_equal", "stored_real"])
@pytest.mark.parametrize("bad", ["", None, 123, b"abc"])
@pytest.mark.parametrize("field,stored_attr,path", [
    ("change_id", "change_id", "marker.change_id"),
    ("manifest_hash", "change_hash", "marker.change_hash"),
])
def test_empty_or_non_text_expected_marker_is_expected_missing(
        field, stored_attr, path, bad, stored_equals_expected):
    # An empty expected marker equal to an empty stored marker must NOT count as agreement.
    expected = dataclasses.replace(make_expected(), **{field: bad})
    stored = make_stored(**({stored_attr: bad} if stored_equals_expected else {}))
    result = run(FakeReader(stored), expected=expected)
    assert result.status is V.MISMATCH
    assert result.status is not V.VERIFIED
    assert result.findings == (Finding(path, "marker", "EXPECTED_MISSING"),)


# --- CR-388: strict own-date on both sides ---------------------------------------------------------

@pytest.mark.parametrize("day", ["2026-02-30", "2026-03-11T07:00:00", "", None, "0001-01-01",
                                 "0100-01-01", "2026-3-11", "26-03-11"])
def test_invalid_expected_document_day_is_red_even_if_the_stored_text_starts_with_it(day):
    expected = dataclasses.replace(make_expected(), document_day=day)
    stored_text = f"{day}T07:00:00" if isinstance(day, str) else "2026-03-11T07:00:00"
    result = run(FakeReader(make_stored(own_date_text=stored_text)), expected=expected)
    assert result.status is V.MISMATCH
    assert result.findings == (Finding("document.date", "date", "MISMATCH"),)


# --- CR-388: strict boolean reference lookups ---------------------------------------------------------

@pytest.mark.parametrize("lookup", [
    ReferenceLookup(1, False), ReferenceLookup("yes", False), ReferenceLookup(None, None),
    ReferenceLookup(True, 0), ReferenceLookup(True, 1), ReferenceLookup(True, "no"),
], ids=["exists_int", "exists_text", "exists_none", "mark_zero", "mark_one", "mark_text"])
def test_reference_lookup_with_non_bool_members_is_incomplete_never_a_pass(lookup):
    result = run(FakeReader(lookups={ORGANIZATION: lookup}))
    assert result.status is V.INCONCLUSIVE
    assert result.status is not V.VERIFIED
    assert result.findings == (Finding("header.organization", "reference", "INCOMPLETE"),)


def test_reference_lookup_exists_false_is_not_resolving_even_with_a_missing_mark():
    result = run(FakeReader(lookups={ORGANIZATION: ReferenceLookup(False, None)}))
    assert result.findings == (Finding("header.organization", "reference", "NOT_RESOLVING"),)


# --- CR-388: READ_ERROR code and per-check isolation ---------------------------------------------------

def test_read_error_finding_carries_the_exception_class_name_only_never_the_message():
    reader = FakeReader(lookup_errors={ORGANIZATION: RuntimeError("secret-token-xyz")})
    result = run(reader)
    assert result.findings == (
        Finding("header.organization", "reference", "READ_ERROR", "RuntimeError"),)
    assert "secret-token-xyz" not in repr(result)


def test_read_error_alone_is_inconclusive_not_red_and_not_a_pass():
    result = run(FakeReader(lookup_errors={NOMENCLATURE: TimeoutError()}))
    assert result.status is V.INCONCLUSIVE
    assert result.status not in (V.MISMATCH, V.VERIFIED)


def test_failing_lookup_does_not_hide_a_definite_mismatch_on_a_posted_draft():
    reader = FakeReader(make_stored(posted=True),
                        lookup_errors={ORGANIZATION: RuntimeError("socket")})
    result = run(reader)
    assert result.status is V.MISMATCH
    assert {(f.path, f.code) for f in result.findings} == {
        ("document.posted", "MISMATCH"), ("header.organization", "READ_ERROR")}


def test_failing_lookup_does_not_skip_the_remaining_reference_checks():
    reader = FakeReader(lookup_errors={ORGANIZATION: RuntimeError("x")},
                        lookups={COUNTERPARTY: ReferenceLookup(True, True)})
    result = run(reader)
    assert result.status is V.MISMATCH
    assert {(f.path, f.code) for f in result.findings} == {
        ("header.organization", "READ_ERROR"), ("header.counterparty", "DELETION_MARKED")}
    assert sorted(reader.lookup_calls) == sorted(REFERENCE_PATHS.values())


def test_unexpected_failure_reading_one_field_is_isolated_to_that_field():
    base = make_stored()
    header = ExplodingMapping(base.header, {"header.incoming_date": ValueError("secret-v-1")})
    reader = FakeReader(dataclasses.replace(base, header=header))
    result = run(reader)
    assert result.status is V.INCONCLUSIVE
    assert result.findings == (
        Finding("header.incoming_date", "date", "READ_ERROR", "ValueError"),)
    assert "secret-v-1" not in repr(result)
    # The other fields were still checked (line references were resolved).
    assert ("Nomenclature", NOMENCLATURE) in reader.lookup_calls


def test_unexpected_failure_in_one_field_does_not_hide_a_mismatch_in_another():
    base = make_stored(line={"line.quantity": 3})
    header = ExplodingMapping(base.header, {"header.currency": KeyError("k")})
    result = run(FakeReader(dataclasses.replace(base, header=header)))
    assert result.status is V.MISMATCH
    assert {(f.path, f.code) for f in result.findings} == {
        ("header.currency", "READ_ERROR"), ("line.quantity", "MISMATCH")}


def test_failure_outside_any_single_check_is_a_document_level_read_error_not_a_crash():
    broken = dataclasses.replace(make_stored(), lines=None)
    result = run(FakeReader(broken))
    assert result.status is V.INCONCLUSIVE
    assert result.findings == (Finding("document", "read", "READ_ERROR", "TypeError"),)


# --- CR-388: typing_checked and incomplete writer declarations ----------------------------------------

ALL_PATHS = tuple(sorted(RECEIPT_TYPING_TABLE.types_by_path()))


@pytest.mark.parametrize("declared", [None, {}], ids=["omitted", "empty"])
def test_missing_writer_declaration_is_partial_unverified_never_verified(declared):
    reader = FakeReader()
    result = verify_receipt(reader, DOCUMENT_REF, make_expected(), SUPPORTED_SHAPE,
                            writer_declared_types=declared)
    assert result.status is V.PARTIAL_UNVERIFIED
    assert result.typing_checked is False
    assert result.findings == ()
    assert result.unverified_paths == ALL_PATHS
    assert reader.read_calls == [DOCUMENT_REF]  # the document itself was still compared


@pytest.mark.parametrize("missing", ALL_PATHS)
def test_declaration_missing_any_single_oracle_path_is_partial_unverified(missing):
    declared = full_declared_types()
    del declared[missing]
    result = run(writer_declared_types=declared)
    assert result.status is V.PARTIAL_UNVERIFIED
    assert result.typing_checked is False
    assert result.unverified_paths == (missing,)


def test_partial_declaration_unverified_paths_are_the_union_of_all_sources_sorted():
    declared = full_declared_types()
    del declared["line.quantity"]
    result = run(expected=make_expected(line__discount="5"), writer_declared_types=declared,
                 writer_unverified_paths=("line.zzz", "line.amount"))
    assert result.status is V.PARTIAL_UNVERIFIED
    assert result.unverified_paths == ("line.discount", "line.quantity", "line.zzz")


def test_complete_declaration_that_matches_the_oracle_is_verified_and_typing_checked():
    result = run(writer_declared_types=full_declared_types())
    assert result.status is V.VERIFIED
    assert result.typing_checked is True


def test_a_definite_mismatch_outranks_partial_typing_and_keeps_typing_unchecked():
    result = verify_receipt(FakeReader(make_stored(posted=True)), DOCUMENT_REF, make_expected(),
                            SUPPORTED_SHAPE)
    assert result.status is V.MISMATCH
    assert result.typing_checked is False
    assert result.unverified_paths == ALL_PATHS


def test_inconclusive_read_with_complete_declaration_reports_typing_checked():
    result = run(FakeReader(read_error=RuntimeError("x")))
    assert result.status is V.INCONCLUSIVE
    assert result.typing_checked is True


def test_a_diverging_declaration_is_never_reported_as_typing_checked():
    declared = full_declared_types()
    declared["line.quantity"] = "identity_text"
    result = run(writer_declared_types=declared)
    assert result.status is V.TYPING_DIVERGENCE
    assert result.typing_checked is False
