"""S15 epic E15-2: independent versioned oracle (typing table, total rule, value comparison)."""
from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from erp_mcp_s15 import oracle, verifier
from erp_mcp_s15.oracle import (
    ORACLE_VERSION,
    RECEIPT_TYPING_TABLE,
    FieldRule,
    FieldType,
    Scope,
    TypingTable,
    expected_total,
    own_date_matches,
    value_matches,
)
from erp_mcp_s15.verifier import SUPPORTED_SHAPE, VerificationStatus, verify_receipt
from tests.phase2._s15_fixtures import (
    FakeReader,
    full_declared_types,
    make_expected,
    make_stored,
)


def _rule(kind: FieldType, catalog: str | None = None) -> FieldRule:
    return FieldRule("x.path", Scope.LINE, kind, catalog)


# --- versioning (assertion 1) ---------------------------------------------------------------

def test_oracle_version_is_recorded_in_a_verified_result():
    result = verify_receipt(FakeReader(), "ref", make_expected(), SUPPORTED_SHAPE,
                            writer_declared_types=full_declared_types())
    assert result.status is VerificationStatus.VERIFIED
    assert result.oracle_version == ORACLE_VERSION == "s15-oracle-1"


def test_oracle_version_is_recorded_in_a_red_result_too():
    reader = FakeReader(make_stored(posted=True))
    result = verify_receipt(reader, "ref", make_expected(), SUPPORTED_SHAPE)
    assert result.status is VerificationStatus.MISMATCH
    assert result.oracle_version == ORACLE_VERSION


def test_changing_the_oracle_version_changes_the_recorded_value(monkeypatch):
    monkeypatch.setattr(verifier, "ORACLE_VERSION", "s15-oracle-TEST-2")
    result = verify_receipt(FakeReader(), "ref", make_expected(), SUPPORTED_SHAPE)
    assert result.oracle_version == "s15-oracle-TEST-2"
    assert result.oracle_version != ORACLE_VERSION


def test_oracle_version_is_recorded_for_unsupported_shape_and_divergence():
    other = verifier.OperationShape("POST", "RECEIPT", 1)
    assert verify_receipt(FakeReader(), "r", make_expected(), other).oracle_version \
        == ORACLE_VERSION
    divergent = verify_receipt(FakeReader(), "r", make_expected(), SUPPORTED_SHAPE,
                               writer_declared_types={"line.quantity": "date"})
    assert divergent.oracle_version == ORACLE_VERSION


# --- total rule (assertion 3) ---------------------------------------------------------------

def test_total_with_flag_false_is_amount_plus_vat():
    assert expected_total("20", "1.82", False) == "21.82"


def test_total_with_flag_true_is_the_amount_alone():
    assert expected_total("20", "1.82", True) == "20"


def test_total_takes_vat_as_given_and_never_recomputes_it():
    # 20% of 20 would be 4.00; the approved vat_amount is used verbatim.
    assert expected_total("20", "0.01", False) == "20.01"
    assert expected_total("20", "0", False) == "20"


def test_total_is_decimal_exact_not_float():
    assert expected_total("0.1", "0.2", False) == "0.3"


def test_total_negative_amounts_supported():
    assert expected_total("-20", "-1.82", False) == "-21.82"


@pytest.mark.parametrize("amount,vat,flag", [
    (20, "1.82", False), ("20", 1.82, False), ("abc", "1", False), ("20", "", False),
    ("1e3", "1", False), (" 20", "1", False), ("20", "1.82", 1), ("20", "1.82", None),
    ("20.", "1", False), ("NaN", "1", False),
])
def test_total_rejects_invalid_inputs(amount, vat, flag):
    with pytest.raises(ValueError, match="ORACLE_TOTAL_INPUT_INVALID"):
        expected_total(amount, vat, flag)


# --- typing table (assertion 4) -------------------------------------------------------------

def test_receipt_table_pins_the_reviewed_types():
    # A pinned snapshot: any silent retyping of a field fails here.
    assert RECEIPT_TYPING_TABLE.types_by_path() == {
        "header.organization": "reference", "header.counterparty": "reference",
        "header.contract": "reference", "header.currency": "reference",
        "header.incoming_number": "identity_text", "header.incoming_date": "date",
        "line.nomenclature": "reference", "line.quantity": "number", "line.price": "number",
        "line.amount": "number", "line.vat_rate": "enumeration", "line.vat_amount": "number",
    }


