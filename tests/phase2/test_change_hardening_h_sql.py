"""Focused PostgreSQL tests for db/phase2/016_dispatch_receipt.sql: the receipt of the bytes the simulated 1C received is
signed by the clone itself (own Ed25519 key) and verified inside the ledger (simulation program P4, GPT-PM F-01).

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database with all migrations applied.

Chosen compatibility mode: the receipt requirement is OPT-IN per dispatch (require_dispatch_receipt marker), so every
existing flow that completes without a receipt stays valid (test h5).

Item -> tests:
  h1 valid receipt accepted, completion allowed          h1_*
  h2 tampered received digest refused                    h2_*
  h3 wrong key / wrong role / unregistered key refused   h3_*
  h4 replay of a receipt on another dispatch refused     h4_*
  h5 completion without receipt refused where required   h5_*  (and allowed where not required)
"""
import asyncpg
import pytest
from _approval_envelope import FIXTURE_PAYLOAD
from _pg_harness import fails, require_dsn, throwaway_db
from test_change_ledger_sql import C, T, L, _setup

from business_ai_gateway.phase2.change import canonical_json, sha256_hex
from business_ai_gateway.phase2.simulation.clone_1c import SimulatedOneC, receipt_signing_text, verify_clone_receipt

pytestmark = pytest.mark.integration

CLONE = SimulatedOneC("SIM-CLONE-A")
OTHER_CLONE = SimulatedOneC("SIM-CLONE-OTHER")
KEY = "vk-clone"
VERSION = "V1"


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        await db.conn.execute(
            "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
            "VALUES($1,$2,$3,'receipt_role',$4)", T, C, KEY, CLONE.receipt_public_key_hex)
        yield L(db)


async def dispatched(led, *, require=True, target="doc1", base="base-1"):
    """A DISPATCHED change; with `require` the receipt marker is set before the dispatch."""
    cid, tok, call_id, _ = await led.permitted(target=target, base=base)
    if require:
        await led.call("clt_wri", "require_dispatch_receipt", cid, tok["generation"])
    assert await led.call("clt_wri", "record_call", cid, tok["generation"], call_id) is True
    # migration 018: the clone signs the sha256 of the exact canonical wire bytes the ledger verified before
    # dispatch (change_dispatch_verifications.wire_payload_sha256), not the typed approval payload_digest
    digest = await led.conn.fetchval(
        "SELECT wire_payload_sha256 FROM change_ledger.change_dispatch_verifications "
        "WHERE change_id=$1 AND generation=$2 AND wire_payload_sha256 IS NOT NULL", cid, tok["generation"])
    assert digest is not None and digest != (await led.rec(cid))["payload_digest"]
    return cid, tok["generation"], call_id, digest


def receipt(clone, cid, call_id, digest, version=VERSION):
    """What the clone itself signs and returns; the ledger only receives its fields."""
    return clone._sign_receipt(str(cid), str(call_id), digest, version)


async def put(led, cid, gen, rc, key=KEY, role="clt_wri"):
    return await led.call(role, "record_dispatch_receipt", cid, gen, key, rc["received_payload_sha256"],
                          rc["new_version"], rc["signature"])


async def n_receipts(led, cid):
    return await led.conn.fetchval("SELECT count(*) FROM change_ledger.dispatch_receipts WHERE change_id=$1", cid)


# ============================================================================ h1 valid
async def test_h1_valid_clone_receipt_is_accepted_and_completion_succeeds(led):
    cid, gen, call_id, digest = await dispatched(led)
    assert digest == sha256_hex(canonical_json(FIXTURE_PAYLOAD))             # independent Python derivation of the wire sha
    rc = receipt(CLONE, cid, call_id, digest)
    assert verify_clone_receipt(CLONE.receipt_public_key_hex, rc)            # the offline verifier agrees with the ledger text
    assert receipt_signing_text(str(cid), str(call_id), digest, VERSION) == await led.conn.fetchval(
        "SELECT change_ledger.dispatch_receipt_text($1,$2,$3,$4)", cid, call_id, digest, VERSION)
    rid = await put(led, cid, gen, rc)
    assert rid is not None and await n_receipts(led, cid) == 1
    assert await put(led, cid, gen, rc) == rid and await n_receipts(led, cid) == 1     # exact replay is idempotent
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1 "
                                   "AND event_type='DISPATCH_RECEIPT_RECORDED'", cid) == 1
    assert await led.complete(cid, gen, "SUCCESS") == "APPLIED"
    # the stored receipt is immutable
    with pytest.raises(asyncpg.PostgresError):
        await led.conn.execute("UPDATE change_ledger.dispatch_receipts SET new_version='V9'")


