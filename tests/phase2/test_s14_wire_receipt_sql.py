"""Focused migration 018 contract tests (synthetic disposable PostgreSQL only).

Maps to S14-R02: approval's typed payload digest remains separate from the SHA-256
of canonical UTF-8 wire bytes; only the latter can bind a clone receipt. These
tests use the existing `led` fixture, which creates and drops a throwaway database
on the guarded disposable PostgreSQL cluster. They do not call a real 1C instance.
"""
import hashlib
import asyncpg
import pytest
from _approval_envelope import FIXTURE_PAYLOAD
from _ed25519_fixtures import pub_hex, sign_hex
from _pg_harness import fails
from business_ai_gateway.phase2.change import canonical_json
from test_change_ledger_sql import DIGEST, T, C, led

pytestmark = pytest.mark.integration

RECEIPT_KEY = "vk-s14-wire"
NEW_VERSION = "V2"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _dispatched(ledger, *, require_receipt=True):
    cid, tok, call_id, _ = await ledger.permitted(
        kind="CREATE_DRAFT", digest=DIGEST, target="s14-wire-doc")
    gen = tok["generation"]
    if require_receipt:
        await ledger.call("clt_wri", "require_dispatch_receipt", cid, gen)
    canonical = canonical_json(FIXTURE_PAYLOAD)
    assert await ledger.call("clt_wri", "verify_dispatch_payload", cid, gen, canonical) is True
    assert await ledger.call("clt_wri", "record_call", cid, gen, call_id) is True
    return cid, gen, call_id, canonical


async def _receipt(ledger, cid, call_id, digest, new_version=NEW_VERSION):
    text = await ledger.conn.fetchval(
        "SELECT change_ledger.dispatch_receipt_text($1,$2,$3,$4)",
        cid, call_id, digest, new_version)
    return sign_hex(RECEIPT_KEY, text)


async def test_wire_sha_is_independent_and_only_actual_wire_receipt_can_complete(led):
    await led.conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
        "VALUES($1,$2,$3,'receipt_role',$4)", T, C, RECEIPT_KEY, pub_hex(RECEIPT_KEY))
    cid, gen, call_id, canonical = await _dispatched(led)
    wire_sha = sha256(canonical.encode("utf-8"))
    typed_sha = (await led.rec(cid))["payload_digest"]
    assert wire_sha != typed_sha

    verification = await led.conn.fetchrow(
        "SELECT payload_digest,wire_payload_sha256 FROM change_ledger.change_dispatch_verifications "
        "WHERE change_id=$1 AND generation=$2", cid, gen)
    assert verification["payload_digest"] == typed_sha
    assert verification["wire_payload_sha256"] == wire_sha

    # A correctly signed receipt that substitutes the approval digest for received bytes is refused.
    typed_sig = await _receipt(led, cid, call_id, typed_sha)
    await fails("DIGEST_MISMATCH", led.call(
        "clt_wri", "record_dispatch_receipt", cid, gen, RECEIPT_KEY, typed_sha, NEW_VERSION, typed_sig))
    assert await led.conn.fetchval(
        "SELECT count(*) FROM change_ledger.dispatch_receipts WHERE change_id=$1", cid) == 0

    # Receipt over the actual canonical bytes is accepted, and exact receipt replay is idempotent.
    wire_sig = await _receipt(led, cid, call_id, wire_sha)
    rid = await led.call(
        "clt_wri", "record_dispatch_receipt", cid, gen, RECEIPT_KEY, wire_sha, NEW_VERSION, wire_sig)
    assert rid is not None
    assert await led.call(
        "clt_wri", "record_dispatch_receipt", cid, gen, RECEIPT_KEY, wire_sha, NEW_VERSION, wire_sig) == rid
    assert await led.conn.fetchval(
        "SELECT count(*) FROM change_ledger.dispatch_receipts WHERE change_id=$1", cid) == 1
    assert await led.complete(cid, gen, "SUCCESS") == "APPLIED"

    # The verification marker cannot be rewritten, even by the database owner/test superuser.
    with pytest.raises(asyncpg.PostgresError, match="IMMUTABLE_LEDGER"):
        await led.conn.execute(
            "UPDATE change_ledger.change_dispatch_verifications SET wire_payload_sha256=$2 "
            "WHERE change_id=$1", cid, "f" * 64)


async def test_noncanonical_payload_is_refused_without_recording_wire_evidence(led):
    cid, tok, _call_id, _ = await led.permitted(kind="CREATE_DRAFT", digest=DIGEST, target="s14-noncanonical")
    gen = tok["generation"]
    canonical = canonical_json(FIXTURE_PAYLOAD)
    await fails("SCHEMA_INVALID", led.call("clt_wri", "verify_dispatch_payload", cid, gen, " " + canonical))
    assert await led.conn.fetchval(
        "SELECT count(*) FROM change_ledger.change_dispatch_verifications "
        "WHERE change_id=$1 AND generation=$2 AND wire_payload_sha256 IS NOT NULL", cid, gen) == 0


async def test_legacy_null_wire_row_is_not_backfilled_or_sufficient_for_dispatch(led):
    cid, tok, call_id, _permit = await led.permitted(
        kind="CREATE_DRAFT", digest=DIGEST, target="s14-legacy-null")
    gen = tok["generation"]
    typed_sha = (await led.rec(cid))["payload_digest"]
    # Simulate a historical 017 verification record: typed digest only, no byte evidence.
    await led.conn.execute(
        "INSERT INTO change_ledger.change_dispatch_verifications "
        "(tenant_id,company_id,change_id,generation,payload_digest,verified_by) "
        "VALUES($1,$2,$3,$4,$5,'clt_wri')", T, C, cid, gen, typed_sha)
    old = await led.conn.fetchrow(
        "SELECT payload_digest,wire_payload_sha256 FROM change_ledger.change_dispatch_verifications "
        "WHERE change_id=$1 AND generation=$2", cid, gen)
    assert old["payload_digest"] == typed_sha and old["wire_payload_sha256"] is None

    await fails("FORBIDDEN_TRANSITION", led.call("clt_wri", "record_call", cid, gen, call_id))
    after = await led.conn.fetchrow(
        "SELECT payload_digest,wire_payload_sha256 FROM change_ledger.change_dispatch_verifications "
        "WHERE change_id=$1 AND generation=$2", cid, gen)
    assert after == old
    assert (await led.rec(cid))["execution_state"] == "APPLYING"
