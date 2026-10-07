"""ADR-0008 mapping validation, argument builder and canonical row normalisation (no DB, no 1C)."""
from __future__ import annotations

import copy

import pytest

from business_ai_gateway.analytics_balance import (
    ANALYTICS_BALANCE_CONCEPT,
    AnalyticsBalanceError,
    build_analytics_balance_arguments,
    normalize_com_balance_rows,
    normalize_odata_balance_rows,
    normalize_type,
    validate_analytics_balance_mapping,
)
from business_ai_gateway.semantic import SemanticMappingUnconfirmed

KEY1 = "11111111-1111-4111-8111-111111111111"
KEY2 = "22222222-2222-4222-8222-222222222222"
REF1 = "33333333-3333-4333-8333-333333333333"
COMPANY = "f3727523-9689-4b73-973e-9754360fd0a0"
OTHER_COMPANY = "f3727523-9689-4b73-973e-9754360fd0a1"
ZERO = "00000000-0000-0000-0000-000000000000"
REGISTER = "AccountingRegister_Хозрасчетный"


def good_mapping() -> dict:
    return {
        "entity_set": REGISTER,
        "method": "balance",
        "company_scope": {"field": "Организация_Key", "value_type": "guid"},
        "accounts": [{"code": "521.1", "account_key": KEY1}, {"code": "221", "account_key": KEY2}],
        "account_field": "Account_Key",
        "analytics": [
            {"slot": 1, "role": "counterparty", "ref_field": "ExtDimension1",
             "type_field": "ExtDimension1_Type", "expected_type": "Catalog.Контрагенты"},
            {"slot": 2, "role": "contract", "ref_field": "ExtDimension2",
             "type_field": "ExtDimension2_Type"},
        ],
        "amount_fields": {"debit": "СуммаDebitBalance", "credit": "СуммаCreditBalance"},
        "currency_field": "Currency_Key",
        "required_register_capabilities": [{"entity_set": REGISTER, "method": "balance"}],
    }


def odata_row(**over) -> dict:
    row = {
        "Account_Key": KEY1,
        "ExtDimension1": REF1, "ExtDimension1_Type": "StandardODATA.Catalog_Контрагенты",
        "ExtDimension2": ZERO, "ExtDimension2_Type": None,
        "СуммаDebitBalance": 10.5, "СуммаCreditBalance": 0,
        "Организация_Key": COMPANY, "Currency_Key": ZERO,
    }
    row.update(over)
    return row


def com_row(**over) -> dict:
    row = {
        "account_key": KEY1,
        "analytics": [{"ref": REF1, "type": "Catalog.Контрагенты"},
                      {"ref": None, "type": None}, {"ref": None, "type": None}],
        "debit": "10.50", "credit": "0.00", "currency_ref": None,
    }
    row.update(over)
    return row


def test_concept_name():
    assert ANALYTICS_BALANCE_CONCEPT == "account.balance_by_analytics"


def test_valid_mapping_accepted():
    assert validate_analytics_balance_mapping(good_mapping()) == (REGISTER, "balance")


