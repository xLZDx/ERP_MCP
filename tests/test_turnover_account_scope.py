"""Profile-owned account scope and exact server-side sums for balance-and-turnovers (real 818 HA shape)."""
from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from business_ai_gateway.analytics_balance import AnalyticsBalanceError, summarize_account_turnovers
from business_ai_gateway.fixture_profiles import ProvisionalProfiles
from business_ai_gateway.registry import Registry
from business_ai_gateway.semantic import (
    ACCOUNT_TURNOVERS_CONCEPT,
    SemanticMappingUnconfirmed,
    build_account_turnovers_arguments,
    normalize_account_turnovers,
    validate_account_turnovers_mapping,
)

PROFILE = Path(__file__).resolve().parents[1] / "testbed" / "real1c" / "provisional_profiles_818ha.json"
COMPANY = uuid.UUID("3e31afc5-351f-4f36-8074-99129fa3d911")
ORG = "019bbaa8-5131-11ee-aa2f-d85ed30dc416"
KEY_521_1 = "5659a91f-5098-11ee-aa2f-d85ed30dc416"
START, END = "2026-08-01T00:00:00+03:00", "2026-08-31T23:59:59+03:00"


@pytest.fixture(scope="module")
def mapping():
    provider = ProvisionalProfiles(PROFILE, hashlib.sha256(PROFILE.read_bytes()).hexdigest(), environment="test")
    return provider.lookup("onec-818ha-reference", COMPANY, ACCOUNT_TURNOVERS_CONCEPT)


def native_row(account, od, oc, dt, ct, cd, cc):
    return {
        "Account_Key": account,
        "СуммаOpeningSplittedBalanceDr": od, "СуммаOpeningSplittedBalanceCr": oc,
        "СуммаTurnoverDr": dt, "СуммаTurnoverCr": ct,
        "СуммаClosingSplittedBalanceDr": cd, "СуммаClosingSplittedBalanceCr": cc,
    }


def test_committed_real_profile_passes_the_shared_validator_chain(mapping):
    assert validate_account_turnovers_mapping(mapping) == ("AccountingRegister_Хозрасчетный", "balanceAndTurnovers")
    assert Registry.check_concept_mapping(ACCOUNT_TURNOVERS_CONCEPT, mapping) == mapping["required_register_capabilities"]


def test_arguments_are_scoped_to_company_and_profile_account(mapping):
    _, method, args = build_account_turnovers_arguments(
        mapping, company_external_ref=ORG, start_period=START, end_period=END)
    assert method == "balanceAndTurnovers"
    assert args["Condition"] == f"Организация_Key eq guid'{ORG}'"
    assert args["AccountCondition"] == f"Account_Key eq guid'{KEY_521_1}'"
    _, _, chosen = build_account_turnovers_arguments(
        mapping, company_external_ref=ORG, start_period=START, end_period=END, account_code="521.1")
    assert chosen["AccountCondition"] == args["AccountCondition"]


@pytest.mark.parametrize("code", ["521.2", "x", "521.1 or 1 eq 1", ""])
def test_caller_cannot_pick_an_undeclared_account_or_inject_a_filter(mapping, code):
    with pytest.raises(ValueError):
        build_account_turnovers_arguments(
            mapping, company_external_ref=ORG, start_period=START, end_period=END, account_code=code)


def test_profile_without_scope_keeps_old_behaviour_and_refuses_account_code(mapping):
    legacy = {k: v for k, v in mapping.items() if k not in {"account_field", "accounts"}}
    _, _, args = build_account_turnovers_arguments(
        legacy, company_external_ref=ORG, start_period=START, end_period=END)
    assert "AccountCondition" not in args
    with pytest.raises(ValueError):
        build_account_turnovers_arguments(
            legacy, company_external_ref=ORG, start_period=START, end_period=END, account_code="521.1")


@pytest.mark.parametrize("patch", [
    {"accounts": [{"code": "521.1", "account_key": "nope"}]},
    {"accounts": []},
    {"accounts": [{"code": "521.1", "account_key": KEY_521_1}, {"code": "521.1", "account_key": KEY_521_1}]},
    {"accounts": [{"code": "52'1", "account_key": KEY_521_1}]},
    {"account_field": "A eq 1 or B"},
])
def test_invalid_scope_fails_closed(mapping, patch):
    with pytest.raises(SemanticMappingUnconfirmed):
        validate_account_turnovers_mapping({**mapping, **patch})


def test_scope_needs_both_keys(mapping):
    only_field = {k: v for k, v in mapping.items() if k != "accounts"}
    with pytest.raises(SemanticMappingUnconfirmed):
        validate_account_turnovers_mapping(only_field)


def test_august_totals_are_exact_and_reconcile_with_the_real_figures(mapping):
    # Real August 2026 figures for 521.1 (read live 2026-10-07): opening 533036.05, debit 173436.43,
    # credit 263450.05, closing 623049.67 net credit. Split into two supplier rows for the test.
    rows = normalize_account_turnovers([
        native_row(KEY_521_1, 0, 533036.05, 100000.1, 200000.02, 0, 633035.97),
        native_row(KEY_521_1, 0, 0, 73436.33, 63450.03, 9986.3, 0),
    ], mapping)

    [total] = summarize_account_turnovers(rows, mapping)

    assert total["account"] == "521.1" and total["row_count"] == 2
    assert total["opening_credit"] == "533036.05"
    assert total["debit_turnover"] == "173436.43"
    assert total["credit_turnover"] == "263450.05"
    opening = Decimal(total["opening_credit"]) - Decimal(total["opening_debit"])
    closing = Decimal(total["closing_credit"]) - Decimal(total["closing_debit"])
    assert opening + Decimal(total["credit_turnover"]) - Decimal(total["debit_turnover"]) == closing
    assert closing == Decimal("623049.67")


def test_foreign_account_in_response_fails_closed(mapping):
    rows = normalize_account_turnovers([native_row(str(uuid.uuid4()), 0, 0, 1, 1, 0, 0)], mapping)
    with pytest.raises(AnalyticsBalanceError):
        summarize_account_turnovers(rows, mapping)


def test_malformed_amount_fails_closed(mapping):
    rows = normalize_account_turnovers([native_row(KEY_521_1, 0, 0, "NaN", 1, 0, 0)], mapping)
    with pytest.raises(AnalyticsBalanceError):
        summarize_account_turnovers(rows, mapping)


def test_profile_without_scope_yields_no_totals(mapping):
    legacy = {k: v for k, v in mapping.items() if k not in {"account_field", "accounts"}}
    assert summarize_account_turnovers([], legacy) == []
