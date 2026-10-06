from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import pytest

from business_ai_gateway.admin_access import explain_access
from business_ai_gateway.admin_mutations import (
    AdminActor,
    AdminConflict,
    AdminMutationService,
    AdminValidationError,
)
from business_ai_gateway.db import Database

URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="requires disposable PostgreSQL BAG_PRIVILEGE_TEST_DATABASE_URL")


@pytest.fixture
async def service():
    owner = await asyncpg.connect(URL)
    source = f"acc-{uuid4()}"
    company = uuid4()
    await owner.execute("INSERT INTO bag.sources(source_id,project,kind,display_name,base_url) VALUES($1,'onec','onec_auto','ACC test','https://approved.test/odata')", source)
    await owner.execute("INSERT INTO bag.companies(company_id,source_id,external_ref,display_name) VALUES($1,$2,'org','Company')", company, source)

    async def control(conn):
        await conn.execute("SET ROLE business_ai_control_api")

    pool = await asyncpg.create_pool(URL, min_size=1, max_size=4, init=control)
    svc = AdminMutationService(SimpleNamespace(require_pool=lambda: pool), production=False)
    yield svc, owner, source, company
    await pool.close()
    await owner.close()


def grant_args(source, company, key=None):
    return {"actor": AdminActor(str(uuid4()), "client"), "principal_kind": "subject", "principal_id": "subject-id",
            "source_id": source, "company_id": company, "effect": "allow", "expires_at": "2099-01-01T00:00:00Z",
            "reason": "integration test", "request_id": uuid4(), "idempotency_key": key or str(uuid4())}


@pytest.mark.asyncio
async def test_control_role_grant_replay_conflict_exact_revoke_and_audit(service):
    svc, owner, source, company = service
    args = grant_args(source, company)
    first = await svc.create_grant(**args)
    assert await svc.create_grant(**args) == first
    with pytest.raises(AdminConflict):
        await svc.create_grant(**{**args, "effect": "deny"})
    with pytest.raises(AdminConflict):
        await svc.revoke_grant(actor=args["actor"], grant_id=UUID(first["id"]), expected_version=99,
                               reason="stale revoke", request_id=uuid4(), idempotency_key=str(uuid4()))
    revoked = await svc.revoke_grant(actor=args["actor"], grant_id=UUID(first["id"]), expected_version=1,
                                   reason="exact revoke", request_id=uuid4(), idempotency_key=str(uuid4()))
    assert revoked["row_version"] == 2
    audit_rows = await owner.fetch(
        """
        SELECT action, outcome, company_id
        FROM bag.admin_audit_events
        WHERE actor_subject=$1
        """,
        args["actor"].subject,
    )
    assert {row["outcome"] for row in audit_rows} == {"success", "conflict"}
    revoke_success = next(
        row
        for row in audit_rows
        if row["action"] == "grant.revoke" and row["outcome"] == "success"
    )
    assert revoke_success["company_id"] == company


@pytest.mark.asyncio
async def test_concurrent_idempotency_has_one_logical_grant(service):
    svc, owner, source, company = service
    args = grant_args(source, company)
    results = await asyncio.gather(*(svc.create_grant(**args) for _ in range(4)), return_exceptions=True)
    assert all(isinstance(result, (dict, AdminConflict)) for result in results)
    successes = [result for result in results if isinstance(result, dict)]
    assert successes
    assert len({result["id"] for result in successes}) == 1
    assert await svc.create_grant(**args) == successes[0]
    assert await owner.fetchval("SELECT count(*) FROM bag.access_grants WHERE created_by_subject=$1", args["actor"].subject) == 1


@pytest.mark.asyncio
async def test_foreign_company_and_invalid_expiry_fail_without_policy_write(service):
    svc, owner, source, company = service
    args = grant_args(source, uuid4())
    with pytest.raises(AdminValidationError):
        await svc.create_grant(**args)
    with pytest.raises(AdminValidationError):
        await svc.create_grant(**{**grant_args(source, company), "expires_at": "tomorrow"})
    assert await owner.fetchval("SELECT count(*) FROM bag.access_grants WHERE created_by_subject=$1", args["actor"].subject) == 0


@pytest.mark.asyncio
async def test_effective_access_is_paginated_at_151_companies_and_explains_group_denies(service):
    _svc, owner, source, company = service
    await owner.executemany("INSERT INTO bag.companies(company_id,source_id,external_ref,display_name) VALUES($1,$2,$3,$3)",
                           [(uuid4(), source, f"company-{index}") for index in range(150)])
    await owner.execute("INSERT INTO bag.access_grants(grant_id,principal_kind,principal_id,source_id,effect) VALUES($1,'group','finance',$2,'allow')", uuid4(), source)
    await owner.execute("INSERT INTO bag.access_grants(grant_id,principal_kind,principal_id,source_id,company_id,effect) VALUES($1,'subject','employee',$2,$3,'deny')", uuid4(), source, company)
    ctx = SimpleNamespace(token=SimpleNamespace(subject="employee"), groups=frozenset({"finance"}))
    args = {"ctx": ctx, "kind": "subject", "principal_id": "employee", "source_id": source,
            "entity_set": "Document_Sale", "limit": 50, "offset": 0}
    pages, offset = [], 0
    while offset is not None:
        result = await explain_access(owner, **{**args, "offset": offset})
        assert len(result["items"]) <= 50
        pages.extend(result["items"])
        offset = result["next_offset"]
    assert len(pages) == 151
    denied = next(item for item in pages if item["company_id"] == str(company))
    assert denied["detail_code"] == "EXPLICIT_DENY"
    assert {g["inheritance"] for g in denied["matching_grants"]} == {"direct", "inherited"}
    assert all(item["company_operation"] == "unsupported_or_stale_mapping" for item in pages)
    unknown = await explain_access(owner, **{**args, "principal_id": "another-employee"})
    assert all(item["data_acl"] == "unknown" for item in unknown["items"])
    filtered = await explain_access(owner, **args, effect="deny", inheritance="direct")
    assert len(filtered["items"]) == 1


@pytest.mark.asyncio
async def test_production_control_db_check_rejects_owner_and_privileged_membership(service):
    _svc, owner, _source, _company = service
    db = Database(URL)
    db.pool = owner
    with pytest.raises(RuntimeError, match="least-privilege"):
        await db.assert_control_api_role()
    login = "acc_control_" + uuid4().hex
    await owner.execute(f"CREATE ROLE {login} LOGIN PASSWORD 'acc-disposable-test' INHERIT")
    await owner.execute(f"GRANT business_ai_control_api TO {login}")
    conn = await asyncpg.connect(URL, user=login, password="acc-disposable-test")
    try:
        db.pool = conn
        await db.assert_control_api_role()
        await owner.execute(f"GRANT business_ai_admin TO {login}")
        with pytest.raises(RuntimeError, match="least-privilege"):
            await db.assert_control_api_role()
    finally:
        await conn.close()
