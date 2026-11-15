"""S13 operator list/status SQL contract against disposable PostgreSQL."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio

from _pg_harness import disposable_cluster, throwaway_db
from test_change_ledger_sql import C, L, T, _setup

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]
MIGRATIONS = Path(__file__).resolve().parents[2] / "db" / "phase2"


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
                for version in range(19, 28):
                    await _apply(db.conn, next(p.name for p in MIGRATIONS.glob(f"{version:03d}_*.sql")))
                await _setup(db.conn)
                await db.conn.execute(
                    "INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason) "
                    "VALUES($1,$2,'LEGACY',0,'TEST_FIXTURE'),('T2','C2','LEGACY',0,'TEST_FIXTURE') "
                    "ON CONFLICT DO NOTHING", T, C)
                await _apply(db.conn, "028_refusal_codes_parity.sql")
                await _apply(db.conn, "029_scoped_operator_reads.sql")
                yield L(db)
    finally:
        if old is None:
            os.environ.pop("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", None)
        else:
            os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = old


def _decode_json(value):
    return json.loads(value) if isinstance(value, str) else value


async def test_operator_list_and_status_follow_live_ledger_transitions(ledger: L):
    change_id = await ledger.approved(request_id="s13-inflight-status")
    before = _decode_json(await ledger.call("clt_dave", "list_inflight", 50, 0))
    row = next(item for item in before if item["change_id"] == str(change_id))
    assert row["execution_state"] == "NOT_STARTED"

    token = await ledger.claimed(change_id)
    claimed = _decode_json(await ledger.call("clt_dave", "operator_status", change_id))
    assert claimed["change_id"] == str(change_id)
    assert claimed["execution"] == "NOT_STARTED"
    assert claimed["authorization"] == "CLAIMED"
    assert claimed["reservation"] == "RESERVED"
    current = _decode_json(await ledger.call("clt_dave", "list_inflight", 50, 0))
    assert any(item["change_id"] == str(change_id) and item["authorization_state"] == "CLAIMED"
               for item in current)

    missing_id = uuid4()
    try:
        await ledger.call("clt_dave", "operator_status", missing_id)
    except asyncpg.PostgresError as exc:
        assert str(exc).splitlines()[0] == "CHANGE_NOT_FOUND", str(exc)
    else:
        raise AssertionError("unknown change returned a fabricated status")

    # migration 027 intentionally revokes legacy begin_apply from runtime roles; this journey
    # stops at the permitted claim boundary and proves the operator view tracks that service state.
    assert token["generation"] == 1


async def test_operator_status_and_list_do_not_reveal_another_company_record(ledger: L):
    foreign = await ledger.propose(requester="clt_zed", request_id="s13-foreign-scope",
                                   t="T2", c="C2", base="base-t2")
    try:
        await ledger.call("clt_dave", "operator_status", foreign, t=T, c=C)
    except asyncpg.PostgresError as exc:
        assert str(exc).splitlines()[0] == "CHANGE_NOT_FOUND", str(exc)
    else:
        raise AssertionError("operator status disclosed a foreign-company record")

    listed = _decode_json(await ledger.call("clt_dave", "list_inflight", 50, 0, t=T, c=C))
    assert all(item["change_id"] != str(foreign) for item in listed)
