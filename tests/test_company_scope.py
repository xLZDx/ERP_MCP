from __future__ import annotations

import uuid

import pytest

from business_ai_gateway.models import Company
from business_ai_gateway.principal import Principal
from business_ai_gateway.registry import AccessDenied, Registry
from scripts.admin import company_upsert, grant_add


def principal() -> Principal:
    return Principal(
        subject="subject-1",
        client_id="client-1",
        scopes=frozenset({"onec:read"}),
        groups=frozenset({"accounting"}),
        claims={},
    )


def company_row(company_id: uuid.UUID, source_id: str = "source-1") -> dict:
    return {
        "company_id": company_id,
        "source_id": source_id,
        "external_ref": "org-1",
        "display_name": "Organization 1",
        "legal_name": None,
        "country_code": "MD",
        "enabled": True,
        "is_default": False,
    }


class FakePool:
    def __init__(self, *, rows=None, row=None):
        self.rows = rows or []
        self.row = row
        self.sql = ""
        self.args = ()

    async def fetch(self, sql, *args):
        self.sql, self.args = sql, args
        return self.rows

    async def fetchrow(self, sql, *args):
        self.sql, self.args = sql, args
        return self.row


class FakeDatabase:
    def __init__(self, pool):
        self.pool = pool

    def require_pool(self):
        return self.pool


class FakeAdminConnection:
    def __init__(self, *, company_id=None):
        self.company_id = company_id
        self.sql = None
        self.args = ()

    async def execute(self, sql, *args):
        self.sql, self.args = sql, args
        return "INSERT 0 1"

    async def fetchval(self, sql, *args):
        self.sql, self.args = sql, args
        return self.company_id


@pytest.mark.asyncio
async def test_company_list_is_filtered_by_active_source_or_company_grants():
    company_id = uuid.uuid4()
    pool = FakePool(rows=[company_row(company_id)])
    registry = Registry(FakeDatabase(pool), production=True)

    result = await registry.list_allowed_companies(principal(), "source-1")

    assert result == [
        Company(
            id=company_id,
            source_id="source-1",
            external_ref="org-1",
            display_name="Organization 1",
            legal_name=None,
            country_code="MD",
            enabled=True,
            is_default=False,
        )
    ]
    assert "g.company_id IS NULL OR g.company_id = c.company_id" in pool.sql
    assert "g.revoked_at IS NULL" in pool.sql
    assert "g.expires_at > now()" in pool.sql
    assert "g.principal_id = ANY($3::text[])" in pool.sql
    assert "g.effect = 'allow'" in pool.sql
    assert "denied.effect = 'deny'" in pool.sql
    assert "denied.company_id IS NULL OR denied.company_id = c.company_id" in pool.sql
    assert pool.args == ("source-1", "subject-1", ["accounting"])


@pytest.mark.asyncio
async def test_company_access_denies_missing_or_ungranted_company():
    pool = FakePool(row=None)
    registry = Registry(FakeDatabase(pool), production=True)

    with pytest.raises(AccessDenied, match="no access to company"):
        await registry.require_company(principal(), "source-1", uuid.uuid4())

    assert "c.company_id = $2" in pool.sql
    assert "g.company_id IS NULL OR g.company_id = c.company_id" in pool.sql
    assert "denied.effect = 'deny'" in pool.sql


@pytest.mark.asyncio
async def test_company_only_grant_cannot_authorize_unscoped_source_reads():
    pool = FakePool(row=None)
    registry = Registry(FakeDatabase(pool), production=True)

    with pytest.raises(AccessDenied, match="no access to source"):
        await registry.require_source(principal(), "source-1")

    assert "g.company_id IS NULL" in pool.sql
    assert "g.effect = 'allow'" in pool.sql
    assert "denied.effect = 'deny'" in pool.sql


@pytest.mark.asyncio
async def test_company_access_resolves_only_the_requested_source_company_pair():
    company_id = uuid.uuid4()
    pool = FakePool(row=company_row(company_id))
    registry = Registry(FakeDatabase(pool), production=True)

    company = await registry.require_company(principal(), "source-1", company_id)

    assert company.id == company_id
    assert pool.args == ("source-1", company_id, "subject-1", ["accounting"])
    assert "c.source_id = $1" in pool.sql


@pytest.mark.asyncio
async def test_company_admin_upsert_uses_explicit_stable_scope_and_returns_database_id(capsys):
    company_id = uuid.uuid4()
    conn = FakeAdminConnection(company_id=company_id)
    args = type(
        "Args",
        (),
        {
            "company_id": str(company_id),
            "source_id": "source-1",
            "external_ref": "org-1",
            "display_name": "Organization 1",
            "legal_name": None,
            "country_code": "MD",
            "default": False,
        },
    )()

    await company_upsert(args, conn)

    assert "ON CONFLICT(source_id, external_ref)" in conn.sql
    assert "RETURNING company_id" in conn.sql
    assert conn.args[:4] == (company_id, "source-1", "org-1", "Organization 1")
    assert capsys.readouterr().out.strip() == str(company_id)


@pytest.mark.asyncio
async def test_admin_can_issue_company_scoped_deny_grant():
    company_id = uuid.uuid4()
    conn = FakeAdminConnection()
    args = type(
        "Args",
        (),
        {
            "kind": "group",
            "principal": "accounting",
            "source_id": "source-1",
            "company_id": str(company_id),
            "effect": "deny",
        },
    )()

    await grant_add(args, conn)

    assert "company_id, effect" in conn.sql
    assert conn.args[4:] == (company_id, "deny")