# ============================================================================ h2 tampered digest
async def test_h2_tampered_received_digest_is_refused(led):
    cid, gen, call_id, digest = await dispatched(led)
    tampered = "f" * 64
    assert tampered != digest
    await fails("DIGEST_MISMATCH", put(led, cid, gen, receipt(CLONE, cid, call_id, tampered)))   # clone signed other bytes
    # 018: a receipt over the typed approval payload_digest (not the wire bytes) is refused too
    typed = (await led.rec(cid))["payload_digest"]
    await fails("DIGEST_MISMATCH", put(led, cid, gen, receipt(CLONE, cid, call_id, typed)))
    # a field changed after signing no longer verifies
    good = receipt(CLONE, cid, call_id, digest)
    await fails("EVIDENCE_UNSIGNED", put(led, cid, gen, {**good, "new_version": "V2"}))
    await fails("EVIDENCE_UNSIGNED", put(led, cid, gen, {**good, "received_payload_sha256": tampered}))
    assert await n_receipts(led, cid) == 0
    await fails("EVIDENCE_UNSIGNED", led.complete(cid, gen, "SUCCESS"))


# ============================================================================ h3 keys
async def test_h3_wrong_key_wrong_role_and_unregistered_key_are_refused(led):
    cid, gen, call_id, digest = await dispatched(led)
    forged = receipt(OTHER_CLONE, cid, call_id, digest)                       # valid receipt of ANOTHER clone key
    await fails("EVIDENCE_UNSIGNED", put(led, cid, gen, forged))
    good = receipt(CLONE, cid, call_id, digest)
    await fails("EVIDENCE_UNSIGNED", put(led, cid, gen, good, key="vk-unregistered"))
    await fails("EVIDENCE_UNSIGNED", put(led, cid, gen, good, key="vk-wri"))  # a registered key of another purpose (role)
    # the same clone key registered under another role is not a receipt key either
    await fails("KEY_ROLE_CONFLICT", led.conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
        "VALUES($1,$2,'vk-clone-wrk','clt_wrk',$3)", T, C, CLONE.receipt_public_key_hex))
    # a runtime actor that is not the requester / writer cannot submit a receipt
    await fails("permission denied", put(led, cid, gen, good, role="clt_wrk"))
    assert await n_receipts(led, cid) == 0
    # the receipt key cannot sign evidence either (no actor holds receipt_role)
    assert await put(led, cid, gen, good) is not None


# ============================================================================ h4 replay
async def test_h4_receipt_of_another_dispatch_is_refused(led):
    a, gen_a, call_a, digest_a = await dispatched(led, target="doc1")
    b, gen_b, call_b, digest_b = await dispatched(led, target="doc2", base="base-2")
    assert call_a != call_b
    rc_a = receipt(CLONE, a, call_a, digest_a)
    await fails("EVIDENCE_UNSIGNED", put(led, b, gen_b, rc_a))                # receipt of dispatch A replayed on change B
    rc_b_wrong_dispatch = receipt(CLONE, b, call_a, digest_b)                 # right change, other dispatch id
    await fails("EVIDENCE_UNSIGNED", put(led, b, gen_b, rc_b_wrong_dispatch))
    rc_a_other_change = receipt(CLONE, b, call_b, digest_b)
    await put(led, b, gen_b, rc_a_other_change)                               # the genuine one is accepted
    await fails("EVIDENCE_UNSIGNED", put(led, a, gen_a, rc_a_other_change))   # and cannot be moved back to A
    assert await n_receipts(led, a) == 0 and await n_receipts(led, b) == 1


# ============================================================================ h5 completion gate
async def test_h5_completion_without_receipt_is_refused_where_required(led):
    cid, gen, call_id, digest = await dispatched(led, require=True)
    await fails("EVIDENCE_UNSIGNED", led.complete(cid, gen, "SUCCESS"))
    assert (await led.rec(cid))["execution_state"] == "APPLYING"
    # a failed completion path is not blocked by the marker (only APPLIED is)
    await put(led, cid, gen, receipt(CLONE, cid, call_id, digest))
    assert await led.complete(cid, gen, "SUCCESS") == "APPLIED"


async def test_h5_completion_without_marker_is_unchanged_legacy_lane(led):
    cid, gen, _call_id, _digest = await dispatched(led, require=False)
    assert await led.complete(cid, gen, "SUCCESS") == "APPLIED"
    assert await n_receipts(led, cid) == 0


async def test_h5_marker_and_receipt_preconditions(led):
    cid, tok, call_id, _ = await led.permitted()
    gen = tok["generation"]
    await fails("PERMIT_MISSING", put(led, cid, gen, receipt(CLONE, cid, call_id, "a" * 64)))   # not dispatched yet
    await fails("TICKET_SUPERSEDED", led.call("clt_wri", "require_dispatch_receipt", cid, gen + 1))
    await fails("permission denied", led.call("clt_wrk", "require_dispatch_receipt", cid, gen))
    await led.call("clt_wri", "require_dispatch_receipt", cid, gen)
    await led.call("clt_wri", "require_dispatch_receipt", cid, gen)            # idempotent
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.dispatch_receipt_requirements "
                                   "WHERE change_id=$1", cid) == 1
    assert await led.call("clt_wri", "record_call", cid, gen, call_id) is True
    await fails("FORBIDDEN_TRANSITION", led.call("clt_wri", "require_dispatch_receipt", cid, gen))   # too late