def test_receipt_table_references_name_their_expected_catalog():
    expected = {
        "header.organization": "Organizations", "header.counterparty": "Counterparties",
        "header.contract": "Contracts", "header.currency": "Currencies",
        "line.nomenclature": "Nomenclature",
    }
    found = {r.path: r.catalog for r in RECEIPT_TYPING_TABLE.rules
             if r.field_type is FieldType.REFERENCE}
    assert found == expected
    assert all(r.catalog is None for r in RECEIPT_TYPING_TABLE.rules
               if r.field_type is not FieldType.REFERENCE)


def test_table_get_returns_rule_or_none():
    assert RECEIPT_TYPING_TABLE.get("line.amount").field_type is FieldType.NUMBER
    assert RECEIPT_TYPING_TABLE.get("line.nope") is None


def test_reference_rule_requires_a_catalog_and_others_forbid_it():
    with pytest.raises(ValueError, match="ORACLE_RULE_INVALID"):
        FieldRule("a", Scope.HEADER, FieldType.REFERENCE)
    with pytest.raises(ValueError, match="ORACLE_RULE_INVALID"):
        FieldRule("a", Scope.HEADER, FieldType.NUMBER, "Catalog")


def test_table_rejects_empty_and_duplicate_paths():
    with pytest.raises(ValueError, match="ORACLE_TABLE_INVALID"):
        TypingTable(())
    rule = FieldRule("a", Scope.HEADER, FieldType.NUMBER)
    with pytest.raises(ValueError, match="ORACLE_TABLE_INVALID"):
        TypingTable((rule, rule))


def test_divergence_between_writer_types_and_oracle_table_is_red():
    writer_types = dict(RECEIPT_TYPING_TABLE.types_by_path())
    # Control: identical declaration is not divergent.
    ok = verify_receipt(FakeReader(), "r", make_expected(), SUPPORTED_SHAPE,
                        writer_declared_types=writer_types)
    assert ok.status is VerificationStatus.VERIFIED
    writer_types["line.quantity"] = "identity_text"  # the writer would treat quantity as text
    result = verify_receipt(FakeReader(), "r", make_expected(), SUPPORTED_SHAPE,
                            writer_declared_types=writer_types)
    assert result.status is VerificationStatus.TYPING_DIVERGENCE
    assert [(f.path, f.code) for f in result.findings] == [("line.quantity", "TYPING_DIVERGENCE")]


@pytest.mark.parametrize("path", sorted(RECEIPT_TYPING_TABLE.types_by_path()))
def test_every_table_path_diverging_is_detected(path):
    types = dict(RECEIPT_TYPING_TABLE.types_by_path())
    types[path] = "flag"  # a type that no receipt path has
    reader = FakeReader()
    result = verify_receipt(reader, "r", make_expected(), SUPPORTED_SHAPE,
                            writer_declared_types=types)
    assert result.status is VerificationStatus.TYPING_DIVERGENCE
    assert {f.path for f in result.findings} == {path}
    assert reader.read_calls == []  # divergence is decided before any read


def test_writer_declaring_a_path_the_oracle_does_not_know_is_divergent():
    result = verify_receipt(FakeReader(), "r", make_expected(), SUPPORTED_SHAPE,
                            writer_declared_types={"line.mystery": "number"})
    assert result.status is VerificationStatus.TYPING_DIVERGENCE
    assert result.findings[0].path == "line.mystery"


def test_writer_declaring_a_subset_with_matching_types_is_not_divergent_but_not_verified():
    result = verify_receipt(FakeReader(), "r", make_expected(), SUPPORTED_SHAPE,
                            writer_declared_types={"line.amount": "number"})
    # The declared part agrees, but the undeclared remainder was never type-checked.
    assert result.status is VerificationStatus.PARTIAL_UNVERIFIED
    assert result.typing_checked is False
    assert result.unverified_paths == tuple(
        sorted(set(RECEIPT_TYPING_TABLE.types_by_path()) - {"line.amount"}))


def test_oracle_table_is_used_not_the_writer_table_for_comparison():
    # A custom reviewed table that types the incoming number as a NUMBER: the stored int 123
    # for expected "123" then matches, while the default table (identity text) rejects it.
    rules = tuple(
        FieldRule(r.path, r.scope, FieldType.NUMBER) if r.path == "header.incoming_number" else r
        for r in RECEIPT_TYPING_TABLE.rules)
    custom = TypingTable(rules)
    expected = make_expected(header__incoming_number="123")
    stored = make_stored(header={"header.incoming_number": 123})
    custom_result = verify_receipt(FakeReader(stored), "r", expected, SUPPORTED_SHAPE,
                                   writer_declared_types=custom.types_by_path(), table=custom)
    default_result = verify_receipt(FakeReader(stored), "r", expected, SUPPORTED_SHAPE,
                                    writer_declared_types=full_declared_types())
    assert custom_result.status is VerificationStatus.VERIFIED
    assert default_result.status is VerificationStatus.MISMATCH


