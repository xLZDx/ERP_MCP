from __future__ import annotations

from types import SimpleNamespace

import pytest

from business_ai_gateway.admin_api import AdminContext, AdminRepository, AdminRoleBinding


class FakePool:
    def __init__(self):
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        if "platform_role_bindings" in sql:
            return [
                {"role_name": "SOURCE_ADMIN", "source_id": "source-a"},
                {"role_name": "AUDITOR", "source_id": "source-b"},
            ]
        if "FROM bag.sources" in sql:
            return [
                {
                    "source_id": "source-a",
                    "project": "onec",
                    "kind": "onec_auto",
                    "display_name": "A",
                    "read_only": True,
                    "enabled": True,
                    "platform_version_hint": None,
                    "created_at": None,
                    "updated_at": None,
                }
            ]
        if "FROM bag.companies" in sql:
            return []
        raise AssertionError(sql)


class FakeDB:
    def __init__(self):
        self.pool = FakePool()

    def require_pool(self):
        return self.pool


@pytest.mark.asyncio
async def test_role_resolution_accepts_subject_and_group_bindings():
    repo = AdminRepository(FakeDB())

    bindings = await repo.resolve_bindings("subject-1", frozenset({"ops"}))

    assert bindings == (
        AdminRoleBinding("SOURCE_ADMIN", "source-a"),
        AdminRoleBinding("AUDITOR", "source-b"),
    )


@pytest.mark.asyncio
async def test_source_scoped_admin_reads_only_delegated_sources():
    db = FakeDB()
    repo = AdminRepository(db)
    token = SimpleNamespace(subject="subject-1", client_id="client-1")
    ctx = AdminContext(
        token=token,
        groups=frozenset(),
        bindings=(AdminRoleBinding("SOURCE_ADMIN", "source-a"),),
    )

    rows = await repo.list_sources(ctx)

    assert [row["source_id"] for row in rows] == ["source-a"]
    sql, args = db.pool.calls[-1]
    assert "source_id=ANY" in sql
    assert args == (["source-a"], 500)


def test_global_auditor_is_global_read_context():
    token = SimpleNamespace(subject="auditor", client_id="client")
    ctx = AdminContext(
        token=token,
        groups=frozenset(),
        bindings=(AdminRoleBinding("AUDITOR", None),),
    )

    assert ctx.source_scope() is None
