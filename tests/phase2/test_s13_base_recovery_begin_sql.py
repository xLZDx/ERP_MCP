"""Bounded SQL contract for S13 base recovery begin (migration 036)."""
from __future__ import annotations

import hashlib
import json

import asyncpg
import pytest

from test_change_ledger_sql import C, L, T
from test_s13_inflight_status import ledger

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

RUNTIME_ROLES = (
    "requester_role",
    "approver_role",
    "operator_role",
    "writer_role",
    "worker_role",
    "auditor_role",
    "checkpoint_role",
    "business_ai_private_writer",
    "private_writer_evidence_ingest",
)
BEGIN_SIGNATURE = "change_ledger.begin_base_recovery(text)"


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


async def _owner_begin(ledger: L, base: str):
    """Call only from a fresh owner transaction, with the migration's required timeout bound."""
    async with ledger.conn.transaction():
        await ledger.conn.execute("SET LOCAL ROLE ledger_owner")
        await ledger.conn.execute("SELECT set_config('statement_timeout','10s',true)")
        value = await ledger.conn.fetchval(
            "SELECT change_ledger.begin_base_recovery($1)", base
        )
    return _json(value)


async def _fence_snapshot(ledger: L):
    bases = await ledger.conn.fetch(
        "SELECT base_fingerprint,state,epoch,scope_manifest::text,manifest_digest "
        "FROM change_ledger.base_recovery_fences ORDER BY base_fingerprint"
    )
    scopes = await ledger.conn.fetch(
        "SELECT tenant_id,company_id,state,epoch,reason "
        "FROM change_ledger.lifecycle_fences ORDER BY tenant_id,company_id"
    )
    return [tuple(row) for row in bases], [tuple(row) for row in scopes]


async def test_begin_base_recovery_is_unavailable_to_runtime_roles(ledger: L):
    """Only the internal recovery owner may call the fence-establishing entry point."""
    assert await ledger.conn.fetchval(
        "SELECT pg_get_userbyid(p.proowner) FROM pg_catalog.pg_proc p WHERE p.oid=$1::text::regprocedure",
        BEGIN_SIGNATURE,
    ) == "ledger_owner"
    for role in RUNTIME_ROLES:
        assert not await ledger.conn.fetchval(
            "SELECT has_function_privilege($1,$2,'EXECUTE')", role, BEGIN_SIGNATURE
        ), f"runtime role {role} can begin base recovery"


async def test_owner_begin_returns_exact_manifest_and_retry_advances_epoch(ledger: L):
    """A synthetic registered target yields its exact scope and a fresh epoch on each begin."""
    expected_manifest = [{"tenant_id": T, "company_id": C}]
    first = await _owner_begin(ledger, "base-1")

    assert first == {
        "base_fingerprint": "base-1",
        "state": "RECOVERING",
        "epoch": 1,
        "manifest_digest": hashlib.sha256(
            b'[{"tenant_id": "T1", "company_id": "C1"}]'
        ).hexdigest(),
        "scope_count": 1,
        "scope_manifest": expected_manifest,
    }
    assert tuple(await ledger.conn.fetchrow(
        "SELECT state,epoch,reason FROM change_ledger.lifecycle_fences "
        "WHERE tenant_id=$1 AND company_id=$2", T, C
    )) == ("RECOVERING", 1, "BASE_RECOVERY_IN_PROGRESS")

    second = await _owner_begin(ledger, "base-1")
    assert second == {**first, "epoch": 2}
    assert await ledger.conn.fetchval(
        "SELECT epoch FROM change_ledger.base_recovery_fences WHERE base_fingerprint='base-1'"
    ) == 2
    assert await ledger.conn.fetchval(
        "SELECT epoch FROM change_ledger.lifecycle_fences WHERE tenant_id=$1 AND company_id=$2", T, C
    ) == 2


async def test_overlapping_base_begin_refuses_without_changing_fence_rows(ledger: L):
    """A different synthetic clone sharing a lifecycle scope cannot acquire a second recovery fence."""
    await _owner_begin(ledger, "base-1")
    before = await _fence_snapshot(ledger)

    try:
        await _owner_begin(ledger, "base-2")
    except asyncpg.PostgresError as exc:
        assert str(exc).splitlines()[0] == "BASE_RECOVERY_SCOPE_BUSY", str(exc)
    else:
        raise AssertionError("overlapping base recovery unexpectedly acquired a second fence")

    assert await _fence_snapshot(ledger) == before


async def test_begin_rejects_65_scope_manifest_before_fence_changes(ledger: L):
    """The 64-scope bound is enforced before any recovery or lifecycle row is written."""
    base = "base-scope-limit"
    for index in range(65):
        await ledger.conn.execute(
            "INSERT INTO change_ledger.targets "
            "(tenant_id,company_id,base_fingerprint,organization_ref,target_class) "
            "VALUES($1,$2,$3,'synthetic-org','DISPOSABLE_CLONE')",
            f"limit-tenant-{index:02d}",
            f"limit-company-{index:02d}",
            base,
        )
    before = await _fence_snapshot(ledger)

    try:
        await _owner_begin(ledger, base)
    except asyncpg.PostgresError as exc:
        assert str(exc).splitlines()[0] == "BASE_SCOPE_LIMIT", str(exc)
    else:
        raise AssertionError("a 65-scope recovery manifest was accepted")

    assert await _fence_snapshot(ledger) == before