# --- unverified paths (assertion 5) ----------------------------------------------------------

def test_executor_unverified_path_not_covered_by_oracle_is_reported_and_blocks_verified():
    result = verify_receipt(FakeReader(), "r", make_expected(), SUPPORTED_SHAPE,
                            writer_declared_types=full_declared_types(),
                            writer_unverified_paths=("line.discount",))
    assert result.status is VerificationStatus.PARTIAL_UNVERIFIED
    assert result.unverified_paths == ("line.discount",)
    assert result.typing_checked is True


def test_executor_unverified_path_covered_by_oracle_is_not_reported():
    result = verify_receipt(FakeReader(), "r", make_expected(), SUPPORTED_SHAPE,
                            writer_declared_types=full_declared_types(),
                            writer_unverified_paths=("line.amount", "header.incoming_date"))
    assert result.status is VerificationStatus.VERIFIED
    assert result.unverified_paths == ()


def test_expected_path_outside_the_table_is_reported_unverified():
    result = verify_receipt(FakeReader(), "r", make_expected(line__discount="5"),
                            SUPPORTED_SHAPE, writer_declared_types=full_declared_types())
    assert result.status is VerificationStatus.PARTIAL_UNVERIFIED
    assert result.unverified_paths == ("line.discount",)


def test_unverified_paths_are_kept_alongside_a_mismatch():
    reader = FakeReader(make_stored(posted=True))
    result = verify_receipt(reader, "r", make_expected(), SUPPORTED_SHAPE,
                            writer_declared_types=full_declared_types(),
                            writer_unverified_paths=("line.discount",))
    assert result.status is VerificationStatus.MISMATCH
    assert result.unverified_paths == ("line.discount",)


# --- value comparison per type ----------------------------------------------------------------

@pytest.mark.parametrize("expected,stored", [
    ("20", 20), ("20", Decimal("20.00")), ("20", 20.0), ("1.82", 1.82),
    ("1.82", Decimal("1.82")), ("0", 0), ("-5", -5),
])
def test_number_matches_by_exact_numeric_value(expected, stored):
    assert value_matches(_rule(FieldType.NUMBER), expected, stored) is True


@pytest.mark.parametrize("expected,stored", [
    ("20", "20"), ("20", 21), ("1.82", 1.83), ("20", True), ("20", None),
    ("20", Decimal("NaN")), ("20", Decimal("Infinity")), ("abc", 20), (20, 20), ("", 0),
])
def test_number_rejects_text_wrong_value_bool_and_nonfinite(expected, stored):
    assert value_matches(_rule(FieldType.NUMBER), expected, stored) is False


def test_identity_text_is_exact_string_so_leading_zeros_matter():
    rule = _rule(FieldType.IDENTITY_TEXT)
    assert value_matches(rule, "00123", "00123") is True
    assert value_matches(rule, "00123", 123) is False
    assert value_matches(rule, "00123", "123") is False
    assert value_matches(rule, "abc", "ABC") is False
    assert value_matches(rule, "abc", "abc ") is False


def test_date_is_text_with_midnight_suffix_and_never_the_empty_date():
    rule = _rule(FieldType.DATE)
    assert value_matches(rule, "2026-03-10", "2026-03-10T00:00:00") is True
    assert value_matches(rule, "2026-03-10", "2026-03-11T00:00:00") is False
    assert value_matches(rule, "2026-03-10", "2026-03-09T00:00:00") is False
    assert value_matches(rule, "2026-03-10", "2026-03-10T07:00:00") is False
    assert value_matches(rule, "2026-03-10", "") is False
    assert value_matches(rule, "2026-03-10", None) is False
    # Python datetime objects are never accepted (dates are read as XMLString text only).
    assert value_matches(rule, "2026-03-10", datetime.datetime(2026, 3, 10, tzinfo=datetime.UTC)) is False
    # An expected empty date can never match, even against itself.
    assert value_matches(rule, "0001-01-01", "0001-01-01T00:00:00") is False
    assert value_matches(rule, "0100-01-01", "0100-01-01T00:00:00") is False
    assert value_matches(rule, "not-a-date", "not-a-dateT00:00:00") is False