def _mutations():
    def m(fn):
        def run():
            mapping = good_mapping()
            fn(mapping)
            return mapping
        return run
    return {
        "unknown_key": m(lambda x: x.update(extra=1)),
        "accumulation_register": m(lambda x: x.update(
            entity_set="AccumulationRegister_X",
            required_register_capabilities=[{"entity_set": "AccumulationRegister_X", "method": "balance"}])),
        "wrong_method": m(lambda x: x.update(method="Balance")),
        "no_accounts": m(lambda x: x.update(accounts=[])),
        "17_accounts": m(lambda x: x.update(accounts=[
            {"code": str(i), "account_key": f"{i:08x}-1111-4111-8111-111111111111"} for i in range(17)])),
        "dup_key": m(lambda x: x["accounts"][1].update(account_key=KEY1)),
        "dup_code": m(lambda x: x["accounts"][1].update(code="521.1")),
        "key_injection": m(lambda x: x["accounts"][0].update(account_key=f"{KEY1}' or 1 eq 1 or '")),
        "key_braces": m(lambda x: x["accounts"][0].update(account_key="{" + KEY1 + "}")),
        "code_injection": m(lambda x: x["accounts"][0].update(code="1'; drop")),
        "account_field_injection": m(lambda x: x.update(account_field="Account_Key eq 1 or A")),
        "no_slots": m(lambda x: x.update(analytics=[])),
        "4_slots": m(lambda x: x.update(analytics=[
            {"slot": 1, "role": "item", "ref_field": f"R{i}", "type_field": f"T{i}"} for i in range(4)])),
        "dup_slot": m(lambda x: x["analytics"][1].update(slot=1)),
        "slot_bool": m(lambda x: x["analytics"][0].update(slot=True)),
        "slot_zero": m(lambda x: x["analytics"][0].update(slot=0)),
        "bad_role": m(lambda x: x["analytics"][0].update(role="payload")),
        "bad_expected_type": m(lambda x: x["analytics"][0].update(expected_type="Catalog'X")),
        "ref_field_injection": m(lambda x: x["analytics"][0].update(ref_field="A) or (B")),
        "extra_slot_key": m(lambda x: x["analytics"][0].update(x=1)),
        "amount_missing": m(lambda x: x.update(amount_fields={"debit": "A"})),
        "amount_extra": m(lambda x: x["amount_fields"].update(net="N")),
        "amount_same": m(lambda x: x["amount_fields"].update(credit="СуммаDebitBalance")),
        "currency_bad": m(lambda x: x.update(currency_field="a b")),
        "scope_bad_type": m(lambda x: x["company_scope"].update(value_type="int")),
        "scope_extra": m(lambda x: x["company_scope"].update(x=1)),
        "caps_missing": m(lambda x: x.pop("required_register_capabilities")),
        "caps_wrong_method": m(lambda x: x.update(
            required_register_capabilities=[{"entity_set": REGISTER, "method": "turnovers"}])),
        "caps_extra": m(lambda x: x["required_register_capabilities"].append(
            {"entity_set": REGISTER, "method": "balance"})),
    }


@pytest.mark.parametrize("name", sorted(_mutations()))
def test_rejected_variants(name):
    with pytest.raises(SemanticMappingUnconfirmed):
        validate_analytics_balance_mapping(_mutations()[name]())


def test_non_object_rejected():
    with pytest.raises(SemanticMappingUnconfirmed):
        validate_analytics_balance_mapping([])


def test_currency_null_allowed():
    mapping = good_mapping()
    mapping["currency_field"] = None
    validate_analytics_balance_mapping(mapping)


def test_arguments_contain_only_validated_guids_and_timezone():
    register, method, args = build_analytics_balance_arguments(
        good_mapping(), company_external_ref=COMPANY, as_of="2026-04-30T23:59:59+03:00")
    assert (register, method) == (REGISTER, "balance")
    assert args == {
        "Period": "2026-04-30T23:59:59+03:00",
        "Condition": f"Организация_Key eq guid'{COMPANY}'",
        "AccountCondition": f"Account_Key eq guid'{KEY1}' or Account_Key eq guid'{KEY2}'",
    }
    assert set(args) == {"Period", "Condition", "AccountCondition"}


def test_account_condition_normalises_guid_case():
    mapping = good_mapping()
    lettered = "abcdefab-1111-4111-8111-111111111111"
    mapping["accounts"][0]["account_key"] = lettered.upper()
    args = build_analytics_balance_arguments(mapping, company_external_ref=COMPANY, as_of="2026-04-30T00:00:00Z")[2]
    assert lettered.upper() not in args["AccountCondition"] and lettered in args["AccountCondition"]


@pytest.mark.parametrize("as_of", ["2026-04-30", "2026-04-30T00:00:00", "not-a-date", ""])
def test_as_of_requires_explicit_timezone(as_of):
    with pytest.raises(ValueError):
        build_analytics_balance_arguments(good_mapping(), company_external_ref=COMPANY, as_of=as_of)


def test_company_ref_must_be_guid_for_guid_scope():
    with pytest.raises(SemanticMappingUnconfirmed):
        build_analytics_balance_arguments(
            good_mapping(), company_external_ref="x' or 1 eq 1", as_of="2026-04-30T00:00:00Z")


def test_odata_normalisation_canonical_shape_and_split_balances():
    (row,) = normalize_odata_balance_rows([odata_row()], good_mapping(), company_external_ref=COMPANY)
    assert row == {
        "account": "521.1", "account_key": KEY1,
        "analytics": [
            {"slot": 1, "role": "counterparty", "ref": REF1, "type": "Catalog.Контрагенты"},
            {"slot": 2, "role": "contract", "ref": None, "type": None},
        ],
        "balance_debit": "10.5", "balance_credit": "0", "currency_ref": None,
    }


