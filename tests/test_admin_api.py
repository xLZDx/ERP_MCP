from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode
from uuid import UUID

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse

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

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return {"source_id": "source-b"}


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
async def test_intake_preview_rechecks_live_source_role_after_parse():
    """A stale request-start binding cannot survive revocation during parsing."""
    from business_ai_gateway.admin_api import AdminAPI

    class RevokingPool:
        def __init__(self):
            self.calls = []

        async def fetchrow(self, sql, *args):
            self.calls.append((sql, args))
            return {
                "active": True,
                "has_admin_role": len(self.calls) == 1,
                "has_allow": True,
                "has_deny": False,
            }

    class DB:
        def __init__(self):
            self.pool = RevokingPool()

        def require_pool(self):
            return self.pool

    company_id = UUID("8de7f202-ae8d-49d4-8655-3de42662c026")
    ctx = AdminContext(
        token=SimpleNamespace(subject="subject-1", client_id="client-1"),
        groups=frozenset(),
        # This request-start snapshot remains stale after the fake pool revokes the role.
        bindings=(AdminRoleBinding("SOURCE_ADMIN", "source-a"),),
    )
    db = DB()
    api = object.__new__(AdminAPI)
    api.authenticate = AsyncMock(return_value=ctx)
    api.repository = SimpleNamespace(db=db)

    payload = b"invoice_number,amount\nINV-REVOKED-1,12.50\n"
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/admin/v1/intake/preview",
            "query_string": urlencode({
                "source_id": "source-a", "company_id": str(company_id), "format": "csv",
            }).encode(),
            "headers": [(b"content-type", b"application/octet-stream")],
        },
        receive,
    )

    response = await api.intake_preview(request)

    assert response.status_code == 403
    assert json.loads(response.body) == {"error": "INTAKE_SCOPE_DENIED"}
    assert b"INV-REVOKED-1" not in response.body
    assert len(db.pool.calls) == 2  # pre-parse authorization and post-parse recheck
    for sql, args in db.pool.calls:
        assert "FROM bag.platform_role_bindings b" in sql
        assert "FROM bag.access_grants a" in sql
        assert args[0] == company_id
        assert args[1] == "source-a"
        assert args[2] == "subject-1"
        assert args[4] == ["PLATFORM_ADMIN", "SOURCE_ADMIN", "ACCESS_ADMIN", "AUDITOR"]


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


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["grant", "assignment", "override", "profile"])
async def test_target_authorization_looks_up_exact_object_by_primary_key(kind):
    db = FakeDB()
    repo = AdminRepository(db)
    target_id = "target-outside-any-list-page"
    ctx = AdminContext(
        token=SimpleNamespace(subject="subject-1", client_id="client-1"),
        groups=frozenset(),
        bindings=(AdminRoleBinding("ACCESS_ADMIN" if kind != "profile" else "PROFILE_ADMIN", "source-a"),),
    )
    assert await repo.visible_target(ctx, kind, target_id) is False
    sql, args = db.pool.calls[-1]
    assert "WHERE" in sql and "$1" in sql
    assert "LIMIT" not in sql.upper()
    assert args == (target_id,)


@pytest.mark.asyncio
async def test_authenticate_returns_403_when_valid_token_has_no_role_binding():
    from business_ai_gateway.admin_api import AdminAPI

    api = object.__new__(AdminAPI)
    api.sessions = None
    api.verifier = SimpleNamespace(verify_token=AsyncMock(return_value=SimpleNamespace(
        subject="unbound", client_id="client", claims={"groups": []}
    )))
    api.runtime = SimpleNamespace(
        start=AsyncMock(),
        rate_limit=SimpleNamespace(check=AsyncMock()),
    )
    api.repository = SimpleNamespace(resolve_bindings=AsyncMock(return_value=()))
    request = Request({
        "type": "http", "method": "GET", "path": "/admin/v1/me", "query_string": b"",
        "headers": [(b"authorization", b"Bearer valid")],
    })
    result = await api.authenticate(request)
    assert isinstance(result, JSONResponse)
    assert result.status_code == 403


@pytest.mark.asyncio
async def test_authenticate_returns_401_when_token_verifier_returns_none():
    from business_ai_gateway.admin_api import AdminAPI

    api = object.__new__(AdminAPI)
    api.sessions = None
    api.mutations = None
    api.verifier = SimpleNamespace(verify_token=AsyncMock(return_value=None))
    request = Request({
        "type": "http", "method": "GET", "path": "/admin/v1/me", "query_string": b"",
        "headers": [(b"authorization", b"Bearer invalid")],
    })
    result = await api.authenticate(request)
    assert isinstance(result, JSONResponse)
    assert result.status_code == 401


def test_global_auditor_is_global_read_context():
    token = SimpleNamespace(subject="auditor", client_id="client")
    ctx = AdminContext(
        token=token,
        groups=frozenset(),
        bindings=(AdminRoleBinding("AUDITOR", None),),
    )

    assert ctx.source_scope() is None


def test_capability_refusal_is_a_conflict_not_a_server_fault():
    import json

    from business_ai_gateway.admin_api import AdminAPI
    from business_ai_gateway.compatibility import CapabilityUnsupported

    refusal = AdminAPI._mutation_error(CapabilityUnsupported("unconfirmed register capability"))
    assert refusal.status_code == 409
    assert json.loads(refusal.body) == {"error": "CAPABILITY_UNSUPPORTED"}
    # Unmapped exceptions must still fail as server faults with a sanitized code.
    fault = AdminAPI._mutation_error(RuntimeError("boom"))
    assert fault.status_code == 500
    assert json.loads(fault.body) == {"error": "ADMIN_DEPENDENCY_FAILED"}


def test_non_string_exception_code_is_sanitized_to_dependency_failed():
    import json

    from business_ai_gateway.admin_api import AdminAPI

    class Odd(Exception):
        code = 5

    response = AdminAPI._mutation_error(Odd("odd"))
    assert response.status_code == 500
    assert json.loads(response.body) == {"error": "ADMIN_DEPENDENCY_FAILED"}