@pytest.mark.parametrize("kind", [FieldType.ENUMERATION, FieldType.REFERENCE])
def test_enumeration_and_reference_need_nonempty_identical_text(kind):
    rule = _rule(kind, "Cat" if kind is FieldType.REFERENCE else None)
    assert value_matches(rule, "VAT20", "VAT20") is True
    assert value_matches(rule, "VAT20", "VAT10") is False
    assert value_matches(rule, "VAT20", "") is False
    assert value_matches(rule, "VAT20", None) is False
    assert value_matches(rule, "", "") is False  # empty expected can never be verified
    assert value_matches(rule, "VAT20", 20) is False


def test_flag_requires_identity_with_the_expected_bool():
    rule = _rule(FieldType.FLAG)
    assert value_matches(rule, False, False) is True
    assert value_matches(rule, True, True) is True
    assert value_matches(rule, False, True) is False
    assert value_matches(rule, False, 0) is False
    assert value_matches(rule, False, None) is False
    assert value_matches(rule, "false", False) is False


def test_own_date_compares_calendar_day_only():
    assert own_date_matches("2026-03-11", "2026-03-11T07:00:00") is True
    assert own_date_matches("2026-03-11", "2026-03-11T00:00:00") is True
    assert own_date_matches("2026-03-11", "2026-03-11T23:59:59") is True
    assert own_date_matches("2026-03-11", "2026-03-12T07:00:00") is False
    assert own_date_matches("2026-03-11", "2026-03-10T23:59:59") is False
    assert own_date_matches("2026-03-11", "") is False
    assert own_date_matches("2026-03-11", None) is False
    assert own_date_matches("2026-03-11", 20260311) is False
    assert own_date_matches("0001-01-01", "0001-01-01T00:00:00") is False
    assert own_date_matches("2026-3-11", "2026-3-11T00:00:00") is False
    assert own_date_matches(None, "2026-03-11T07:00:00") is False


@pytest.mark.parametrize("stored", [
    "2026-03-11",  # no time part
    "2026-03-11T07:00",  # no seconds
    "2026-03-11T07:00:00Z",  # trailing zone garbage
    "2026-03-11T07:00:00.5",  # fractional seconds are not XMLString
    "2026-03-11T07:00:00junk",
    "2026-03-11T07:00:00" + chr(10),  # a trailing newline must not slip through the end anchor
    "2026-03-11 07:00:00",  # wrong separator
    "2026-03-11T24:00:00", "2026-03-11T07:60:00", "2026-03-11T07:00:60",  # impossible time
    "2026-02-30T07:00:00", "2026-13-11T07:00:00", "2026-00-11T07:00:00",  # impossible date
    "2026-03-32T07:00:00", "2025-02-29T07:00:00",  # 2025 is not a leap year
    chr(0xFF12) + "026-03-11T07:00:00",  # non-ASCII digit
    " 2026-03-11T07:00:00",
])
def test_own_date_rejects_a_stored_text_that_is_not_a_full_real_xml_datetime(stored):
    # The expected day is a real day on the stored day, so only the stored text can make it red.
    assert own_date_matches("2026-03-11", stored) is False


def test_own_date_accepts_a_real_leap_day_and_boundary_times():
    assert own_date_matches("2024-02-29", "2024-02-29T00:00:00") is True
    assert own_date_matches("2024-02-29", "2024-02-29T23:59:59") is True


@pytest.mark.parametrize("day", [
    "2026-02-30", "2025-02-29", "2026-13-01", "2026-00-10", "2026-03-00", "2026-03-11T00:00:00",
    "", "2026-3-11", "26-03-11", "2026-03-11 ", "2026-03-11" + chr(10), None, 20260311,
    "0001-01-01", "0100-01-01",
])
def test_own_date_rejects_an_expected_day_that_is_not_a_real_calendar_day(day):
    # The stored text starts with the same characters as the expected day, so a plain prefix
    # comparison would accept it; the calendar validation must refuse it.
    stored = f"{day}T07:00:00" if isinstance(day, str) else "2026-03-11T07:00:00"
    assert own_date_matches(day, stored) is False


def test_empty_date_days_constant_covers_both_1c_empty_dates():
    assert oracle.EMPTY_DATE_DAYS == frozenset({"0001-01-01", "0100-01-01"})
