"""CapabilityUnsupported -> savepoint rollback -> 'error' audit/idempotency -> HTTP 409 chain.

Database-backed (disposable PostgreSQL, same env as tests/test_admin_mutations_postgres.py).
With ERP_MCP_REQUIRE_DB_TESTS=1 a missing database is a FAILURE, never a skip.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import pytest

from business_ai_gateway.admin_api import AdminAPI
from business_ai_gateway.admin_mutations import AdminActor, AdminConflict, AdminMutationService
from business_ai_gateway.compatibility import CapabilityUnsupported

URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
REQUIRE_DB = os.getenv("ERP_MCP_REQUIRE_DB_TESTS") == "1"


@pytest.fixture
async def chain():
    if not URL:
        if REQUIRE_DB:
            pytest.fail("ERP_MCP_REQUIRE_DB_TESTS=1 but BAG_PRIVILEGE_TEST_DATABASE_URL is not set")
        pytest.skip("requires disposable PostgreSQL BAG_PRIVILEGE_TEST_DATABASE_URL")
    owner = await asyncpg.connect(URL)
    source = f"cap-{uuid4()}"
    await owner.execute(
        "INSERT INTO bag.sources(source_id,project,kind,display_name,base_url) "
        "VALUES($1,'onec','onec_auto','Original name','https://approved.test/odata')", source)

    async def control(conn):
        await conn.execute("SET ROLE business_ai_control_api")

    pool = await asyncpg.create_pool(URL, min_size=1, max_size=2, setup=control)
    svc = AdminMutationService(SimpleNamespace(require_pool=lambda: pool), production=False)
    yield svc, owner, source
    await pool.close()
    await owner.close()


@pytest.mark.asyncio
async def test_capability_unsupported_rolls_back_audits_error_retries_and_maps_to_409(chain):
    svc, owner, source = chain
    actor, key = AdminActor(str(uuid4()), "client"), str(uuid4())
    executed = []

    async def mutation(conn):
        executed.append(1)
        await conn.execute("UPDATE bag.sources SET display_name='MUTATED' WHERE source_id=$1", source)
        raise CapabilityUnsupported("CAPABILITY_UNSUPPORTED")

    async def call(*, source_id=source, request_id=None):
        return await svc._execute(
            actor=actor, command="capability.refresh", target_type="source_capability",
            target_id=source_id, source_id=source, company_id=None, reason="refusal chain",
            request_id=request_id or uuid4(), idempotency_key=key,
            request={"source_id": source_id}, mutation=mutation)

    with pytest.raises(CapabilityUnsupported) as raised:
        await call()
    assert executed == [1]

    audit = await owner.fetch(
        "SELECT outcome, detail_code FROM bag.admin_audit_events WHERE actor_subject=$1", actor.subject)
    assert [(r["outcome"], r["detail_code"]) for r in audit] == [("error", "CAPABILITY_UNSUPPORTED")]
    idem = await owner.fetchrow(
        "SELECT outcome, detail_code, result_json FROM bag.admin_idempotency "
        "WHERE actor_subject=$1 AND idempotency_key=$2", actor.subject, key)
    assert idem["outcome"] == "error" and idem["result_json"] is None
    assert idem["detail_code"] == "CAPABILITY_UNSUPPORTED"
    # Savepoint rollback: the domain write made inside the mutation did not survive.
    assert await owner.fetchval(
        "SELECT display_name FROM bag.sources WHERE source_id=$1", source) == "Original name"

    # Real route mapper: domain refusal -> 409 with the stable code, not a 500.
    response = AdminAPI._mutation_error(raised.value)
    assert response.status_code == 409
    assert response.body == b'{"error":"CAPABILITY_UNSUPPORTED"}'

    # Same key + same payload re-executes the mutation (failed attempt does not poison the key).
    with pytest.raises(CapabilityUnsupported):
        await call()
    assert executed == [1, 1]
    assert await owner.fetchval(
        "SELECT count(*) FROM bag.admin_audit_events WHERE actor_subject=$1 AND outcome='error'",
        actor.subject) == 2
    assert await owner.fetchval(
        "SELECT display_name FROM bag.sources WHERE source_id=$1", source) == "Original name"

    # Same key + different payload is a conflict and never runs the mutation.
    with pytest.raises(AdminConflict):
        await call(source_id=source + "-other")
    assert executed == [1, 1]
