from __future__ import annotations

import uuid

import pytest

from business_ai_gateway.audit import Audit
from business_ai_gateway.principal import Principal


class FakePool:
    def __init__(self):
        self.args = None
        self.sql = None

    async def execute(self, sql, *args):
        self.sql, self.args = sql, args


class FakeDatabase:
    def __init__(self, pool):
        self.pool = pool

    def require_pool(self):
        return self.pool


@pytest.mark.asyncio
async def test_audit_writes_correlation_scope_and_adapter_provenance():
    pool = FakePool()
    audit = Audit(FakeDatabase(pool), include_query=False)
    request_id = uuid.uuid4()
    company_id = uuid.uuid4()

    await audit.write(
        principal=Principal(
            subject="subject-1",
            client_id="client-1",
            scopes=frozenset(),
            groups=frozenset(),
            claims={},
        ),
        tool="onec_read",
        source_id="source-1",
        outcome="success",
        started_at=0,
        request_id=request_id,
        company_id=company_id,
        adapter_kind="ODATA_V3",
        adapter_version="0.6.0",
        upstream_sha="abc123",
        policy_version="policy-7",
        metadata_fingerprint="sha256:metadata",
        returned_items=4,
        response_bytes=512,
        truncated=True,
    )

    assert "request_id, company_id, adapter_kind" in pool.sql
    assert "response_bytes, truncated" in pool.sql
    assert pool.args[11:20] == (
        request_id,
        company_id,
        "ODATA_V3",
        "0.6.0",
        "abc123",
        "policy-7",
        "sha256:metadata",
        512,
        True,
    )


@pytest.mark.asyncio
async def test_audit_generates_request_id_when_caller_does_not_supply_one():
    pool = FakePool()
    audit = Audit(FakeDatabase(pool), include_query=False)

    await audit.write(
        principal=Principal("subject", "client", frozenset(), frozenset(), {}),
        tool="sources_list",
        source_id=None,
        outcome="success",
        started_at=0,
    )

    assert isinstance(pool.args[11], uuid.UUID)
