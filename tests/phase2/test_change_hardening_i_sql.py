"""Focused PostgreSQL regressions for receipt hardening migration 017."""
import pytest

from _pg_harness import fails, require_dsn, throwaway_db
from test_change_ledger_sql import C, T, L, _setup
from test_change_hardening_h_sql import CLONE, KEY, OTHER_CLONE, dispatched, put, receipt

pytestmark = pytest.mark.integration


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        await db.conn.execute(
            "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
            "VALUES($1,$2,$3,'receipt_role',$4)", T, C, KEY, CLONE.receipt_public_key_hex)
        yield L(db)


async def test_i1_receipt_requirement_moves_to_reclaimed_generation(led):
    cid, tok, _call_id = await led.applying()
    old_gen = tok["generation"]
    await led.call("clt_wri", "require_dispatch_receipt", cid, old_gen)
    # Simulate recovery of an expired APPLYING claim whose permit was never issued.
    assert await led.conn.fetchval(
        "SELECT change_ledger.permit_not_issued_internal($1,$2,$3,0)", T, C, cid) is True
    new_tok = await led.claimed(cid)
    new_gen = new_tok["generation"]
    assert new_gen == old_gen + 1
    assert await led.conn.fetchval(
        "SELECT count(*) FROM change_ledger.dispatch_receipt_requirements WHERE change_id=$1 AND generation=$2",
        cid, new_gen) == 1


async def test_i2_receipt_is_rejected_after_change_becomes_terminal(led):
    cid, gen, call_id, digest = await dispatched(led)
    rc = receipt(CLONE, cid, call_id, digest)
    await put(led, cid, gen, rc)
    assert await led.complete(cid, gen, "SUCCESS") == "APPLIED"
    await fails("FORBIDDEN_TRANSITION", put(led, cid, gen, rc))


async def test_i3_receipt_public_key_cannot_be_registered_under_another_role(led):
    await fails("KEY_ROLE_CONFLICT", led.conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
        "VALUES($1,$2,'vk-same-key-worker','clt_wrk',$3)", T, C, CLONE.receipt_public_key_hex))


async def test_i4_receipt_key_cannot_be_repurposed_after_registration(led):
    await led.conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
        "VALUES($1,$2,'vk-worker-first','clt_wrk',$3)", T, C, OTHER_CLONE.receipt_public_key_hex)
    await fails("KEY_ROLE_CONFLICT", led.conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
        "VALUES($1,$2,'vk-receipt-first','receipt_role',$3)", T, C, OTHER_CLONE.receipt_public_key_hex))
