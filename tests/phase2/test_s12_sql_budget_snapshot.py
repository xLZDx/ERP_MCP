"""Focused S1.2 budget snapshot integration coverage on disposable PostgreSQL."""
from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from _pg_harness import disposable_cluster, throwaway_db
from test_change_ledger_sql import C, DEFAULT_GRANT, L, T, T2, C2, _setup
from business_ai_gateway.phase2.change.types import BudgetCheck
from business_ai_gateway.phase2.change_ledger._common import LedgerError, Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]
ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "phase2"
PREDECESSORS = tuple(f"{n:03d}" for n in range(19, 29))
FUNCTION_SIGNATURE = "change_ledger.budget_snapshot(text,text,uuid,numeric,text)"


async def _apply(conn: asyncpg.Connection, name: str) -> None:
    raw = (MIGRATIONS / name).read_bytes()
    await conn.execute(
        "SELECT set_config('living.migration_checksum',$1,false)",
        hashlib.sha256(raw).hexdigest(),
    )
    await conn.execute(raw.decode("utf-8"))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def cluster_dsn():
    async with disposable_cluster() as (dsn, _name, _token):
        yield dsn


@pytest_asyncio.fixture(loop_scope="module")
async def ledger(cluster_dsn):
    async with throwaway_db(cluster_dsn, seed=False) as db:
        for version in PREDECESSORS:
            migration = next(MIGRATIONS.glob(version + "_*.sql"))
            await _apply(db.conn, migration.name)
        await _setup(db.conn)
        await db.conn.execute(
            "INSERT INTO change_ledger.lifecycle_fences"
            "(tenant_id,company_id,state,epoch,reason) "
            "VALUES($1,$2,'LEGACY',0,'TEST_FIXTURE') ON CONFLICT DO NOTHING",
            T,
            C,
        )
        await _apply(db.conn, "029_s12_budget_snapshot.sql")
        adapter = SqlChangeLedger(
            db.conn,
            {"operator": "clt_dave", "auditor": "clt_aud"},
            private_writer_schema_enabled=True,
        )
        yield db, L(db), adapter


def assert_ledger_error(exc_info, code: str) -> None:
    assert isinstance(exc_info.value, LedgerError)
    assert exc_info.value.code == code


async def test_snapshot_maps_available_overage_and_exhausted_grant_to_budgetcheck(ledger):
    db, flows, adapter = ledger
    grant_id = DEFAULT_GRANT[(T, C)]
    scope = Scope(T, C)
    await db.conn.execute(
        "UPDATE change_ledger.grants "
        "SET amount_limit=100,count_limit=100,post_count_limit=100 WHERE grant_id=$1",
        grant_id,
    )

    assert await adapter.budget_snapshot(scope, grant_id, Decimal("1"), "EUR") is BudgetCheck.OK

    partial = await flows.approved(request_id="s12-snapshot-partial", amount=40)
    await flows.claimed(partial)
    # The grant has a positive remainder (60), but this request exceeds it.
    assert await adapter.budget_snapshot(scope, grant_id, Decimal("61"), "EUR") is BudgetCheck.EXCEEDED

    remainder = await flows.approved(request_id="s12-snapshot-remainder", amount=60, base="base-2")
    await flows.claimed(remainder)
    assert await adapter.budget_snapshot(scope, grant_id, Decimal("1"), "EUR") is BudgetCheck.EXHAUSTED


async def test_snapshot_preserves_refusals_and_enforces_scope_and_role_permissions(ledger):
    db, flows, adapter = ledger
    grant_id = DEFAULT_GRANT[(T, C)]
    scope = Scope(T, C)

    with pytest.raises(LedgerError) as unknown:
        await adapter.budget_snapshot(scope, uuid4(), Decimal("1"), "EUR")
    assert_ledger_error(unknown, "BUDGET_EXCEEDED")

    with pytest.raises(LedgerError) as currency:
        await adapter.budget_snapshot(scope, grant_id, Decimal("1"), "USD")
    assert_ledger_error(currency, "CURRENCY_NOT_BUDGETED")

    with pytest.raises(LedgerError) as invalid:
        await adapter.budget_snapshot(scope, grant_id, Decimal("-1"), "EUR")
    assert_ledger_error(invalid, "SCHEMA_INVALID")

    await db.conn.execute(
        "UPDATE change_ledger.grants SET status='REVOKED' WHERE grant_id=$1",
        grant_id,
    )
    with pytest.raises(LedgerError) as inactive:
        await adapter.budget_snapshot(scope, grant_id, Decimal("1"), "EUR")
    assert_ledger_error(inactive, "BUDGET_EXCEEDED")

    # The auditor class is explicitly allowed; the requester class is not.
    await db.conn.execute(
        "UPDATE change_ledger.grants SET status='ACTIVE' WHERE grant_id=$1",
        grant_id,
    )
    assert await adapter.budget_snapshot(
        scope, grant_id, Decimal("1"), "EUR", as_class="auditor"
    ) is BudgetCheck.OK
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await flows.call("clt_alice", "budget_snapshot", grant_id, Decimal("1"), "EUR")

    with pytest.raises(LedgerError) as wrong_scope:
        await adapter.budget_snapshot(
            Scope(T2, C2), DEFAULT_GRANT[(T2, C2)], Decimal("1"), "EUR"
        )
    assert_ledger_error(wrong_scope, "SCOPE_NOT_GRANTED")


async def test_migration_reapplies_safely_and_keeps_execute_grants_scoped(ledger):
    db, _flows, adapter = ledger
    await _apply(db.conn, "029_s12_budget_snapshot.sql")

    assert await db.conn.fetchval(
        "SELECT has_function_privilege('clt_dave',$1,'EXECUTE')", FUNCTION_SIGNATURE
    )
    assert await db.conn.fetchval(
        "SELECT has_function_privilege('clt_aud',$1,'EXECUTE')", FUNCTION_SIGNATURE
    )
    assert not await db.conn.fetchval(
        "SELECT has_function_privilege('clt_alice',$1,'EXECUTE')", FUNCTION_SIGNATURE
    )
    assert await adapter.budget_snapshot(
        Scope(T, C), DEFAULT_GRANT[(T, C)], Decimal("1"), "EUR"
    ) is BudgetCheck.OK