"""U17 - audit rows for success, deny and error calls; no tokens, secrets or accounting payloads.

Rows are read through the read-only evidence role (business_ai_admin has SELECT only on
bag.audit_events; UPDATE/DELETE are additionally blocked by a trigger).
"""

from __future__ import annotations

import re

import pytest
from user_support import (
    audit_since,
    completion_rows,
    db_clock,
    find_leaks,
    jsonable,
    seed,
)

pytestmark = [pytest.mark.user]

DETAIL_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _accounting_markers() -> set[str]:
    data = seed()
    markers = {row["Number"] for key in ("sales", "purchases") for row in data[key]}
    markers |= {row["Description"] for row in data["organizations"] + data["counterparties"]}
    return markers


async def test_u17_success_deny_and_error_calls_are_audited_without_secrets(
        e2e_env, db, call, tokens, ids, grants):
    since = await db_clock(db)
    expected = []  # (subject, tool, outcome, source_id)

    ok_status = await call(tokens["uc1"], "system_status")
    ok_sources = await call(tokens["uc1"], "sources_list")
    ok_companies = await call(tokens["uc1"], "companies_list", {"source_id": ids["source"]})
    assert ok_status.ok and ok_sources.ok and ok_companies.ok
    expected += [(ids["uc1"], "system_status", "success", None),
                 (ids["uc1"], "sources_list", "success", None),
                 (ids["uc1"], "companies_list", "success", ids["source"])]

    deny_una = await call(tokens["una"], "source_health", {"source_id": ids["source"]})
    deny_uc1 = await call(tokens["uc1"], "sales_documents", {
        "source_id": ids["source"], "company_id": ids["two"]})
    assert deny_una.is_error and deny_uc1.is_error
    expected += [(ids["una"], "source_health", "denied", ids["source"]),
                 (ids["uc1"], "sales_documents", "denied", ids["source"])]

    with grants.temporary_source_wide(ids["uc1"]):
        error = await call(tokens["uc1"], "onec_read", {
            "source_id": ids["source"], "entity_set": "Catalog_DoesNotExist", "top": 1})
    assert error.is_error
    expected.append((ids["uc1"], "onec_read", "error", ids["source"]))

    rows = await audit_since(db, since)
    final = completion_rows(rows)
    for subject, tool, outcome, source_id in expected:
        match = [r for r in final if r["principal_subject"] == subject and r["tool_name"] == tool
                 and r["source_id"] == source_id]
        assert [r["outcome"] for r in match] == [outcome], (subject, tool, [m["outcome"] for m in match])
        assert match[0]["client_id"] and match[0]["request_id"] and match[0]["duration_ms"] >= 0
        if outcome != "success":
            assert match[0]["detail_code"] and DETAIL_CODE.match(match[0]["detail_code"])

    # Evidence = request id: the pre-dispatch receipt and the completion of one call share it,
    # and different calls never share one.
    onec_rows = [r for r in rows if r["tool_name"] == "onec_read" and r["principal_subject"]
                 == ids["uc1"]]
    assert len({r["request_id"] for r in onec_rows}) == 1 and len(onec_rows) == 2
    by_call = {}
    for row in final:
        by_call.setdefault(row["request_id"], []).append(row["tool_name"])
    assert len(by_call) == len(final), "two completions share one request id"

    # No tokens, credentials or accounting payloads anywhere in the stored rows.
    assert all(r["query_json"] is None for r in rows)  # raw filters are never persisted
    blob = jsonable([{k: v for k, v in r.items() if k != "event_id"} for r in rows])
    assert find_leaks(blob, e2e_env, extra=tuple(tokens.values())) == []
    leaked = [m for m in _accounting_markers() if m in blob]
    assert not leaked, f"accounting payload markers in audit: {leaked}"
    assert not [t for t in ("Authorization", "Bearer", "password", "secret") if t.lower() in
                blob.lower()]
