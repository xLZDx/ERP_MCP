"""SC01..SC12 black-box scenario contracts through the public MCP tools (real Streamable-HTTP client).

Statuses are OBSERVED, never assumed:

* PASS            a public tool answered with live data and the declared invariant held
* EXTERNAL-GATE   VAT-style capability that exists only on a validated profile (SC06)

SC08 (duplicate counterparties) is a real PASS scenario: the read-only candidate tool
`counterparty_duplicate_candidates` (docs/SC08_DUPLICATE_COUNTERPARTY_CONTRACT.md), merge_count always 0.

The data-bearing tools answer through the TEST-ONLY reviewed synthetic fixture profile
(BAG_ENVIRONMENT=test, source tag synthetic-fixture). Every response must be labelled
SYNTHETIC_FIXTURE / L1 / native_reconciliation NOT_RUN: this is never native 1C reconciliation.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal

import pytest

from tests.functional.support import harness as h
from tests.functional.support.evidence import record
from tests.functional.support.specs import (
    CASH_WINDOW,
    DECEMBER,
    FIX,
    ITEM_1,
    ITEM_2,
    PARTY_DUP_A,
    PARTY_DUP_B,
    PARTY_OVERDUE,
    PARTY_OVERPAID,
    PARTY_PARTIAL,
    SPECS,
    WIDE,
    args_for,
)

IDS = sorted(SPECS)
FIXTURE_CODE = "SYNTHETIC_FIXTURE_PROFILE"


def D(x) -> Decimal:
    return Decimal(str(x))


async def ok_call(tool: str, company: str = h.COMPANY_ONE, **extra) -> h.Outcome:
    """Call a data tool that must succeed; assert labelling, read-only transport and bounds."""
    out = await h.call(tool, args_for(tool, h.SOURCE_ID, company, **extra))
    assert out.ok, f"{tool}: {out.text or out.transport_error}; audit={[r['detail_code'] for r in out.audit]}"
    body = out.data
    assert body["profile_kind"] == "SYNTHETIC_FIXTURE" and body["evidence_level"] == "L1"
    assert body["native_reconciliation"] == "NOT_RUN"
    assert "SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE" in body["warnings"]
    assert str(body["company_id"]) == company and body["source_id"] == h.SOURCE_ID
    assert h.no_write_reached_1c(out), (out.upstream, out.sidecar)
    rows = body.get("value", body.get("rows", []))
    assert len(rows) <= 200, "result must be bounded by max_rows"
    assert not (body.get("page") or {}).get("truncated"), "unexpected truncation"
    assert h.final_audit(out)["outcome"] == "success"
    assert FIXTURE_CODE in [r["detail_code"] for r in out.audit]
    return out


def by_key(rows, key):
    return {r[key]: r for r in rows}


# ---------------------------------------------------------------- positive evaluators

async def eval_sc01():
    body = (await ok_call("receivable_aging")).data
    assert body["status"] == "PASS" and body["kind"] == "AR"
    b = by_key(body["rows"], "counterparty_id")[PARTY_OVERDUE]["buckets"]
    overdue = sum(D(b[k]) for k in ("days_31_60", "days_61_90", "days_91_plus"))
    open_balance = D(by_key(body["summary"], "counterparty_id")[PARTY_OVERDUE]["open_balance"])
    assert 0 <= overdue <= open_balance
    assert (overdue, open_balance) == (D(FIX["ar-overdue-30d"]["overdue_30d"]), D(FIX["ar-overdue-30d"]["open_balance"]))
    return f"overdue_30d={overdue} <= open_balance={open_balance}"


async def eval_sc02():
    body = (await ok_call("receivable_aging")).data
    s = by_key(body["summary"], "counterparty_id")[PARTY_PARTIAL]
    total, applied, open_ = D(s["charged_total"]), D(s["payments_applied"]), D(s["open_balance"])
    assert total - applied == open_ > 0
    f = FIX["partial-payment"]
    assert (total, applied, open_) == (D(f["invoice_total"]), D(f["payments_applied"]), D(f["open_balance"]))
    return f"invoice {total} - applied {applied} = open {open_}"


async def eval_sc03():
    body = (await ok_call("receivable_aging")).data
    s = by_key(body["summary"], "counterparty_id")[PARTY_OVERPAID]
    row = by_key(body["rows"], "counterparty_id")[PARTY_OVERPAID]
    assert D(s["open_balance"]) == D(FIX["overpayment"]["invoice_open"]) == 0
    assert D(s["unapplied_credit"]) == D(row["unapplied_credit"]) == D(FIX["overpayment"]["unapplied_advance"]) > 0
    assert sum(D(v) for v in row["buckets"].values()) == 0, "advance must not leak into receivable buckets"
    return f"receivable open 0; unapplied advance {s['unapplied_credit']} kept separate"


async def eval_sc04():
    sales = by_key((await ok_call("sales_documents")).data["value"], "document_number")
    assert sales["SALE-003"]["posted"] is False and sales["SALE-001"]["posted"] is True
    assert "SALE-002" not in sales, "other company's document leaked"
    rows = (await ok_call("accounting_posting_rows", **WIDE)).data["value"]
    recorders = {r["recorder_ref"] for r in rows}
    unposted = sales["SALE-003"]["document_ref"]
    assert sales["SALE-001"]["document_ref"] in recorders, "posted document must have movements"
    assert unposted not in recorders
    movements = [r for r in rows if r["recorder_ref"] == unposted]
    assert len(movements) == FIX["unposted-document"]["movement_count"] == 0
    return "SALE-003 posted=false, 0 posting rows; SALE-001 posted with rows"


async def eval_sc05():
    moves = (await ok_call("inventory_movements")).data["value"]
    item2 = [D(r["quantity_delta"]) for r in moves if r["item_ref"] == ITEM_2]
    assert item2 == [D(10), D(-3)], "return recorded as a negative movement"
    assert D(10) - D(3) == sum(item2) == D(7)
    net: dict[str, Decimal] = {}
    for r in moves:
        net[r["item_ref"]] = net.get(r["item_ref"], D(0)) + D(r["quantity_delta"])
    bal = {r["item_ref"]: D(r["quantity"]) for r in (await ok_call("inventory_balance")).data["value"]}
    assert bal == net == {ITEM_1: D(5), ITEM_2: D(7)}
    return "item 002: receipt 10 - return 3 = on-hand 7; item 001 net 5 = balance 5"


async def eval_sc07():
    sales = by_key((await ok_call("sales_documents")).data["value"], "document_number")
    ref = sales["SALE-004"]["document_ref"]
    assert sales["SALE-004"]["date"].startswith(FIX["backdated-document"]["document_date"])
    dec = (await ok_call("accounting_posting_rows", **DECEMBER)).data["value"]
    assert [r["recorder_ref"] for r in dec] == [ref]
    assert dec[0]["period"][:7] == FIX["backdated-document"]["accounting_period"] == "2025-12"
    april = (await ok_call("accounting_posting_rows")).data["value"]
    assert ref not in {r["recorder_ref"] for r in april}
    return "SALE-004 dated 2025-12-31 posts in 2025-12 and not in April"


async def eval_sc09():
    cash = (await ok_call("cash_movements", **CASH_WINDOW)).data["value"]
    bank = (await ok_call("bank_balance")).data["value"]
    cash_total = sum(D(r["amount_delta"]) for r in cash)
    bank_total = sum(D(r["amount"]) for r in bank)
    f = FIX["cash-bank"]
    assert {r["cash_account_ref"] for r in cash}.isdisjoint({r["bank_account_ref"] for r in bank})
    assert (cash_total, bank_total, cash_total + bank_total) == (D(f["cash_balance"]), D(f["bank_balance"]), D(f["combined_balance"]))
    return f"cash {cash_total} + bank {bank_total} = combined {cash_total + bank_total}"


async def eval_sc10():
    out = await ok_call("accounting_balance_and_turnovers")
    (row,) = out.data["value"]
    opening, debit, credit, closing = (D(row[k]) for k in ("opening_debit", "debit_turnover", "credit_turnover", "closing_debit"))
    f = FIX["account-turnover"]
    assert (opening, debit, credit, closing) == (D(f["opening_debit"]), D(f["debit_turnover"]), D(f["credit_turnover"]), D(f["closing_debit"]))
    assert opening + debit - credit == closing
    return f"{opening} + {debit} - {credit} = {closing}"


async def eval_sc11():
    moves = (await ok_call("inventory_movements")).data["value"]
    item1 = [r for r in moves if r["item_ref"] == ITEM_1]
    receipts = sum(D(r["quantity_delta"]) for r in item1 if r["direction"] == "receipt")
    expense = [D(r["quantity_delta"]) for r in item1 if r["direction"] == "expense"]
    f = FIX["inventory-receipt-expense"]
    assert all(e < 0 for e in expense) and sum(expense) == D(f["expense_delta"])
    assert receipts == D(f["receipt_quantity"]) and receipts + sum(expense) == D(f["net_quantity"]) > 0
    return f"item 001 receipt {receipts} + expense {sum(expense)} = net {receipts + sum(expense)}"


async def eval_sc12():
    cash = (await ok_call("cash_movements")).data["value"]
    receipts = sum(D(r["amount_delta"]) for r in cash if r["direction"] == "receipt")
    expense = [D(r["amount_delta"]) for r in cash if r["direction"] == "expense"]
    f = FIX["cash-receipt-expense"]
    assert all(e < 0 for e in expense) and sum(expense) == D(f["expense_delta"])
    assert receipts == D(f["receipt_amount"]) and receipts + sum(expense) == D(f["net_amount"]) > 0
    return f"April receipts {receipts} + expense {sum(expense)} = net {receipts + sum(expense)}"


async def eval_sc08():
    body = (await ok_call("counterparty_duplicate_candidates")).data
    f = FIX["duplicate-counterparty"]
    assert body["status"] == "FINDING" and body["reason"] == "DUPLICATE_CANDIDATES_FOUND"
    assert body["match_rule"] == "normalized_name_v1"
    assert body["candidate_count"] == f["candidate_count"] == 2
    assert body["merge_count"] == f["merge_count"] == 0 and isinstance(body["merge_count"], int)
    assert body["group_count"] == 1 and body["truncated"] is False
    assert body["native_approval_inferred"] is False and body["human_review_required"] is True
    groups = body["groups"]
    assert len(groups) == body["group_count"] <= 200, "groups must be bounded"
    (group,) = groups
    assert group["match_basis"] == "NORMALIZED_NAME" and group["group_id"].startswith("dup-")
    members = group["members"]
    assert len(members) == body["candidate_count"] <= 200
    assert {m["counterparty_id"] for m in members} == {PARTY_DUP_A, PARTY_DUP_B}
    assert {m["code"] for m in members} == {"C001", "C001D"}
    assert {m["name"] for m in members} == {"Synthetic customer"}
    assert sorted(members, key=lambda m: m["code"]) == [
        {"counterparty_id": PARTY_DUP_A, "code": "C001", "name": "Synthetic customer"},
        {"counterparty_id": PARTY_DUP_B, "code": "C001D", "name": "Synthetic customer"},
    ], "exactly the two in-scope namesakes, with no extra member or field"
    # Scoping guard: the catalog holds BOTH namesakes, but company two has activity for only one
    # of them, so it must get no pair. Dropping the activity/company scoping would report one.
    two = (await ok_call("counterparty_duplicate_candidates", h.COMPANY_TWO)).data
    assert (two["status"], two["candidate_count"], two["groups"]) == ("PASS", 0, [])
    return f"1 group of {len(members)} duplicate counterparties (C001, C001D); merge_count=0"


EVALUATORS = {"SC01": eval_sc01, "SC02": eval_sc02, "SC03": eval_sc03, "SC04": eval_sc04,
              "SC05": eval_sc05, "SC07": eval_sc07, "SC08": eval_sc08, "SC09": eval_sc09,
              "SC10": eval_sc10, "SC11": eval_sc11, "SC12": eval_sc12}


@pytest.mark.parametrize("case", IDS)
async def test_scenario_positive_contract(case):
    spec = SPECS[case]
    if "disposition" in spec:
        tools = await h.list_tool_names()
        # Fail loudly if a matching tool appears: the disposition must then be re-evaluated.
        assert not [t for t in tools if re.search(spec["missing_regex"], t)], f"{case}: new tool appeared"
        status = spec["disposition"]
        record(case, observed_status=status, public_tool=spec["tools"][0], question=spec["question"],
               positive_summary=spec["missing"], missing=spec["missing"])
        pytest.xfail(f"{status} {case} ({spec['slug']}): {spec['missing']}")
    summary = await EVALUATORS[case]()
    record(case, observed_status="PASS", public_tool=" + ".join(spec["tools"]),
           question=spec["question"], positive_summary=summary)


# ---------------------------------------------------------------- negatives

@pytest.mark.parametrize("case", IDS)
async def test_scenario_negative_wrong_company_denied_before_upstream(case):
    spec = SPECS[case]
    tool = spec["tools"][0]
    args = args_for(tool, h.SOURCE_ID, h.rand_uuid())
    out = await h.call(tool, args)
    assert out.is_error and out.transport_error is None and "Traceback" not in out.text
    last = h.final_audit(out)
    assert (last["outcome"], last["detail_code"]) == ("denied", "AccessDenied")
    assert str(last["company_id"]) == args["company_id"]
    assert h.business_reads(out) == [], "denied call reached a business read"
    assert h.no_write_reached_1c(out)
    record(case, negative_wrong_company="random company id: denied AccessDenied; zero business reads",
           audit_negative=[{"tool": tool, "outcome": "denied", "detail": "AccessDenied"}])


@pytest.mark.parametrize("case", [c for c in IDS if SPECS[c]["neg_tool"]])
async def test_scenario_negative_unsupported_capability_fails_closed(case):
    """A related capability with no validated/fixture profile must deny, never guess an entity."""
    tool = SPECS[case]["neg_tool"]
    out = await h.call(tool, args_for(tool, h.SOURCE_ID, h.COMPANY_ONE))
    assert out.is_error and out.transport_error is None
    last = h.final_audit(out)
    assert (last["outcome"], last["detail_code"]) == ("denied", "SEMANTIC_PROFILE_UNVALIDATED")
    assert h.business_reads(out) == [] and h.no_write_reached_1c(out)
    record(case, negative_capability=f"{tool}: denied SEMANTIC_PROFILE_UNVALIDATED (no profile), zero business reads")


async def _isolation(case: str):
    """Company two must never see company one's rows for the scenario's own tools."""
    two = h.COMPANY_TWO
    if case in {"SC01", "SC02", "SC03"}:
        body = (await ok_call("receivable_aging", two)).data
        parties = {r["counterparty_id"] for r in body["summary"]}
        assert parties == {PARTY_OVERDUE}, parties
        assert by_key(body["summary"], "counterparty_id")[PARTY_OVERDUE]["open_balance"] == "999"
    elif case in {"SC04", "SC07"}:
        sales = {r["document_number"] for r in (await ok_call("sales_documents", two)).data["value"]}
        assert sales.isdisjoint({"SALE-001", "SALE-003", "SALE-004"}), sales
        assert (await ok_call("accounting_posting_rows", two, **WIDE)).data["value"] == []
    elif case in {"SC05", "SC11"}:
        assert (await ok_call("inventory_movements", two)).data["value"] == []
        assert (await ok_call("inventory_balance", two)).data["value"] == []
    elif case in {"SC09", "SC12"}:
        assert (await ok_call("cash_movements", two, **CASH_WINDOW)).data["value"] == []
        assert (await ok_call("bank_balance", two)).data["value"] == []
    elif case == "SC10":
        assert (await ok_call("accounting_balance_and_turnovers", two)).data["value"] == []
    elif case == "SC08":
        body = (await ok_call("counterparty_duplicate_candidates", two)).data
        assert body["status"] == "PASS" and body["reason"] == "NO_DUPLICATE_CANDIDATES"
        assert (body["candidate_count"], body["group_count"], body["merge_count"]) == (0, 0, 0)
        assert body["groups"] == []
        text = json.dumps(body, ensure_ascii=False)
        assert PARTY_DUP_A not in text and PARTY_DUP_B not in text
        assert "Synthetic customer" not in text
    else:
        pytest.skip(f"{case}: no data tool")
    record(case, negative_company_scope="company two receives none of company one's rows")


@pytest.mark.parametrize("case", [c for c in IDS if "disposition" not in SPECS[c]])
async def test_scenario_negative_company_isolation(case):
    await _isolation(case)


async def test_sc01_naive_timestamp_rejected_before_any_business_read():
    out = await h.call("receivable_aging", {**args_for("receivable_aging", h.SOURCE_ID, h.COMPANY_ONE), "as_of": "2026-04-30"})
    assert out.is_error and h.business_reads(out) == []
    record("SC01", negative_input="naive as_of rejected; zero business reads")


async def test_sc10_naive_timestamps_rejected_before_any_register_read():
    out = await h.call("accounting_balance_and_turnovers", {
        **args_for("accounting_balance_and_turnovers", h.SOURCE_ID, h.COMPANY_ONE),
        "start_period": "2026-04-01", "end_period": "2026-04-30"})
    assert out.is_error and h.business_reads(out) == []
    record("SC10", negative_input="naive start/end rejected; zero register reads")


async def test_sc01_truncated_aging_is_inconclusive_not_partial():
    out = await h.call("receivable_aging", args_for("receivable_aging", h.SOURCE_ID, h.COMPANY_ONE, top=3))
    assert out.ok and out.data["status"] == "INCONCLUSIVE" and out.data["reason"] == "AGING_ROWS_TRUNCATED"
    assert out.data["rows"] == [] and out.data["summary"] == [] and out.data["truncated"] is True
    record("SC01", bounded="top=3 -> INCONCLUSIVE AGING_ROWS_TRUNCATED with no partial answer")


async def test_sc08_truncated_scan_is_inconclusive_not_partial():
    tool = "counterparty_duplicate_candidates"
    out = await h.call(tool, args_for(tool, h.SOURCE_ID, h.COMPANY_ONE, top=3))
    assert out.ok, out.text or out.transport_error
    body = out.data
    assert body["status"] == "INCONCLUSIVE" and body["reason"] == "COUNTERPARTY_ROWS_TRUNCATED"
    assert body["groups"] == [] and body["truncated"] is True
    assert body["candidate_count"] == 0 and body["group_count"] == 0 and body["merge_count"] == 0
    assert h.no_write_reached_1c(out)
    assert h.final_audit(out)["outcome"] == "error"
    record("SC08", bounded="top=3 -> INCONCLUSIVE COUNTERPARTY_ROWS_TRUNCATED with no partial answer")


# ---------------------------------------------------------------- correlation / audit evidence

@pytest.mark.parametrize("case", IDS)
async def test_scenario_request_correlation_and_company_scope_in_audit(case):
    tool = SPECS[case]["tools"][0]
    out = await h.call(tool, args_for(tool, h.SOURCE_ID, h.COMPANY_ONE))
    assert len(out.audit) == 2, [r["detail_code"] for r in out.audit]
    ids = {str(r["request_id"]) for r in out.audit}
    assert len(ids) == 1, "predispatch + completion rows must share one request/correlation id"
    assert [r["detail_code"] for r in out.audit] == ["ACCESS_AUTHORIZED", FIXTURE_CODE]
    assert {r["principal_subject"] for r in out.audit} == {h.PRINCIPAL}
    assert {r["source_id"] for r in out.audit} == {h.SOURCE_ID}
    assert {str(r["company_id"]) for r in out.audit} == {h.COMPANY_ONE}
    request_id = ids.pop()
    if h.env("FT_GATEWAY_LOG"):
        assert h.log_has_request_id(request_id), "request id not found in gateway log"
    assert h.no_write_reached_1c(out)
    record(case, request_id=request_id,
           audit_rows=[{"outcome": r["outcome"], "detail_code": r["detail_code"]} for r in out.audit])
