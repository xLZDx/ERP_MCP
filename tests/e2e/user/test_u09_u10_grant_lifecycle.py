"""U09/U10 - revoke the exact grant via the Admin API, then re-grant; no gateway restart.

The grant is the baseline UC1 -> company one subject grant. The registry reads grants from
PostgreSQL on every call (no allow cache), so the very next call after revocation must be denied
and the very next call after re-granting must be authorized again.
"""

from __future__ import annotations

import uuid

import pytest
from user_support import audit_since, db_clock, receipts

pytestmark = [pytest.mark.user]


def _args(ids) -> dict:
    return {"source_id": ids["source"], "company_id": ids["one"], "top": 5}


async def _admin_events(db, **filters) -> list[dict]:
    clauses = " AND ".join(f"{key}=${n}" for n, key in enumerate(filters, 1))
    return await db.fetch(
        f"SELECT action, outcome, actor_subject, reason FROM bag.admin_audit_events "
        f"WHERE {clauses} ORDER BY occurred_at", *filters.values(), role="control")


async def test_u09_revoked_grant_denies_next_call_without_restart(
        db, call, tokens, ids, uc1_company_grant, fake1c_log):
    grant = uc1_company_grant.active("subject", ids["uc1"], ids["one"])
    assert grant is not None
    since = await db_clock(db)
    before = await call(tokens["uc1"], "companies_list", {"source_id": ids["source"]})
    assert [c["company_id"] for c in before.payload] == [ids["one"]]
    await call(tokens["uc1"], "sales_documents", _args(ids))
    rows_before = await audit_since(db, since, subject=ids["uc1"], tool="sales_documents")
    assert [str(r["company_id"]) for r in receipts(rows_before)] == [ids["one"]]

    uc1_company_grant.revoke(grant, f"E2E U09 revoke {uuid.uuid4().hex[:8]}")
    revoked = [e for e in await _admin_events(db, target_id=str(grant["grant_id"]))
               if e["action"] == "grant.revoke"]
    assert [e["outcome"] for e in revoked] == ["success"]

    mark, after_since = fake1c_log.mark(), await db_clock(db)
    after_list = await call(tokens["uc1"], "companies_list", {"source_id": ids["source"]})
    after_read = await call(tokens["uc1"], "sales_documents", _args(ids))  # same token, no wait
    assert after_list.payload in ([], None) or after_list.is_error
    assert after_read.is_error and after_read.payload is None
    rows_after = await audit_since(db, after_since, subject=ids["uc1"], tool="sales_documents")
    assert [r["outcome"] for r in rows_after] == ["denied"] and receipts(rows_after) == []
    assert fake1c_log.since(mark, gateway_only=False) == []


async def test_u10_regrant_restores_access_without_restart(
        db, call, tokens, ids, uc1_company_grant, fake1c_log):
    grant = uc1_company_grant.active("subject", ids["uc1"], ids["one"])
    assert grant is not None
    uc1_company_grant.revoke(grant, "E2E U10 precondition revoke")
    denied = await call(tokens["uc1"], "sales_documents", _args(ids))
    assert denied.is_error

    reason = f"E2E U10 re-grant {uuid.uuid4().hex[:8]}"
    created = uc1_company_grant.create("subject", ids["uc1"], ids["one"], reason)
    assert str(created["grant_id"]) != str(grant["grant_id"])  # a new exact grant, not an undo
    events = await _admin_events(db, action="grant.create", reason=reason)
    assert [e["outcome"] for e in events] == ["success"]

    since = await db_clock(db)
    again = await call(tokens["uc1"], "companies_list", {"source_id": ids["source"]})
    assert [c["company_id"] for c in again.payload] == [ids["one"]]
    await call(tokens["uc1"], "sales_documents", _args(ids))
    rows = await audit_since(db, since, subject=ids["uc1"], tool="sales_documents")
    assert [str(r["company_id"]) for r in receipts(rows)] == [ids["one"]]
