from __future__ import annotations

import os
import time
import uuid

import asyncpg
import pytest

from business_ai_gateway.audit import Audit, query_fingerprint
from business_ai_gateway.principal import Principal
from business_ai_gateway.registry import AccessDenied, Registry

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="requires the disposable PostgreSQL database configured by CI",
)


class ConnectionDatabase:
    def __init__(self, connection):
        self.connection = connection

    def require_pool(self):
        return self.connection


@pytest.mark.asyncio
async def test_postgres_company_grants_deny_precedence_and_live_revocation():
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    source_id = f"acl-test-{uuid.uuid4()}"
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    grant_a = uuid.uuid4()
    grant_b = uuid.uuid4()
    subject = f"subject-{uuid.uuid4()}"
    try:
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'ACL integration source',
                   'https://onec.example.test/odata')
            """,
            source_id,
        )
        await conn.executemany(
            """
            INSERT INTO bag.companies(company_id, source_id, external_ref, display_name)
            VALUES($1,$2,$3,$4)
            """,
            [
                (company_a, source_id, "a", "Company A"),
                (company_b, source_id, "b", "Company B"),
            ],
        )
        await conn.executemany(
            """
            INSERT INTO bag.access_grants(
              grant_id, principal_kind, principal_id, source_id, company_id, effect
            ) VALUES($1, 'subject', $2, $3, $4, $5)
            """,
            [
                (grant_a, subject, source_id, company_a, "allow"),
                (grant_b, subject, source_id, company_b, "allow"),
                (uuid.uuid4(), subject, source_id, company_b, "deny"),
            ],
        )
        principal = Principal(
            subject=subject,
            client_id="acl-integration-test",
            scopes=frozenset({"onec:read"}),
            groups=frozenset(),
            claims={},
        )
        registry = Registry(ConnectionDatabase(conn), production=True)

        assert [c.id for c in await registry.list_allowed_companies(principal, source_id)] == [
            company_a
        ]
        assert (await registry.require_company(principal, source_id, company_a)).id == company_a
        with pytest.raises(AccessDenied):
            await registry.require_company(principal, source_id, company_b)
        with pytest.raises(AccessDenied):
            await registry.require_source(principal, source_id)

        await conn.execute(
            "UPDATE bag.access_grants SET revoked_at=now() WHERE grant_id=$1", grant_a
        )
        with pytest.raises(AccessDenied):
            await registry.require_company(principal, source_id, company_a)
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_postgres_runtime_role_is_read_only_except_append_only_audit():
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    source_id = f"role-test-{uuid.uuid4()}"
    request_id = uuid.uuid4()
    company_id = uuid.uuid4()
    try:
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'Role integration source',
                   'https://onec.example.test/odata')
            """,
            source_id,
        )
        await conn.execute(
            """
            INSERT INTO bag.companies(company_id, source_id, external_ref, display_name)
            VALUES($1, $2, 'audit-test', 'Audit integration company')
            """,
            company_id,
            source_id,
        )
        await conn.execute("SET LOCAL ROLE business_ai_app")

        assert await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.sources', 'SELECT')"
        )
        assert await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.audit_events', 'INSERT')"
        )
        assert not await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.sources', 'UPDATE')"
        )
        assert not await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.audit_events', 'UPDATE')"
        )
        assert await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM bag.sources WHERE source_id=$1)", source_id
        )
        principal = Principal(
            subject="role-test",
            client_id="role-test-client",
            scopes=frozenset({"onec:read"}),
            groups=frozenset(),
            claims={},
        )
        await Audit(ConnectionDatabase(conn), include_query=True).write(
            principal=principal,
            tool="onec_read",
            source_id=source_id,
            outcome="error",
            started_at=time.monotonic(),
            query={"entity_set": "Invoices", "top": 10},
            request_id=request_id,
            company_id=company_id,
            adapter_kind="ODATA_JSON_V3",
            adapter_version="test-1",
            upstream_sha="a" * 40,
            policy_version="acl-test-v1",
            metadata_fingerprint="b" * 64,
            returned_items=0,
            response_bytes=0,
            truncated=False,
            detail_code="IntegrationTestError",
        )
        audit_row = await conn.fetchrow(
            "SELECT * FROM bag.audit_events WHERE request_id=$1", request_id
        )
        assert audit_row["company_id"] == company_id
        assert audit_row["source_id"] == source_id
        assert audit_row["request_id"] == request_id
        assert audit_row["query_fingerprint"] == query_fingerprint(
            {"entity_set": "Invoices", "top": 10}
        )
        assert audit_row["returned_items"] == 0
        assert audit_row["duration_ms"] >= 0
        assert audit_row["adapter_kind"] == "ODATA_JSON_V3"
        assert audit_row["adapter_version"] == "test-1"
        assert audit_row["upstream_sha"] == "a" * 40
        assert audit_row["policy_version"] == "acl-test-v1"
        assert audit_row["metadata_fingerprint"] == "b" * 64
        assert audit_row["response_bytes"] == 0
        assert audit_row["truncated"] is False
        assert audit_row["outcome"] == "error"
        assert audit_row["detail_code"] == "IntegrationTestError"

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE bag.audit_events SET detail_code='tampered' WHERE request_id=$1",
                    request_id,
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM bag.audit_events WHERE request_id=$1", request_id
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE bag.sources SET display_name='tampered' WHERE source_id=$1",
                    source_id,
                )
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_postgres_admin_role_can_manage_registry_but_not_audit_or_delete():
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    source_id = f"admin-role-test-{uuid.uuid4()}"
    company_id = uuid.uuid4()
    grant_id = uuid.uuid4()
    try:
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'Admin role integration source',
                   'https://onec.example.test/odata')
            """,
            source_id,
        )
        await conn.execute("SET LOCAL ROLE business_ai_admin")

        assert await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.sources', 'UPDATE')"
        )
        assert await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.access_grants', 'INSERT')"
        )
        assert await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.companies', 'INSERT')"
        )
        assert not await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.audit_events', 'INSERT')"
        )
        assert not await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.sources', 'DELETE')"
        )

        await conn.execute(
            "UPDATE bag.sources SET display_name='Admin-updated source' WHERE source_id=$1",
            source_id,
        )
        await conn.execute(
            """
            INSERT INTO bag.companies(company_id, source_id, external_ref, display_name)
            VALUES($1, $2, 'admin-company', 'Admin company')
            """,
            company_id,
            source_id,
        )
        await conn.execute(
            """
            INSERT INTO bag.access_grants(grant_id, principal_kind, principal_id, source_id)
            VALUES($1, 'subject', 'admin-test-subject', $2)
            """,
            grant_id,
            source_id,
        )
        await conn.execute(
            "UPDATE bag.access_grants SET revoked_at=now() WHERE grant_id=$1", grant_id
        )

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO bag.audit_events(
                      event_id, principal_subject, client_id, tool_name, outcome, duration_ms
                    ) VALUES($1, 'admin-test', 'admin-test', 'system_status', 'success', 0)
                    """,
                    uuid.uuid4(),
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute("DELETE FROM bag.sources WHERE source_id=$1", source_id)
    finally:
        await tx.rollback()
        await conn.close()
