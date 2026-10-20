"""Test-lane reconciliation over fake gateways: states, exact rows, honesty rules, no leaks."""
from __future__ import annotations

import json
from decimal import Decimal

from _testlane_helpers import (
    ACC1,
    AS_OF,
    COMPANY,
    END,
    SECRET_AMOUNT,
    SECRET_NAME,
    START,
    analytics_payload,
    standard_responses,
    turnover_payload,
)

from testlane.phase2_mcp.gateway_client import GatewayError


def _run(make_reconciler, a, b, **kw):
    rec, ga, gb = make_reconciler(a, b)
    out = rec.reconcile_two_bases(COMPANY, AS_OF, START, END, **kw)
    return out, ga, gb


def test_match_on_complete_equal_pages(make_reconciler):
    out, _, _ = _run(make_reconciler, standard_responses(), standard_responses())
    six = out["sections"]["six_column_per_account"]
    assert six["state"] == "MATCH" and six["reason_code"] == "ALL_SIX_AND_ROWS_EQUAL"
    assert six["difference_count"] == 0
    assert six["side_a"]["accounts"] == 2 and six["side_a"]["rows_fetched"] == 3  # summed per account
    assert six["side_a"]["rows_digest"] == six["side_b"]["rows_digest"]
    assert out["native_pass"] is False and out["authority"] == "EVALUATION_ONLY"
    assert six["side_a"]["profile_kind"] == "TEST_LANE_UNRECONCILED"
    assert out["sections"]["supplier_521_1_closing_partial"]["state"] == "PARTIAL_MATCH"


def test_mismatch_reports_exact_row_and_total_when_values_requested(make_reconciler):
    b = standard_responses()
    b["accounting_balance_and_turnovers"]["value"][2]["closing_credit"] = Decimal(12)
    out, _, _ = _run(make_reconciler, standard_responses(), b, show_values=True)
    six = out["sections"]["six_column_per_account"]
    assert six["state"] == "MISMATCH" and six["difference_count"] == 2
    rows = [d for d in six["differences"] if d["level"] == "ROW"]
    totals = [d for d in six["differences"] if d["level"] == "TOTAL"]
    assert len(rows) == 1 and len(totals) == 1
    assert rows[0]["measure"] == "closing_credit"
    assert rows[0]["account_ref"] != ACC1 and rows[0]["side_a"] == "7"
    assert rows[0]["side_b"] == "12" and rows[0]["delta_b_minus_a"] == "5"
    assert totals[0]["delta_b_minus_a"] == "5"


def test_mismatch_hides_values_by_default(make_reconciler):
    b = standard_responses()
    b["accounting_balance_and_turnovers"]["value"][2]["closing_credit"] = Decimal(12)
    out, _, _ = _run(make_reconciler, standard_responses(), b)
    six = out["sections"]["six_column_per_account"]
    assert six["state"] == "MISMATCH"
    assert all("side_a" not in d and "account_ref" not in d for d in six["differences"])
    assert all("account_digest" in d for d in six["differences"] if d["level"] == "ROW")


def test_incomplete_page_is_inconclusive_never_match(make_reconciler):
    out, _, _ = _run(make_reconciler, standard_responses(has_more=True),
                     standard_responses(has_more=True))
    six = out["sections"]["six_column_per_account"]
    assert six["state"] == "INCONCLUSIVE"
    assert six["reason_code"] == "NATIVE_INCOMPLETE_OR_INCONSISTENT"
    assert six["side_a"]["has_more"] is True and six["side_a"]["page_complete"] is False
    assert "never be complete" in six["inconclusive_explanation"]


def test_snapshot_mismatch_is_inconclusive(make_reconciler):
    b = standard_responses()
    b["accounting_balance_and_turnovers"]["metadata_fingerprint"] = "mf-other"
    out, _, _ = _run(make_reconciler, standard_responses(), b)
    assert out["sections"]["six_column_per_account"]["reason_code"] == "SOURCE_SNAPSHOT_MISMATCH"
    assert out["sections"]["six_column_per_account"]["state"] == "INCONCLUSIVE"


def test_supplier_partial_mismatch_and_incomplete(make_reconciler):
    b = standard_responses()
    b["accounting_balance_by_analytics"] = analytics_payload(debit="101.00")
    out, _, _ = _run(make_reconciler, standard_responses(), b, show_values=True)
    part = out["sections"]["supplier_521_1_closing_partial"]
    assert part["state"] == "PARTIAL_MISMATCH" and part["difference_count"] == 1
    assert part["differences"][0]["measure"] == "closing_debit"
    assert part["differences"][0]["delta_b_minus_a"] == "1"
    b["accounting_balance_by_analytics"] = analytics_payload(status="PARTIAL")
    out, _, _ = _run(make_reconciler, standard_responses(), b)
    part = out["sections"]["supplier_521_1_closing_partial"]
    assert part["state"] == "INCONCLUSIVE" and part["reason_code"] == "SIDE_B_SUPPLIER_SUMMARY_NOT_COMPLETE"


