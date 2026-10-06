"""U14-U16 - Fake1C, PostgreSQL and Redis outages with recovery and no gateway restart.

Every outage runs inside `outage(...)`, whose `finally` always starts the component again.
These tests stop disposable components of the local environment only (scripts/e2e/fault.ps1).
The gateway process is never restarted: recovery is proven by a later successful call.
"""

from __future__ import annotations

import pytest
from user_support import (
    audit_since,
    await_until,
    completion_rows,
    db_clock,
    find_leaks,
    outage,
)

pytestmark = [pytest.mark.user]

BOUND_SECONDS = 30


def _assert_sanitized(text: str, e2e_env, *needles: str) -> None:
    assert "Traceback" not in text and find_leaks(text, e2e_env) == []
    for needle in needles:
        assert needle not in text, f"{needle!r} leaked into the client-visible error"


async def _recover(call, token, tool, args, what: str, timeout: int = 90):
    async def attempt():
        outcome = await call(token, tool, args)
        return outcome if outcome.ok else None

    return await await_until(attempt, timeout=timeout, interval=1.0, what=what)


# ------------------------------------------------------------------------------------- U14


async def test_u14_fake1c_outage_gives_sanitized_error_then_recovers(
        e2e_env, db, call, tokens, ids, grants, fake1c_log):
    args = {"source_id": ids["source"]}
    fake_port = str(e2e_env.raw["ports"]["fake1c"])
    with grants.temporary_source_wide(ids["uc1"]):
        assert (await call(tokens["uc1"], "source_health", args)).ok
        since = await db_clock(db)
        with outage("fake1c"):
            down = await call(tokens["uc1"], "source_health", args)
            read_down = await call(tokens["uc1"], "onec_read", {
                "source_id": ids["source"], "entity_set": "Catalog_Organizations", "top": 1})
        for outcome in (down, read_down):
            assert outcome.is_error and outcome.payload is None, outcome
            assert outcome.elapsed < BOUND_SECONDS, outcome.elapsed
            _assert_sanitized(outcome.text, e2e_env, fake_port, "standard.odata",
                              e2e_env.secrets["fake1c_username"],
                              e2e_env.secrets["fake1c_password"], "127.0.0.1")
        recovered = await _recover(call, tokens["uc1"], "source_health", args,
                                   "source_health success after Fake1C restart")
        assert recovered.payload == {"status_code": 200, "ok": True}
        rows = completion_rows(await audit_since(db, since, subject=ids["uc1"],
                                                 tool="source_health"))
    assert rows[0]["outcome"] == "error" and rows[-1]["outcome"] == "success", rows
    assert rows[0]["detail_code"] and "http" not in rows[0]["detail_code"].lower()


# ------------------------------------------------------------------------------------- U15


async def test_u15_postgres_outage_fails_closed_then_recovers(
        e2e_env, db, call, tokens, ids):
    assert (await call(tokens["uc1"], "system_status")).ok
    stopped_at = await db_clock(db)
    with outage("postgres"):
        status = await call(tokens["uc1"], "system_status")
        read = await call(tokens["uc1"], "sales_documents", {
            "source_id": ids["source"], "company_id": ids["one"], "top": 5})
    restored_at = await db_clock(db)
    for outcome in (status, read):  # no authorization decision without the database
        assert outcome.is_error and outcome.payload is None, outcome
        assert outcome.elapsed < 2 * BOUND_SECONDS, outcome.elapsed
        _assert_sanitized(outcome.text, e2e_env, str(e2e_env.raw["ports"]["postgres"]),
                          "business_ai_app", e2e_env.secrets["pg_app_password"])

    recovered = await _recover(call, tokens["uc1"], "system_status", {},
                               "system_status success after PostgreSQL restart")
    assert recovered.payload["subject"] == ids["uc1"]
    rows = await audit_since(db, stopped_at, subject=ids["uc1"])
    during = [r for r in rows if r["occurred_at"] < restored_at]
    assert [r for r in during if r["outcome"] == "success"] == [], during  # never allowed
    after = [r for r in rows if r["occurred_at"] >= restored_at and r["tool_name"] ==
             "system_status"]
    assert after and after[-1]["outcome"] == "success"  # audit written after recovery


# ------------------------------------------------------------------------------------- U16


async def test_u16_redis_outage_fails_closed_for_rate_limited_tools_then_recovers(
        e2e_env, db, call, tokens, ids):
    args = {"source_id": ids["source"]}
    assert (await call(tokens["uc1"], "companies_list", args)).ok
    since = await db_clock(db)
    with outage("redis"):
        limited = await call(tokens["uc1"], "companies_list", args)
        unlimited = await call(tokens["uc1"], "system_status")
    # Observed contract (src/business_ai_gateway/rate_limit.py + server.resolve_source): the
    # per-minute limiter is consulted by source/company tools only; with Redis down they FAIL
    # CLOSED (no silent bypass of the limit) while tools that never touch the limiter
    # (system_status, sources_list) keep working. Recorded, not widened.
    assert limited.is_error and limited.payload is None, limited
    assert limited.elapsed < BOUND_SECONDS, limited.elapsed
    _assert_sanitized(limited.text, e2e_env, str(e2e_env.raw["ports"]["redis"]),
                      e2e_env.secrets["redis_password"])
    assert unlimited.ok and unlimited.payload["subject"] == ids["uc1"]

    rows = completion_rows(await audit_since(db, since, subject=ids["uc1"],
                                             tool="companies_list"))
    assert [r["outcome"] for r in rows] == ["error"] and rows[0]["detail_code"], rows

    recovered = await _recover(call, tokens["uc1"], "companies_list", args,
                               "companies_list success after Redis restart")
    assert [c["company_id"] for c in recovered.payload] == [ids["one"]]
    final = completion_rows(await audit_since(db, since, subject=ids["uc1"],
                                              tool="companies_list"))
    assert final[-1]["outcome"] == "success"
