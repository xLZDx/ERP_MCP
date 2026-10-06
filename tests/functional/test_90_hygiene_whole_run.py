"""Whole-run proofs (file name sorts last): read-only upstream, no sensitive data in audit/logs."""

from __future__ import annotations

import json
import re

import pytest

from tests.functional.support import harness as h
from tests.functional.support.evidence import record

SENSITIVE_VALUES = ["synthetic-password", "SALE-001", "SALE-002", "PUR-001", "Synthetic customer", "Synthetic supplier"]


def _secrets() -> list[str]:
    vals = [v for v in (h.env("FT_BEARER_TOKEN"), h.env("FT_BEARER_TOKEN_NO_ACCESS"),
                        h.env("FT_BEARER_TOKEN_COMPANY_TWO")) if v]
    for var in ("FT_ADMIN_DATABASE_URL", "BAG_DATABASE_URL", "BAG_REDIS_URL"):
        url = h.env(var)
        m = re.match(r"^[a-z]+://[^:]+:([^@]+)@", url or "")
        if m:
            vals.append(m.group(1))
    return vals


def test_only_get_head_reached_1c_during_whole_run(suite_start):
    reqs = h.fake_requests(suite_start["fake_seq"])["requests"]
    assert reqs, "suite produced no upstream traffic - evidence would be vacuous"
    methods = sorted({r["method"] for r in reqs})
    assert set(methods) <= {"GET", "HEAD"}, methods
    record("ALL", upstream_methods=methods, upstream_request_count=len(reqs))


async def test_audit_rows_contain_no_tokens_credentials_or_raw_accounting_rows(suite_start):
    rows = await h.db_fetch("SELECT * FROM bag.audit_events WHERE occurred_at >= $1", suite_start["db"])
    assert rows
    blob = json.dumps(rows, default=str, ensure_ascii=False)
    for needle in SENSITIVE_VALUES + _secrets():
        assert needle not in blob, f"sensitive value leaked into audit: {needle[:4]}..."
    assert not re.search(r"eyJ[A-Za-z0-9_-]{10,}\.", blob), "JWT-shaped string in audit"
    assert not re.search(r"Bearer\s+\S{8,}", blob)
    # Audit stores query shape + counts only, never result rows.
    assert all(r["query_json"] is None or "value" not in r["query_json"] for r in rows)
    record("ALL", audit_rows_scanned=len(rows))


def test_gateway_log_contains_no_tokens_credentials_or_raw_accounting_rows():
    text = h.gateway_log_text()
    if text is None:
        pytest.skip("FT_GATEWAY_LOG not provided; log scan not run (set it to the gateway log file)")
    assert "http_request" in text, "log capture is empty - scan would be vacuous"
    flat = re.sub(r"\s+", "", text)
    for needle in SENSITIVE_VALUES + _secrets():
        assert re.sub(r"\s+", "", needle) not in flat, f"sensitive value in gateway log: {needle[:4]}..."
    assert not re.search(r"eyJ[A-Za-z0-9_-]{10,}\.", flat)
    record("ALL", gateway_log_bytes_scanned=len(text))