def test_purchases_not_supported_with_reasons(make_reconciler):
    out, _, _ = _run(make_reconciler, standard_responses(), standard_responses())
    sec = out["sections"]["purchase_documents"]
    assert sec["state"] == "NOT_SUPPORTED"
    assert "PURCHASE_FIELD_NOT_PROVIDED_CONTRACT_REF" in sec["reason_codes"]
    assert "PURCHASE_FIELD_NOT_PROVIDED_DELETION_MARK" in sec["reason_codes"]
    assert sec["informational_first_page"]["label"].startswith("PARTIAL_FIRST_PAGE_ONLY")


def test_default_output_has_no_amounts_or_names(make_reconciler):
    out, _, _ = _run(make_reconciler, standard_responses(), standard_responses())
    text = json.dumps(out)
    assert str(SECRET_AMOUNT) not in text and "123456" not in text
    assert SECRET_NAME not in text and ACC1 not in text


def test_bad_input_refused_before_any_call(make_reconciler):
    rec, ga, gb = make_reconciler(standard_responses(), standard_responses())
    out = rec.reconcile_two_bases(COMPANY, "2026-08-31", START, END)
    assert out["state"] == "REFUSED" and out["reason_code"] == "AS_OF_TIMEZONE_OFFSET_REQUIRED"
    out = rec.reconcile_two_bases("not-a-guid", AS_OF, START, END)
    assert out["reason_code"] == "COMPANY_ID_INVALID"
    out = rec.reconcile_two_bases(COMPANY, AS_OF, END, START)
    assert out["reason_code"] == "PERIOD_ORDER_INVALID"
    assert ga.calls == [] and gb.calls == []


def test_gateway_error_is_reported_by_code_only(make_reconciler):
    b = standard_responses()
    b["accounting_balance_and_turnovers"] = GatewayError("GATEWAY_UNREACHABLE")
    out, _, _ = _run(make_reconciler, standard_responses(), b)
    six = out["sections"]["six_column_per_account"]
    assert six == {"state": "ERROR", "reason_code": "GATEWAY_UNREACHABLE"}
    assert out["sections"]["supplier_521_1_closing_partial"]["state"] == "PARTIAL_MATCH"


def test_negative_control_finds_exact_injected_difference(make_reconciler):
    rec, _, _ = make_reconciler(
        {"accounting_balance_and_turnovers": turnover_payload(has_more=True)},
        {"accounting_balance_and_turnovers": turnover_payload(has_more=True)})
    out = rec.negative_control(COMPANY, START, END, delta="2.5", show_values=True)
    assert out["label"] == "SYNTHETIC_NEGATIVE_CONTROL" and out["synthetic_completeness_assumed"]
    assert out["state"] == "CONTROL_DETECTED"
    assert out["baseline_state"] == "MATCH" and out["perturbed_state"] == "MISMATCH"
    assert out["perturbed_difference_count"] == 2
    assert {d["delta_b_minus_a"] for d in out["perturbed_differences"]} == {"2.5"}
    assert out["injected"]["delta"] == "2.5" and out["native_pass"] is False


def test_negative_control_hides_amounts_by_default_and_refuses_bad_delta(make_reconciler):
    rec, _, _ = make_reconciler(
        {"accounting_balance_and_turnovers": turnover_payload()},
        {"accounting_balance_and_turnovers": turnover_payload()})
    out = rec.negative_control(COMPANY, START, END)
    text = json.dumps(out)
    assert out["state"] == "CONTROL_DETECTED" and "123456" not in text and ACC1 not in text
    assert rec.negative_control(COMPANY, START, END, delta="0")["reason_code"] == "DELTA_INVALID"
    assert rec.negative_control(COMPANY, START, END, delta="x")["reason_code"] == "DELTA_INVALID"
    assert rec.negative_control(COMPANY, START, END, measure="nope")["reason_code"] == "MEASURE_INVALID"


def test_negative_control_not_detected_when_sides_already_differ(make_reconciler):
    other = turnover_payload()
    other["value"][2]["closing_credit"] = Decimal(8)
    rec, _, _ = make_reconciler({"accounting_balance_and_turnovers": turnover_payload()},
                                {"accounting_balance_and_turnovers": other})
    out = rec.negative_control(COMPANY, START, END)
    assert out["state"] == "CONTROL_NOT_DETECTED" and out["baseline_state"] == "MISMATCH"