def test_com_normalisation_equals_odata_normalisation():
    odata = normalize_odata_balance_rows([odata_row()], good_mapping(), company_external_ref=COMPANY)
    com = normalize_com_balance_rows([com_row()], good_mapping())
    assert odata == com


@pytest.mark.parametrize("raw,expected", [
    ("StandardODATA.Catalog_Контрагенты", "Catalog.Контрагенты"),
    ("Catalog_X", "Catalog.X"), ("Catalog.X", "Catalog.X"),
    ("StandardODATA.Document_Реализация", "Document.Реализация"),
])
def test_type_normalisation(raw, expected):
    assert normalize_type(raw) == expected


@pytest.mark.parametrize("raw", ["Edm.String", "weird", "", None, 5, "Catalog_X'"])
def test_unknown_type_fails_closed(raw):
    if raw == "Edm.String":  # Kind.Name shape is syntactically valid; expected_type guards it
        assert normalize_type(raw) == "Edm.String"
        return
    with pytest.raises(AnalyticsBalanceError):
        normalize_type(raw)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "abc", True, None, [1], {"a": 1}])
def test_decimal_strictness(value):
    with pytest.raises(AnalyticsBalanceError):
        normalize_odata_balance_rows(
            [odata_row(СуммаDebitBalance=value)], good_mapping(), company_external_ref=COMPANY)


def test_decimal_precision_preserved_as_string():
    (row,) = normalize_odata_balance_rows(
        [odata_row(СуммаDebitBalance="1234567890123.4500", СуммаCreditBalance=-0.0)],
        good_mapping(), company_external_ref=COMPANY)
    assert (row["balance_debit"], row["balance_credit"]) == ("1234567890123.45", "0")


def test_account_outside_set_fails_closed():
    other = "44444444-4444-4444-8444-444444444444"
    for rows, fn in (
        ([odata_row(Account_Key=other)], lambda r: normalize_odata_balance_rows(
            r, good_mapping(), company_external_ref=COMPANY)),
        ([com_row(account_key=other)], lambda r: normalize_com_balance_rows(r, good_mapping())),
    ):
        with pytest.raises(AnalyticsBalanceError) as err:
            fn(rows)
        assert err.value.code == "SOURCE_RESPONSE_INVALID"


def test_expected_type_mismatch_fails_closed():
    with pytest.raises(AnalyticsBalanceError):
        normalize_odata_balance_rows(
            [odata_row(ExtDimension1_Type="StandardODATA.Catalog_Номенклатура")],
            good_mapping(), company_external_ref=COMPANY)
    bad = com_row()
    bad["analytics"][0]["type"] = "Catalog.Номенклатура"
    with pytest.raises(AnalyticsBalanceError):
        normalize_com_balance_rows([bad], good_mapping())


def test_missing_field_fails_closed():
    row = odata_row()
    del row["СуммаCreditBalance"]
    with pytest.raises(AnalyticsBalanceError):
        normalize_odata_balance_rows([row], good_mapping(), company_external_ref=COMPANY)
    with pytest.raises(AnalyticsBalanceError):
        normalize_com_balance_rows([{"account_key": KEY1}], good_mapping())


def test_company_mismatch_fails_closed_and_missing_company_field_is_ignored():
    with pytest.raises(AnalyticsBalanceError) as err:
        normalize_odata_balance_rows(
            [odata_row(Организация_Key=OTHER_COMPANY)], good_mapping(), company_external_ref=COMPANY)
    assert err.value.code == "COMPANY_SCOPE_MISMATCH"
    row = odata_row()
    del row["Организация_Key"]
    assert normalize_odata_balance_rows([row], good_mapping(), company_external_ref=COMPANY)


def test_non_list_and_non_object_rows_fail_closed():
    for bad in ({}, "x", [1]):
        with pytest.raises(AnalyticsBalanceError):
            normalize_odata_balance_rows(bad, good_mapping(), company_external_ref=COMPANY)


def test_mapping_is_not_mutated():
    mapping = good_mapping()
    snapshot = copy.deepcopy(mapping)
    normalize_odata_balance_rows([odata_row()], mapping, company_external_ref=COMPANY)
    assert mapping == snapshot
