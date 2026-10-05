from __future__ import annotations

import os
import uuid

import asyncpg
import pytest

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
    event_id = uuid.uuid4()
    try:
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'Role integration source',
                   'https://onec.example.test/odata')
            """,
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
        await conn.execute(
            """
            INSERT INTO bag.audit_events(
              event_id, principal_subject, client_id, tool_name, outcome, duration_ms
            ) VALUES($1, 'role-test', 'role-test', 'system_status', 'success', 0)
            """,
            event_id,
        )

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE bag.audit_events SET detail_code='tampered' WHERE event_id=$1",
                    event_id,
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM bag.audit_events WHERE event_id=$1", event_id
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
