"""U14-U16 - Fake1C, PostgreSQL and Redis outages with recovery and no gateway restart.

Every outage runs inside `outage(...)`, whose `finally` always starts the component again.
These tests stop disposable components of the local environment only (scripts/e2e/fault.ps1).
The gateway process is never restarted: recovery is proven by a later successful call.
"""

from __future__ import annotations

import re

import pytest
from user_support import (
    audit_since,
    await_until,
    completion_rows,
    db_clock,
    find_leaks,
    metric_value,
    outage,
)

pytestmark = [pytest.mark.user]

BOUND_SECONDS = 30


# Sanitized audit detail codes are identifiers only: no host, port, URL, DSN or credential.
_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _assert_outage_outcome(outcome) -> None:
    """The gateway was REACHABLE: a transport-level failure would make the test vacuous."""
    assert outcome.transport_error is None, outcome.transport_error
    assert outcome.is_error and outcome.payload is None, outcome


def _assert_code(detail_code: str | None, e2e_env) -> None:
    assert detail_code and _CODE.fullmatch(detail_code), detail_code
    assert find_leaks(detail_code, e2e_env) == []


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
            # Entity data is read through the sidecar (unaffected by a Fake1C outage); live
            # metadata still comes from Fake1C itself, so it must fail closed too.
            read_down = await call(tokens["uc1"], "onec_metadata_summary", {
                "source_id": ids["source"], "refresh": True})
        for outcome in (down, read_down):
            _assert_outage_outcome(outcome)
            assert outcome.elapsed < BOUND_SECONDS, outcome.elapsed
            _assert_sanitized(outcome.text, e2e_env, fake_port, "standard.odata",
                              e2e_env.secrets["fake1c_username"],
                              e2e_env.secrets["fake1c_password"], "127.0.0.1")
        recovered = await _recover(call, tokens["uc1"], "source_health", args,
                                   "source_health success after Fake1C restart")
        assert recovered.payload == {"status_code": 200, "ok": True}
        rows = completion_rows(await audit_since(db, since, subject=ids["uc1"]))
    during = [r for r in rows if r["tool_name"] in ("source_health", "onec_metadata_summary")
              and r["outcome"] == "error"]
    assert {r["tool_name"] for r in during} == {"source_health", "onec_metadata_summary"}, rows
    for row in during:  # the sanitized detail code is what the audit keeps
        _assert_code(row["detail_code"], e2e_env)
    health = [r for r in rows if r["tool_name"] == "source_health"]
    assert health[0]["outcome"] == "error" and health[-1]["outcome"] == "success", health


async def test_u14_sidecar_outage_fails_closed_for_entity_reads_then_recovers(
        e2e_env, db, call, tokens, ids, grants):
    read_args = {"source_id": ids["source"], "entity_set": "Catalog_Organizations", "top": 1}
    sidecar_port = str(e2e_env.raw["ports"]["sidecar"])
    with grants.temporary_source_wide(ids["uc1"]):
        healthy = await call(tokens["uc1"], "onec_read", read_args)
        assert healthy.ok and healthy.payload["value"], healthy
        since = await db_clock(db)
        with outage("sidecar"):
            down = await call(tokens["uc1"], "onec_read", read_args)
        _assert_outage_outcome(down)
        assert down.elapsed < BOUND_SECONDS, down.elapsed
        _assert_sanitized(down.text, e2e_env, sidecar_port, "/v1/read",
                          e2e_env.secrets["sidecar_token"])
        recovered = await _recover(call, tokens["uc1"], "onec_read", read_args,
                                   "onec_read success after sidecar restart")
        assert recovered.payload["value"] == healthy.payload["value"]
        rows = completion_rows(await audit_since(db, since, subject=ids["uc1"], tool="onec_read"))
    assert rows[0]["outcome"] == "error" and rows[-1]["outcome"] == "success", rows
    _assert_code(rows[0]["detail_code"], e2e_env)


# ------------------------------------------------------------------------------------- U15


