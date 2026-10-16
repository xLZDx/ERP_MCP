"""Focused disposable-PostgreSQL acceptance test for R-03 / migration 019.

Run directly with the project interpreter (never through pytest):
    .venv/Scripts/python.exe tests/phase2/test_r03_migration019.py

The runner provisions an invocation-owned loopback Docker PostgreSQL cluster, seeds historical
stand-in evidence before migration 015, applies migrations 001-021, and removes only the cluster
bearing its ownership label. Scenarios map to CR101's signed-write boundaries and R-03-021's
post-cutover evidence-consumer and permit-scope contracts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest

from _pg_harness import FILES, disposable_cluster, seed_basic, throwaway_db
from _ed25519_fixtures import pub_hex, sign_hex
from r03_application_e2e import run_api_boundary
from test_change_ledger_sql import L, SIGN_KEYS, T, C, _setup


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_019 = ROOT / "db" / "phase2" / "019_ed25519_action_only.sql"
MIGRATION_020 = ROOT / "db" / "phase2" / "020_kill_switch_recovery_guard.sql"
MIGRATION_021 = ROOT / "db" / "phase2" / "021_ed25519_consumer_cutover.sql"


async def _apply_019(conn: asyncpg.Connection) -> None:
    await _apply_migration(conn, MIGRATION_019)


async def _apply_migration(conn: asyncpg.Connection, path: Path) -> None:
    raw = path.read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)",
                       hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


async def _legacy_evidence(led: L, cid, kind: str, content: dict, *, role="clt_wrk",
                           key_id="vk-legacy-wrk"):
    """Write a valid pre-cutover stand-in record through the real 018 API."""
    rec = await led.rec(cid)
    generation = rec["claim_generation"]
    call_id = await led.call_id_of(cid)
    content = {"generation": generation, "call_id": str(call_id), "nonce": uuid4().hex, **content}
    observed_at = datetime.now(UTC)
    content_hash = await led.conn.fetchval(
        "SELECT change_ledger.canonical_content_hash($1::jsonb)", json.dumps(content))
    binding = await led.conn.fetchval(
        "SELECT change_ledger.evidence_binding($1,$2,$3,$4,$5,$6)",
        cid, kind, content_hash, observed_at, generation, call_id)
    key_material = await led.conn.fetchval(
        "SELECT key_material FROM change_ledger.verifier_keys WHERE tenant_id=$1 AND company_id=$2 AND key_id=$3",
        T, C, key_id)
    signature = await _legacy_signature(led.conn, key_material, binding)
    return await led.call(role, "record_evidence", cid, kind, content_hash, observed_at,
                          json.dumps(content), key_id, binding, signature, generation, call_id)


async def _seed_legacy_consumer_cases(conn: asyncpg.Connection) -> dict:
    """Arrange genuine legacy rows and otherwise valid action preconditions before cutover."""
    post_cutover_keys = SIGN_KEYS.copy()
    SIGN_KEYS["clt_wrk"] = ("vk-precut-wrk", *SIGN_KEYS["clt_wrk"][1:])
    SIGN_KEYS["clt_wri"] = ("vk-precut-wri", *SIGN_KEYS["clt_wri"][1:])
    SIGN_KEYS["clt_chk"] = ("vk-precut-chk", *SIGN_KEYS["clt_chk"][1:])
    await _setup(conn)
    led = L(type("Db", (), {"conn": conn})())
    led.keyed = True
    await conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
        "VALUES($1,$2,'vk-legacy-wrk','clt_wrk','legacy-evidence-key'),"
        "($1,$2,'vk-legacy-wri','clt_wri','legacy-writer-key')", T, C)

    # complete_signed: a valid completion proof exists while the record is still APPLYING.
    complete_cid, complete_tok, _ = await led.dispatched(
        request_id="r03-021-complete", base="base-4")
    complete_evidence = await _legacy_evidence(
        led, complete_cid, "COMPLETION_PROOF", {"class": "a", "result_returned": True},
        role="clt_wri", key_id="vk-legacy-wri")

    # resolve_unknown_signed: produce the real APPLY_UNKNOWN state, then add a valid old observation.
    unknown_cid, _, _ = await led.unknown(request_id="r03-021-unknown", base="base-5")
    unknown_observation = await _legacy_evidence(
        led, unknown_cid, "OBSERVATION", {"effect_present": False})

    # operator_resolve must reject a legacy observation independently of its valid Ed25519 cosign.
    obs_cid, _, _ = await led.unknown(request_id="r03-021-observation", base="base-6")
    assert await led.resolve_unknown(obs_cid, None) == "TRIAGE_REQUIRED"
    obs_cosign = await led.cosign("clt_erin", obs_cid, cls="a")
    legacy_observation = await _legacy_evidence(
        led, obs_cid, "OBSERVATION", {"effect_present": True})

    # A separate TRIAGE_REQUIRED row carries a legacy completion proof in its stored cosign.
    cosign_cid, _, _ = await led.unknown(request_id="r03-021-cosign", base="base-7")
    assert await led.resolve_unknown(cosign_cid, None) == "TRIAGE_REQUIRED"
    legacy_completion = await _legacy_evidence(
        led, cosign_cid, "COMPLETION_PROOF", {"class": "b", "result_returned": False})
    cosign_id = await led.call("clt_erin", "witness_cosign_signed", cosign_cid, legacy_completion)

    # operator_close_failed_verify consumes the same cosign helper as operator_resolve.
    close_cid, close_tok, _ = await led.dispatched(
        request_id="r03-021-close", base="base-8")
    assert await led.complete(close_cid, close_tok["generation"], "SUCCESS") == "APPLIED"
    assert await led.verify(close_cid, False) == "FAILED_VERIFY"
    close_completion = await _legacy_evidence(
        led, close_cid, "COMPLETION_PROOF", {"class": "b", "result_returned": False})
    close_cosign = await led.call("clt_erin", "witness_cosign_signed", close_cid, close_completion)

    # Cross-tenant permit attempt: caller has a legitimate T2/C2 checkpoint key and scope.
    await conn.execute("INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,"
                       "organization_ref,target_class) VALUES($1,$2,'r03-cross-permit',$3,'DISPOSABLE_CLONE')",
                       T, C, "org-1")
    permit_cid, permit_tok, _, _ = await led.permitted(
        request_id="r03-021-cross-permit", base="r03-cross-permit")
    await conn.execute("SELECT change_ledger.add_role_scope('clt_chk','T2','C2')")
    await conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
        "VALUES('T2','C2','vk-chk-t2','checkpoint_role',$1)", pub_hex("vk-chk-t2"))
    permit_digest = await conn.fetchval(
        "SELECT permit_digest FROM change_ledger.dispatch_permits WHERE change_id=$1", permit_cid)
    SIGN_KEYS.clear()
    SIGN_KEYS.update(post_cutover_keys)
    return {"led": led, "complete": (complete_cid, complete_tok, complete_evidence),
            "unknown": (unknown_cid, unknown_observation),
            "observation": (obs_cid, obs_cosign, legacy_observation),
            "cosign": (cosign_cid, cosign_id, legacy_completion),
            "close": (close_cid, close_cosign, close_completion),
            "permit": (permit_cid, permit_tok, permit_digest)}


async def _assert_021_consumers(conn: asyncpg.Connection, fixtures: dict) -> None:
    led = fixtures["led"]
    cid, tok, completion = fixtures["complete"]
    before = await led.rec(cid)
    before_events = await conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1", cid)
    await _expect_error(led.call("clt_wri", "complete_signed", cid, tok["generation"],
                                 "SUCCESS", completion), "EVIDENCE_UNSIGNED")
    after = await led.rec(cid)
    assert after["execution_state"] == before["execution_state"] == "APPLYING"
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1", cid) == before_events

    cid, observation = fixtures["unknown"]
    before_state = (await led.rec(cid))["execution_state"]
    await _expect_error(led.call("clt_wrk", "resolve_unknown_signed", cid, observation, None,
                                 False, False), "EVIDENCE_UNSIGNED")
    assert (await led.rec(cid))["execution_state"] == before_state == "APPLY_UNKNOWN"

    # Historical audit reads remain available and expose the legacy row unchanged.
    evidence = await led.call("clt_aud", "read_evidence", cid)
    evidence = json.loads(evidence) if isinstance(evidence, str) else evidence
    assert any(row["evidence_id"] == str(observation) and row["signer_key_id"] == "vk-legacy-wrk"
               for row in evidence)

    cid, valid_cosign, legacy_obs = fixtures["observation"]
    before_state = (await led.rec(cid))["execution_state"]
    await _expect_error(led.call("clt_dave", "operator_resolve", cid, valid_cosign, True, False),
                        "COMPLETION_PROOF_MISSING")
    assert (await led.rec(cid))["execution_state"] == before_state == "TRIAGE_REQUIRED"
    assert await conn.fetchval("SELECT consumed_at IS NULL FROM change_ledger.witness_cosigns "
                               "WHERE cosign_id=$1", valid_cosign)

    cid, cosign_id, legacy_completion = fixtures["cosign"]
    before_state = (await led.rec(cid))["execution_state"]
    await _expect_error(led.call("clt_dave", "operator_resolve", cid, cosign_id, False, False),
                        "COMPLETION_PROOF_MISSING")
    assert (await led.rec(cid))["execution_state"] == before_state == "TRIAGE_REQUIRED"
    assert await conn.fetchval("SELECT consumed_at IS NULL FROM change_ledger.witness_cosigns "
                               "WHERE cosign_id=$1", cosign_id)

    cid, cosign_id, _ = fixtures["close"]
    before_hold = await conn.fetchval("SELECT released_at IS NULL FROM change_ledger.holds "
                                      "WHERE change_id=$1 AND cause='FAILED_VERIFY_HALT'", cid)
    await _expect_error(led.call("clt_dave", "operator_close_failed_verify", cid, cosign_id, True),
                        "COMPLETION_PROOF_MISSING")
    assert (await led.rec(cid))["verification_state"] == "FAILED_VERIFY"
    assert await conn.fetchval("SELECT released_at IS NULL FROM change_ledger.holds "
                               "WHERE change_id=$1 AND cause='FAILED_VERIFY_HALT'", cid) == before_hold is True
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.change_closures WHERE change_id=$1", cid) == 0
    assert await conn.fetchval("SELECT consumed_at IS NULL FROM change_ledger.witness_cosigns "
                               "WHERE cosign_id=$1", cosign_id)

    cid, tok, digest = fixtures["permit"]
    await conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material,key_algorithm) "
        "VALUES('T2','C2','vk-chk-t2-021','checkpoint_role',$1,'ED25519')", pub_hex("vk-chk-t2-021"))
    await conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material,key_algorithm) "
        "VALUES($1,$2,'vk-chk-021','checkpoint_role',$3,'ED25519')", T, C, pub_hex("vk-chk-021"))
    signature = sign_hex("vk-chk-t2-021", "change-ledger-permit|v1|" + digest)
    await _expect_error(led.call("clt_chk", "attach_permit_signature", cid, tok["generation"],
                                 "vk-chk-t2-021", signature, t="T2", c="C2"), "PERMIT_MISSING")
    assert await conn.fetchval("SELECT signature IS NULL FROM change_ledger.dispatch_permits "
                               "WHERE change_id=$1", cid)
    await led.call("clt_chk", "attach_permit_signature", cid, tok["generation"], "vk-chk-021",
                   sign_hex("vk-chk-021", "change-ledger-permit|v1|" + digest))
    assert await conn.fetchval("SELECT signer_key_id FROM change_ledger.dispatch_permits "
                               "WHERE change_id=$1", cid) == "vk-chk-021"


async def _install_post_cutover_ed25519_test_keys(conn: asyncpg.Connection) -> None:
    """Keep the later CR101 success controls on fresh Ed25519 identities."""
    replacements = {
        "clt_wrk": ("vk-wrk", pub_hex("vk-wrk"), "clt_wrk"),
        "clt_wri": ("vk-wri", pub_hex("vk-wri"), "clt_wri"),
        "clt_chk": ("vk-chk", pub_hex("vk-chk"), "checkpoint_role"),
    }
    for role, (key_id, material, key_role) in replacements.items():
        await conn.execute(
            "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material,key_algorithm) "
            "VALUES($1,$2,$3,$4,$5,'ED25519')", T, C, key_id, key_role, material)
        SIGN_KEYS[role] = (key_id, material, key_role)


async def _insert_legacy_key(conn: asyncpg.Connection, key_id: str, role: str, material: str) -> None:
    await conn.execute(
        "INSERT INTO change_ledger.verifier_keys"
        "(tenant_id,company_id,key_id,role_name,key_material,key_algorithm) "
        "VALUES($1,$2,$3,$4,$5,'KEYED_HASH_STANDIN') ON CONFLICT(tenant_id,company_id,key_id) DO NOTHING",
        T, C, key_id, role, material,
    )


async def _legacy_signature(conn: asyncpg.Connection, key: str, payload: str) -> str:
    return await conn.fetchval("SELECT change_ledger.keyed_signature($1,$2)", key, payload)


async def _expect_error(coro, expected: str) -> None:
    try:
        await coro
    except asyncpg.PostgresError as error:
        assert expected in str(error), f"expected {expected}, got {error!s}"
        return
    raise AssertionError(f"expected database error {expected}, but the write succeeded")


async def _run_scenarios(conn: asyncpg.Connection, *, setup: bool = True) -> None:
    if setup:
        await _setup(conn)
    led = L(type("Db", (), {"conn": conn})())

    # CR101-A: evidence rejects a correctly signed legacy key without storing evidence;
    # the equivalent valid Ed25519 path still writes evidence.
    legacy_evidence_key = "legacy-evidence-key"
    await _insert_legacy_key(conn, "vk-legacy-wrk", "clt_wrk", legacy_evidence_key)
    evidence_cid, evidence_tok, evidence_call = await led.applying(
        request_id="r03-evidence", base="base-1")
    evidence_content = {"nonce": "r03-evidence", "matches": True}
    evidence_at = datetime.now(UTC)
    evidence_hash = await conn.fetchval(
        "SELECT change_ledger.canonical_content_hash($1::jsonb)", json.dumps(evidence_content))
    evidence_binding = await conn.fetchval(
        "SELECT change_ledger.evidence_binding($1,$2,$3,$4,$5,$6)",
        evidence_cid, "FIELD", evidence_hash, evidence_at, evidence_tok["generation"], evidence_call)
    evidence_sig = await _legacy_signature(conn, legacy_evidence_key, evidence_binding)
    await _expect_error(led.call(
        "clt_wrk", "record_evidence", evidence_cid, "FIELD", evidence_hash, evidence_at,
        json.dumps(evidence_content), "vk-legacy-wrk", evidence_binding, evidence_sig,
        evidence_tok["generation"], evidence_call), "EVIDENCE_UNSIGNED")
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.evidence_records WHERE change_id=$1", evidence_cid) == 0
    valid_evidence = await led.evidence(
        evidence_cid, "FIELD", {"matches": True}, gen=evidence_tok["generation"],
        call_id=evidence_call, at=evidence_at)
    assert await conn.fetchval(
        "SELECT signer_key_id FROM change_ledger.evidence_records WHERE evidence_id=$1", valid_evidence) == \
        SIGN_KEYS["clt_wrk"][0]
    evidence_row = await conn.fetchrow(
        "SELECT kind,content_hash,observed_at,content,signer_key_id,binding_hash,signature,generation,call_id "
        "FROM change_ledger.evidence_records WHERE evidence_id=$1", valid_evidence)
    replayed_evidence = await led.call(
        "clt_wrk", "record_evidence", evidence_cid, evidence_row["kind"], evidence_row["content_hash"],
        evidence_row["observed_at"], evidence_row["content"], evidence_row["signer_key_id"],
        evidence_row["binding_hash"], evidence_row["signature"], evidence_row["generation"],
        evidence_row["call_id"])
    assert replayed_evidence == valid_evidence, "valid Ed25519 evidence replay must remain idempotent"
    await _expect_error(led.call(
        "clt_wrk", "record_evidence", evidence_cid, evidence_row["kind"], evidence_row["content_hash"],
        evidence_row["observed_at"], evidence_row["content"], evidence_row["signer_key_id"],
        evidence_row["binding_hash"], evidence_row["signature"], evidence_row["generation"],
        evidence_row["call_id"], t="T2", c="C2"), "SCOPE_NOT_GRANTED")
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.evidence_records WHERE change_id=$1", evidence_cid) == 1

    # CR101-B: checkpoint rejects a valid stand-in signature and accepts the existing Ed25519 signer.
    await _insert_legacy_key(conn, "vk-legacy-checkpoint", "checkpoint_role", "legacy-checkpoint-key")
    head = await led.head()
    checkpoint_at = datetime.now(UTC)
    checkpoint_payload = await conn.fetchval(
        "SELECT change_ledger.checkpoint_payload($1,$2,$3,$4,$5,$6,$7,$8)",
        T, C, head["seq"], head["head_hash"], checkpoint_at,
        "vk-legacy-checkpoint", "REAL", "r03-sink")
    checkpoint_sig = await _legacy_signature(conn, "legacy-checkpoint-key", checkpoint_payload)
    before_checkpoints = await conn.fetchval("SELECT count(*) FROM change_ledger.checkpoints")
    await _expect_error(led.call(
        "clt_chk", "record_checkpoint", head["seq"], head["head_hash"], "REAL", "r03-sink",
        "vk-legacy-checkpoint", checkpoint_sig, checkpoint_at, True), "CHECKPOINT_UNAVAILABLE")
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.checkpoints") == before_checkpoints
    await led.checkpoint()
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.checkpoints") == before_checkpoints + 1

    # CR101-C: permit signing rejects the legacy checkpoint key, leaves the permit unsigned,
    # and accepts a valid Ed25519 signature for the same permit digest.
    permit_cid, permit_tok, _, _ = await led.permitted(
        request_id="r03-permit", base="base-2")
    permit_digest = await conn.fetchval(
        "SELECT permit_digest FROM change_ledger.dispatch_permits WHERE change_id=$1", permit_cid)
    legacy_permit_sig = await _legacy_signature(
        conn, "legacy-checkpoint-key", "change-ledger-permit|v1|" + permit_digest)
    await _expect_error(led.call(
        "clt_chk", "attach_permit_signature", permit_cid, permit_tok["generation"],
        "vk-legacy-checkpoint", legacy_permit_sig), "CHECKPOINT_UNAVAILABLE")
    assert await conn.fetchval(
        "SELECT signature IS NULL FROM change_ledger.dispatch_permits WHERE change_id=$1", permit_cid)
    valid_permit_sig = sign_hex("vk-chk", "change-ledger-permit|v1|" + permit_digest)
    await led.call("clt_chk", "attach_permit_signature", permit_cid, permit_tok["generation"],
                   "vk-chk", valid_permit_sig)
    assert await conn.fetchval(
        "SELECT signer_key_id FROM change_ledger.dispatch_permits WHERE change_id=$1", permit_cid) == "vk-chk"
    await led.call("clt_chk", "attach_permit_signature", permit_cid, permit_tok["generation"],
                   "vk-chk", valid_permit_sig)
    await _expect_error(led.call(
        "clt_wrk", "attach_permit_signature", permit_cid, permit_tok["generation"],
        "vk-chk", valid_permit_sig), "permission denied")

    # CR101-D: a KEYED_HASH_STANDIN row assigned receipt_role bypassed 017's Ed25519-only
    # uniqueness guard; 019 must reject it at the mutating boundary. The valid Ed25519 path succeeds.
    await _insert_legacy_key(conn, "vk-legacy-receipt", "receipt_role", "legacy-receipt-key")
    receipt_cid, receipt_tok, _ = await led.dispatched(
        request_id="r03-receipt", base="base-3")
    receipt_sha = await conn.fetchval(
        "SELECT wire_payload_sha256 FROM change_ledger.change_dispatch_verifications "
        "WHERE change_id=$1 AND generation=$2", receipt_cid, receipt_tok["generation"])
    receipt_text = await conn.fetchval(
        "SELECT change_ledger.dispatch_receipt_text($1,$2,$3,$4)",
        receipt_cid, await led.call_id_of(receipt_cid), receipt_sha, "v2")
    legacy_receipt_sig = await _legacy_signature(conn, "legacy-receipt-key", receipt_text)
    await _expect_error(led.call(
        "clt_alice", "record_dispatch_receipt", receipt_cid, receipt_tok["generation"],
        "vk-legacy-receipt", receipt_sha, "v2", legacy_receipt_sig), "EVIDENCE_UNSIGNED")
    await _expect_error(led.call(
        "clt_alice", "record_dispatch_receipt", receipt_cid, receipt_tok["generation"],
        "vk-wrk", receipt_sha, "v2", sign_hex("vk-wrk", receipt_text)), "EVIDENCE_UNSIGNED")
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.dispatch_receipts WHERE change_id=$1", receipt_cid) == 0
    await conn.execute(
        "INSERT INTO change_ledger.verifier_keys"
        "(tenant_id,company_id,key_id,role_name,key_material,key_algorithm) "
        "VALUES($1,$2,'vk-r03-receipt','receipt_role',$3,'ED25519')",
        T, C, pub_hex("vk-r03-receipt"))
    valid_receipt_sig = sign_hex("vk-r03-receipt", receipt_text)
    receipt_id = await led.call(
        "clt_alice", "record_dispatch_receipt", receipt_cid, receipt_tok["generation"],
        "vk-r03-receipt", receipt_sha, "v2", valid_receipt_sig)
    receipt_replay = await led.call(
        "clt_alice", "record_dispatch_receipt", receipt_cid, receipt_tok["generation"],
        "vk-r03-receipt", receipt_sha, "v2", valid_receipt_sig)
    assert receipt_replay == receipt_id, "valid Ed25519 receipt replay must remain idempotent"
    assert await conn.fetchval(
        "SELECT signer_key_id FROM change_ledger.dispatch_receipts WHERE receipt_id=$1", receipt_id) == "vk-r03-receipt"

    # CR101-E: the internal generic verifier keeps its legacy branch, while runtime callers
    # still cannot invoke that helper directly.
    assert await conn.fetchval(
        "SELECT change_ledger.signature_ok('KEYED_HASH_STANDIN',$1,$2,$3)",
        legacy_evidence_key, "legacy-read-check", await _legacy_signature(conn, legacy_evidence_key, "legacy-read-check"))
    await _expect_error(led.sql("clt_wrk", "SELECT change_ledger.signature_ok("
        "'KEYED_HASH_STANDIN',$1,$2,$3)",
        legacy_evidence_key, "legacy-read-check",
        await _legacy_signature(conn, legacy_evidence_key, "legacy-read-check")), "permission denied")

    # CR101-F: traverse the application SQL adapter at the same migrated database boundary.
    api_result = await run_api_boundary(conn)
    assert api_result["valid_ed25519"] == "accepted and recorded"
    assert api_result["valid_legacy_signature"] == "rejected as EVIDENCE_UNSIGNED"
    assert api_result["state"] == "rejected action left no row"
    print(f"E2E: {api_result}")


async def main() -> int:
    # This test owns the cluster for its complete lifetime; never attach to a pre-existing DB.
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    try:
        async with disposable_cluster() as (dsn, container_name, _token):
            async with throwaway_db(dsn, migrate=False) as db:
                db.conn = await db.connect()
                for name in FILES[:14]:
                    await _apply_migration(db.conn, ROOT / "db" / "phase2" / name)
                await seed_basic(db.conn)
                fixtures = await _seed_legacy_consumer_cases(db.conn)
                for name in FILES[14:]:
                    await _apply_migration(db.conn, ROOT / "db" / "phase2" / name)
                fixtures["led"].keyed = False
                await _install_post_cutover_ed25519_test_keys(db.conn)
                await _apply_019(db.conn)
                await _apply_migration(db.conn, MIGRATION_020)
                await _apply_migration(db.conn, MIGRATION_021)
                version = await db.conn.fetchval(
                    "SELECT count(*) FROM living.schema_migrations WHERE version='019'")
                assert version == 1, f"migration 019 record count is {version}, expected 1"
                for migration in ("020", "021"):
                    count = await db.conn.fetchval(
                        "SELECT count(*) FROM living.schema_migrations WHERE version=$1", migration)
                    assert count == 1, f"migration {migration} record count is {count}, expected 1"
                await _assert_021_consumers(db.conn, fixtures)
                await _run_scenarios(db.conn, setup=False)
    except pytest.skip.Exception as unavailable:
        print(f"NOT_RUN: {unavailable}")
        return 0
    print(f"PASS: CR101-A..F and R-03-021-consumers on owned container {container_name}; "
          "migrations 001-021 applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
