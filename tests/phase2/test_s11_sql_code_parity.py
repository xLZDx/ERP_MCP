"""Focused S1.1 parity and exhausted-grant behavior on disposable PostgreSQL."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

from _pg_harness import disposable_cluster, throwaway_db
from test_change_ledger_sql import C, DEFAULT_GRANT, L, T, _setup
from business_ai_gateway.phase2.change.errors import ErrorCode

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]
ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "phase2"
PREDECESSORS = tuple(f"{n:03d}" for n in range(19, 28))


async def _apply(conn: asyncpg.Connection, name: str) -> None:
    raw = (MIGRATIONS / name).read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def ledger():
    old = os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS")
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    try:
        async with disposable_cluster() as (dsn, _name, _token):
            async with throwaway_db(dsn, seed=False) as db:
                for version in PREDECESSORS:
                    await _apply(db.conn, next(p.name for p in MIGRATIONS.glob(version + "_*.sql")))
                await _setup(db.conn)
                await db.conn.execute(
                    "INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason) "
                    "VALUES($1,$2,'LEGACY',0,'TEST_FIXTURE') ON CONFLICT DO NOTHING", T, C)
                await _apply(db.conn, "028_refusal_codes_parity.sql")
                yield L(db)
    finally:
        if old is None:
            os.environ.pop("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", None)
        else:
            os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = old


async def _fails(code: str, awaitable):
    try:
        await awaitable
    except asyncpg.PostgresError as exc:
        assert exc.sqlstate == "P0001", (exc.sqlstate, str(exc))
        assert str(exc).splitlines()[0] == code, str(exc)
        return
    raise AssertionError(f"expected SQL refusal {code}")


async def test_s11_migration_matches_python_registry_reapplies_and_restricts_table_access(ledger: L):
    python_codes = {code.value for code in ErrorCode}
    sql_codes = set(await ledger.conn.fetchval(
        "SELECT array_agg(code ORDER BY code) FROM change_ledger.refusal_code_registry"))
    assert len(python_codes) == 39
    assert sql_codes == python_codes
    assert {"PERIOD_CLOSED", "GRANT_EXHAUSTED"} <= sql_codes

    await _apply(ledger.conn, "028_refusal_codes_parity.sql")
    rows = await ledger.conn.fetch("SELECT code FROM change_ledger.refusal_code_registry ORDER BY code")
    assert {row["code"] for row in rows} == python_codes
    owner = await ledger.conn.fetchval(
        "SELECT tableowner FROM pg_tables WHERE schemaname='change_ledger' "
        "AND tablename='refusal_code_registry'")
    assert owner == "ledger_owner"
    assert not await ledger.conn.fetchval(
        "SELECT has_table_privilege('clt_alice','change_ledger.refusal_code_registry','SELECT')")
    assert not await ledger.conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a "
        "WHERE n.nspname='change_ledger' AND c.relname='refusal_code_registry' "
        "AND a.grantee=0 AND a.privilege_type='SELECT')")


async def test_s11_budget_path_distinguishes_exhaustion_other_refusals_and_zero_amount(ledger: L):
    gid = DEFAULT_GRANT[(T, C)]
    await ledger.conn.execute(
        "UPDATE change_ledger.grants SET amount_limit=100,count_limit=100,post_count_limit=100 "
        "WHERE grant_id=$1", gid)

    partial = await ledger.approved(request_id="s11-budget-partial", amount=40)
    too_large = await ledger.approved(request_id="s11-budget-over", amount=61, base="base-2")
    remainder = await ledger.approved(request_id="s11-budget-remainder", amount=60, base="base-3")
    exhausted = await ledger.approved(request_id="s11-budget-exhausted", amount=1, base="base-4")
    zero = await ledger.approved(request_id="s11-budget-zero", amount=0, base="base-5")

    await ledger.claimed(partial)
    await _fails("BUDGET_EXCEEDED", ledger.claimed(too_large, observe=False))
    await ledger.claimed(remainder)
    await _fails("GRANT_EXHAUSTED", ledger.claimed(exhausted, observe=False))
    assert (await ledger.claimed(zero, observe=False))["generation"] == 1