async def test_u15_postgres_outage_fails_closed_then_recovers(
        e2e_env, db, call, tokens, ids, grants):
    read_args = {"source_id": ids["source"], "entity_set": "Catalog_Organizations", "top": 1}
    # A call that SUCCEEDS while healthy (source-wide grant created through the Admin API
    # BEFORE the outage), so the failure below is caused by the outage and nothing else.
    with grants.temporary_source_wide(ids["uc1"]):
        healthy = await call(tokens["uc1"], "onec_read", read_args)
        assert healthy.ok and healthy.payload["value"], healthy
        stopped_at = await db_clock(db)
        with outage("postgres"):
            status = await call(tokens["uc1"], "system_status")
            read = await call(tokens["uc1"], "onec_read", read_args)
            company_read = await call(tokens["uc1"], "sales_documents", {
                "source_id": ids["source"], "company_id": ids["one"], "top": 5})
        restored_at = await db_clock(db)
        for outcome in (status, read, company_read):  # no authorization without the database
            _assert_outage_outcome(outcome)
            assert outcome.elapsed < 2 * BOUND_SECONDS, outcome.elapsed
            _assert_sanitized(outcome.text, e2e_env, str(e2e_env.raw["ports"]["postgres"]),
                              "business_ai_app", e2e_env.secrets["pg_app_password"])
        recovered = await _recover(call, tokens["uc1"], "onec_read", read_args,
                                   "onec_read success after PostgreSQL restart")
        assert recovered.payload["value"] == healthy.payload["value"]  # same data as before
        rows = await audit_since(db, stopped_at, subject=ids["uc1"])
    # While PostgreSQL was down nothing could be audited, and nothing was ever allowed.
    during = [r for r in rows if r["occurred_at"] < restored_at]
    assert [r for r in during if r["outcome"] == "success"] == [], during
    after = [r for r in rows if r["occurred_at"] >= restored_at and r["tool_name"] == "onec_read"]
    assert after and after[-1]["outcome"] == "success"  # audit written after recovery
    # No audit row can exist for the failed calls (the audit store IS the outage); their
    # sanitized client text is asserted above.


# ------------------------------------------------------------------------------------- U16


async def test_u16_redis_outage_fails_closed_for_rate_limited_tools_then_recovers(
        e2e_env, db, call, tokens, ids):
    args = {"source_id": ids["source"]}
    assert (await call(tokens["uc1"], "companies_list", args)).ok
    since = await db_clock(db)
    errors_before = metric_value(e2e_env, "erp_mcp_operations_total", tool="companies_list",
                                 outcome="error")
    with outage("redis"):
        limited = await call(tokens["uc1"], "companies_list", args)
        unlimited = await call(tokens["uc1"], "system_status")
    # Observed contract (src/business_ai_gateway/rate_limit.py + server.resolve_source): the
    # per-minute limiter is consulted by source/company tools only; with Redis down they FAIL
    # CLOSED (no silent bypass of the limit) while tools that never touch the limiter
    # (system_status, sources_list) keep working. Recorded, not widened.
    _assert_outage_outcome(limited)
    assert limited.elapsed < BOUND_SECONDS, limited.elapsed
    _assert_sanitized(limited.text, e2e_env, str(e2e_env.raw["ports"]["redis"]),
                      e2e_env.secrets["redis_password"])
    assert unlimited.transport_error is None and unlimited.ok
    assert unlimited.payload["subject"] == ids["uc1"]

    rows = completion_rows(await audit_since(db, since, subject=ids["uc1"],
                                             tool="companies_list"))
    assert [r["outcome"] for r in rows] == ["error"], rows
    _assert_code(rows[0]["detail_code"], e2e_env)
    # The /metrics endpoint (BAG_METRICS_TOKEN) counts the failed operation as an error.
    errors_after = metric_value(e2e_env, "erp_mcp_operations_total", tool="companies_list",
                                outcome="error")
    assert errors_after == errors_before + 1, (errors_before, errors_after)

    recovered = await _recover(call, tokens["uc1"], "companies_list", args,
                               "companies_list success after Redis restart")
    assert [c["company_id"] for c in recovered.payload] == [ids["one"]]
    final = completion_rows(await audit_since(db, since, subject=ids["uc1"],
                                              tool="companies_list"))
    assert final[-1]["outcome"] == "success"
