"""Regression: the shape of the REAL 1C Balance response for account 521.1 (read live 2026-10-07)."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

from business_ai_gateway.analytics_balance import (
    AnalyticsBalanceDenied,
    AnalyticsBalanceError,
    normalize_odata_balance_rows,
)
from business_ai_gateway.fixture_profiles import ProvisionalProfiles
from business_ai_gateway.tool_errors import classify

PROFILE = Path(__file__).resolve().parents[1] / "testbed" / "real1c" / "provisional_profiles_818ha.json"
COMPANY = uuid.UUID("3e31afc5-351f-4f36-8074-99129fa3d911")
ORG_REF = "019bbaa8-5131-11ee-aa2f-d85ed30dc416"
ACCOUNT_KEY = "5659a91f-5098-11ee-aa2f-d85ed30dc416"


@pytest.fixture(scope="module")
def mapping():
    provider = ProvisionalProfiles(PROFILE, hashlib.sha256(PROFILE.read_bytes()).hexdigest(), environment="test")
    return provider.lookup("onec-818ha-reference", COMPANY, "account.balance_by_analytics")


def real_row(counterparty, contract, debit, credit, **override):
    row = {
        "Account_Key": ACCOUNT_KEY,
        "ExtDimension1": counterparty, "ExtDimension1_Type": "StandardODATA.Catalog_Контрагенты",
        "ExtDimension2": contract, "ExtDimension2_Type": "StandardODATA.Catalog_ДоговорыКонтрагентов",
        "ExtDimension3": "", "ExtDimension3_Type": "StandardODATA.Undefined",  # 1C: subconto 3 not set
        "Организация_Key": ORG_REF, "Валюта_Key": None, "Подразделение_Key": "019bbaab-5131-11ee-aa2f-d85ed30dc416",
        "СуммаSplittedBalanceDr": debit, "СуммаSplittedBalanceCr": credit,
    }
    row.update(override)
    return row


def test_unset_third_subconto_is_absent_not_malformed(mapping):
    rows = [
        real_row("0ef98609-57ad-11ee-aa2f-d85ed30dc416", "0ef9860a-57ad-11ee-aa2f-d85ed30dc416", 0, 90230.56),
        real_row("6b48d7c7-8237-11ee-aa36-d85ed30dc416", "6b48d7c8-8237-11ee-aa36-d85ed30dc416", 264.6, 0),
    ]

    out = normalize_odata_balance_rows(rows, mapping, company_external_ref=ORG_REF)

    assert [row["account"] for row in out] == ["521.1", "521.1"]
    assert [(row["balance_debit"], row["balance_credit"]) for row in out] == [("0", "90230.56"), ("264.6", "0")]
    third = out[0]["analytics"][2]
    assert third == {"slot": 3, "role": "other", "ref": None, "type": None}
    assert out[0]["analytics"][0]["type"] == "Catalog.Контрагенты"
    assert out[0]["analytics"][1]["type"] == "Catalog.ДоговорыКонтрагентов"


@pytest.mark.parametrize("bad", ["not-a-guid", " ", "0ef98609", 17, {"x": 1}])
def test_any_other_non_guid_subconto_still_fails_closed(mapping, bad):
    rows = [real_row("0ef98609-57ad-11ee-aa2f-d85ed30dc416", "0ef9860a-57ad-11ee-aa2f-d85ed30dc416", 0, 1,
                     ExtDimension3=bad)]

    with pytest.raises(AnalyticsBalanceError) as raised:
        normalize_odata_balance_rows(rows, mapping, company_external_ref=ORG_REF)

    assert raised.value.code == "SOURCE_RESPONSE_INVALID"


def test_unexpected_counterparty_type_still_fails_closed(mapping):
    rows = [real_row("0ef98609-57ad-11ee-aa2f-d85ed30dc416", "0ef9860a-57ad-11ee-aa2f-d85ed30dc416", 0, 1,
                     ExtDimension1_Type="StandardODATA.Catalog_Номенклатура")]

    with pytest.raises(AnalyticsBalanceError):
        normalize_odata_balance_rows(rows, mapping, company_external_ref=ORG_REF)


def test_other_company_row_fails_closed(mapping):
    rows = [real_row("0ef98609-57ad-11ee-aa2f-d85ed30dc416", "0ef9860a-57ad-11ee-aa2f-d85ed30dc416", 0, 1,
                     Организация_Key=str(uuid.uuid4()))]

    with pytest.raises(AnalyticsBalanceError) as raised:
        normalize_odata_balance_rows(rows, mapping, company_external_ref=ORG_REF)

    assert raised.value.code == "COMPANY_SCOPE_MISMATCH"


def test_missing_amount_column_fails_closed(mapping):
    row = real_row("0ef98609-57ad-11ee-aa2f-d85ed30dc416", "0ef9860a-57ad-11ee-aa2f-d85ed30dc416", 0, 1)
    del row["СуммаSplittedBalanceCr"]

    with pytest.raises(AnalyticsBalanceError):
        normalize_odata_balance_rows([row], mapping, company_external_ref=ORG_REF)


# ---------------------------------------------------------------- error contract


def test_analytics_errors_are_classified_without_echoing_source_content():
    invalid = classify(AnalyticsBalanceError("SOURCE_RESPONSE_INVALID"))
    scope = classify(AnalyticsBalanceError("COMPANY_SCOPE_MISMATCH"))
    denied = classify(AnalyticsBalanceDenied())

    assert (invalid.code, invalid.category, invalid.retryable) == ("SOURCE_RESPONSE_INVALID", "source_response", False)
    assert scope.code == "COMPANY_SCOPE_MISMATCH"
    assert (denied.code, denied.category) == ("ANALYTICS_ROUTE_DENIED", "capability")
    assert "no figures were returned" in invalid.safe_message
    assert json.dumps([invalid.safe_message, scope.safe_message, denied.safe_message]).count("0ef98609") == 0
