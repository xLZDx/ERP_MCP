"""READ-ONLY live check of accounting_balance_by_analytics against the private real-1C test lane (127.0.0.1:21000).

Skipped (with a reason) when the gateway, the IdP token or the private artifacts are unavailable.  Only labels, counts
and totals are asserted; no row content is printed.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest

LANE = Path(r"D:\ERP_MCP_Testbed\real1c_e2e")
ARTIFACTS = LANE / "private_evidence" / "machine_reconciliation" / "artifacts"
SOURCE_ID = "onec-818ha-reference"
AS_OF = "2026-08-31T23:59:59+00:00"


def _call(user: str, company_id: str | None):
    from scripts.real1c.gateway_client import Idp, LaneEnv, call_tool, mcp_session

    env = LaneEnv.load()
    token = Idp(env).token(user)
    out = {}

    async def run():
        async with mcp_session(env, token) as session:
            if company_id is None:
                out["companies"] = await call_tool(session, "companies_list", {"source_id": SOURCE_ID})
                cid = out["companies"]["payload"][0]["company_id"]
            else:
                cid = company_id
            try:
                out["call"] = await call_tool(
                    session, "accounting_balance_by_analytics",
                    {"source_id": SOURCE_ID, "company_id": cid, "as_of": AS_OF},
                )
            except Exception as exc:  # noqa: BLE001 - a denied tool call may surface as any client exception
                out["call"] = {"is_error": True, "payload": None, "text": type(exc).__name__}

    try:
        asyncio.run(run())
    except BaseException:
        if "call" not in out:
            raise
        out["teardown_error"] = True
    return out


@pytest.fixture(scope="module")
def live():
    try:
        out = _call("user_company_one", None)
    except Exception as exc:  # noqa: BLE001 - any failure to reach the lane means skip
        pytest.skip(f"lane gateway/IdP unavailable: {type(exc).__name__}")
    if not ARTIFACTS.is_dir():
        pytest.skip("private machine artifacts are not present")
    return out


def _aggregate(rows, regroup=False):
    if regroup:  # the tool may split a key by an unselected third dimension; artifacts are summed per key
        rows = {(r["account"], tuple((a.get("role") or a.get("type"), a["ref"]) for a in r["analytics"]), r.get("currency_ref") or "")
                for r in rows}
        return len(rows)
    return (
        len(rows),
        sum((Decimal(str(r["balance_debit"])) for r in rows), Decimal(0)),
        sum((Decimal(str(r["balance_credit"])) for r in rows), Decimal(0)),
    )


def test_live_521_1_is_machine_labelled_company_scoped_and_matches_artifacts(live):
    call = live["call"]
    assert call["is_error"] is False
    body = call["payload"]
    company_id = live["companies"]["payload"][0]["company_id"]
    assert len(live["companies"]["payload"]) == 1  # the user sees exactly one company
    assert body["profile_kind"] == "VALIDATED_MACHINE_RECONCILED"
    assert body["evidence_level"] == "PROFILE_VALIDATED_MACHINE"
    assert body["native_reconciliation"] == "MACHINE_TWO_SOURCE"
    assert "MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT" in body["warnings"]
    assert body["company_id"] == company_id and body["source_id"] == SOURCE_ID
    assert body["truncated"] is False
    assert body["row_count"] == len(body["rows"]) > 0
    assert {r["account"] for r in body["rows"]} == {"521.1"}

    matched = []
    for case_dir in sorted(ARTIFACTS.glob("case-*")):
        a = json.loads((case_dir / "side_a.json").read_text(encoding="utf-8"))
        b = json.loads((case_dir / "side_b.json").read_text(encoding="utf-8"))
        if a["as_of"] == AS_OF:
            matched.append((a, b))
    assert len(matched) == 1, "expected exactly one private artifact case for the requested as_of"
    a, b = matched[0]
    assert _aggregate(a["rows"]) == _aggregate(b["rows"])
    live_totals = _aggregate(body["rows"])
    assert live_totals[1:] == _aggregate(a["rows"])[1:]  # debit and credit totals
    assert _aggregate(body["rows"], regroup=True) == len(a["rows"])  # distinct keys == artifact row count


def test_live_other_company_user_cannot_read_company_one(live):
    company_id = live["companies"]["payload"][0]["company_id"]
    try:
        other = _call("user_company_two", company_id)
    except Exception as exc:  # noqa: BLE001 - any failure to reach the lane means skip
        pytest.skip(f"second test user unavailable: {type(exc).__name__}")
    assert other["call"]["is_error"] is True
    assert not (other["call"]["payload"] or {}).get("rows")
