"""SC01..SC12 black-box scenario contracts through the public MCP tools.

Every test calls the real gateway over Streamable HTTP. Statuses are OBSERVED, never assumed:

* PASS            the tool answered and the declared invariant held on the live response
* EXTERNAL-GATE   the tool exists but fails closed (no VALIDATED semantic profile; the DB check
                  constraint requires ten native 1C report cases, which no synthetic run can supply)
* NOT IMPLEMENTED no public tool/data can represent the scenario

Fake1C is synthetic L1 evidence only; nothing here is native 1C reconciliation.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest

from tests.functional.support import harness as h
from tests.functional.support.evidence import record
from tests.functional.support.specs import FIX, SPECS, build_args

IDS = sorted(SPECS)
GATE_CODES = {"SEMANTIC_PROFILE_UNVALIDATED", "CAPABILITY_UNSUPPORTED"}


def _dec(x) -> Decimal:
    return Decimal(str(x))


async def _gated(case: str):
    spec = SPECS[case]
    args = build_args(spec, h.SOURCE_ID, h.COMPANY_ONE)
    return spec, args, await h.call(spec["tool"], args)


def _assert_denied_closed(out: h.Outcome, company: str | None):
    """A denied/failed business call: sanitized error, audited, no business-data fetch."""
    assert out.is_error and out.transport_error is None, out.transport_error
    assert "Traceback" not in out.text and "password" not in out.text.lower()
    last = h.final_audit(out)
    assert last["outcome"] in {"denied", "error"}, last["outcome"]
    assert last["detail_code"], "audit row must carry a safe detail code"
    if company:
        assert str(last["company_id"]) == company
    assert not [r for r in out.upstream if "$filter" in r["query_keys"]], "business read leaked upstream"
    assert {r["method"] for r in out.upstream} <= {"GET", "HEAD"}


@pytest.mark.parametrize("case", IDS)
async def test_scenario_positive_contract(case):
    spec, args, out = await _gated(case)
    tools = await h.list_tool_names()
    tool_present = spec["tool"] in tools
    surface_gap = spec.get("force_not_implemented") or (
        spec["kind"] == "missing" and not any(re.search(spec["missing_regex"], t) for t in tools)
    )
    if surface_gap:
        # Fail closed AND surface check: if a matching tool appears this branch stops applying
        # and the test fails loudly so the evaluator gets written.
        record(case, observed_status="NOT IMPLEMENTED", public_tool=spec["tool"] if tool_present else None,
               missing=spec["missing"], question=spec["question"])
        if out.is_error:
            _assert_denied_closed(out, h.COMPANY_ONE) if spec["tool"] != "onec_read" else None
        pytest.xfail(f"NOT IMPLEMENTED {case} ({spec['slug']}): needs {spec['missing']}")
    if out.ok:
        _evaluate_success(case, out)
        record(case, observed_status="PASS", public_tool=spec["tool"], question=spec["question"])
        return
    _assert_denied_closed(out, h.COMPANY_ONE)
    code = h.final_audit(out)["detail_code"]
    assert code in GATE_CODES, f"unexpected failure code {code!r}"
    record(case, observed_status="EXTERNAL-GATE", public_tool=spec["tool"], gate_code=code,
           missing=spec["missing"], question=spec["question"])
    pytest.xfail(f"EXTERNAL-GATE {case}: {spec['tool']} denied with {code}; needs {spec['missing']}")


def _evaluate_success(case: str, out: h.Outcome):
    data = out.data
    rows = data["value"]
    if case == "SC11":
        deltas = [_dec(r["quantity_delta"]) for r in rows]
        receipts = sum(d for d in deltas if d > 0)
        expense = [d for d in deltas if d < 0]
        assert all(r["direction"] == "expense" for r, d in zip(rows, deltas) if d < 0)
        assert sum(expense) == _dec(FIX["inventory-receipt-expense"]["expense_delta"])
        assert receipts + sum(expense) == _dec(FIX["inventory-receipt-expense"]["net_quantity"])
    elif case == "SC12":
        deltas = [_dec(r["amount_delta"]) for r in rows]
        receipts = sum(d for d in deltas if d > 0)
        expense = [d for d in deltas if d < 0]
        assert sum(expense) == _dec(FIX["cash-receipt-expense"]["expense_delta"])
        assert receipts + sum(expense) == _dec(FIX["cash-receipt-expense"]["net_amount"])
    else:
        pytest.fail(f"{case}: tool now answers; extend the evaluator for its profile-defined fields")
    assert len(rows) <= 200


@pytest.mark.parametrize("case", IDS)
async def test_scenario_negative_wrong_company_denied_before_upstream(case):
    spec = SPECS[case]
    if spec["tool"] == "onec_read":
        pytest.skip("SC08 has no company-aware public tool (NOT IMPLEMENTED); see positive case")
    args = build_args(spec, h.SOURCE_ID, h.rand_uuid())
    out = await h.call(spec["tool"], args)
    _assert_denied_closed(out, args["company_id"])
    assert h.final_audit(out)["detail_code"] == "AccessDenied"
    assert [r for r in out.upstream if "$filter" in r["query_keys"]] == []
    record(case, negative_wrong_company="denied AccessDenied; no upstream business read",
           audit_negative=[{"tool": spec["tool"], "outcome": "denied", "detail": "AccessDenied"}])


@pytest.mark.parametrize("case", IDS)
async def test_scenario_negative_unsupported_capability_fails_closed(case):
    """With company access but no validated profile/capability the tool must deny, never guess."""
    spec = SPECS[case]
    if spec["tool"] == "onec_read":
        pytest.skip("raw onec_read is not a semantic capability")
    out = await h.call(spec["tool"], build_args(spec, h.SOURCE_ID, h.COMPANY_ONE))
    if out.ok:
        pytest.skip(f"{spec['tool']} is enabled in this environment; capability negative n/a")
    _assert_denied_closed(out, h.COMPANY_ONE)
    assert h.final_audit(out)["detail_code"] in GATE_CODES
    record(case, negative_capability=f"{spec['tool']} fail-closed {h.final_audit(out)['detail_code']}")


@pytest.mark.parametrize("case", IDS)
async def test_scenario_request_correlation_and_company_scope_in_audit(case):
    spec = SPECS[case]
    if spec["tool"] == "onec_read":
        args = build_args(spec, h.SOURCE_ID, h.COMPANY_ONE)
    else:
        args = build_args(spec, h.SOURCE_ID, h.COMPANY_ONE)
    out = await h.call(spec["tool"], args)
    assert out.audit, "every call must be audited"
    ids = {str(r["request_id"]) for r in out.audit}
    assert len(ids) == 1, "predispatch + completion rows must share one request/correlation id"
    assert {r["principal_subject"] for r in out.audit} == {h.PRINCIPAL}
    assert {r["source_id"] for r in out.audit} == {h.SOURCE_ID}
    if spec["tool"] != "onec_read":
        assert {str(r["company_id"]) for r in out.audit} == {h.COMPANY_ONE}
    request_id = ids.pop()
    if h.env("FT_GATEWAY_LOG"):
        assert h.log_has_request_id(request_id), "request id not found in gateway log"
    record(case, request_id=request_id, audit_rows=[
        {"outcome": r["outcome"], "detail_code": r["detail_code"]} for r in out.audit])
    assert {r["method"] for r in out.upstream} <= {"GET", "HEAD"}
    assert len(out.audit) <= 4
    if out.ok and isinstance(out.data, dict) and isinstance(out.data.get("value"), list):
        assert len(out.data["value"]) <= 200, "result must be bounded by max_rows"
