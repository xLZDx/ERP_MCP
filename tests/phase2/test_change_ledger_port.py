"""Focused PostgreSQL integration tests for the thin Python port src/business_ai_gateway/phase2/change_ledger.

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database with 001-007 applied and the clt_* actors of
test_change_ledger_sql.py. The port is driven exactly as production would: one SQL function per call under
SET LOCAL ROLE of the caller class. Superuser access only reads results and counts rows.

007 intentionally changed the API (the assertions below were rewritten only where that applies): the raw
complete / verify / resolve_unknown / witness_cosign are revoked from every runtime role, so the journeys use the
typed-evidence ``*_signed`` paths; approve compares an SQL-computed approval digest; record_checkpoint and
attach_permit_signature belong to the checkpoint identity and verify a keyed-hash signature against a registered
key. RealSigner / RealVerifier / RealSink below are TEST-ONLY stand-ins that merely CLAIM to be real.
"""
import asyncio
import hashlib
import inspect
import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from _pg_harness import require_dsn, throwaway_db
from test_change_ledger_sql import BASE, C, DEFAULT_GRANT, DIGEST, KH, ORG, SIGN_KEYS, T, _setup, exp

from business_ai_gateway.phase2.change_ledger._common import LedgerError, Scope, code_from_message
from business_ai_gateway.phase2.change_ledger.checkpoint import (
    CheckpointRecord,
    CheckpointUnavailable,
    DispatchGate,
    FakeSigner,
    FakeVerifier,
    GateDisabled,
    InMemoryCheckpointSink,
    PermitRefused,
    UnwiredVerifier,
    evidence_binding,
    permit_signing_payload,
)
from business_ai_gateway.phase2.change_ledger.sql_ledger import CLASSES, SPEC, SqlChangeLedger
from business_ai_gateway.phase2.change_ledger.write_port import (
    ApplyTicket,
    DispatchPermit,
    NonOperationalWritePort,
    NotWired,
)

pytestmark = pytest.mark.integration

SCOPE = Scope(T, C)
ACTORS = {"requester": "clt_alice", "approver": "clt_bob", "operator": "clt_erin", "writer": "clt_wri",
          "worker": "clt_wrk", "auditor": "clt_aud", "checkpoint": "clt_chk"}
GROUP = {c: c + "_role" for c in CLASSES}
REGTYPE = {"timestamptz": "timestamp with time zone"}
RAW_REVOKED = ("complete", "resolve_unknown", "verify", "witness_cosign")  # 007 A1: internals of the signed paths
CHK_KEY_ID, CHK_KEY_MATERIAL, _ = SIGN_KEYS["clt_chk"]  # keyed-hash stand-in for the D9 signer (TEST ONLY)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class RealSink:
    """In-memory stand-in that CLAIMS to be a real external store (kind REAL) - the SQL cannot tell."""

    kind = "REAL"

    def __init__(self):
        self.sink_id = "ext-store-1"
        self.rows = {}

    async def write(self, record):
        self.rows[(record.tenant_id, record.company_id, record.seq)] = record

    async def read_back(self, scope, seq):
        return self.rows.get((scope.tenant_id, scope.company_id, seq))


class RealSigner:
    """TEST-ONLY stand-in that claims to be a real signer: the keyed hash registered for checkpoint_role."""

    key_id = CHK_KEY_ID
    is_test_double = False

    def sign(self, payload):
        return sha(f"{CHK_KEY_MATERIAL}:{payload.decode()}")


class RealVerifier:
    is_test_double = False

    def verify(self, key_id, payload, signature):
        return key_id == CHK_KEY_ID and signature == sha(f"{CHK_KEY_MATERIAL}:{payload.decode()}")


@pytest.fixture
async def env():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield db.conn, SqlChangeLedger(db.conn, ACTORS)


async def declare_inputs(port, cid):
    """008: a draft needs its business key, its target class and its stored budget before validate."""
    await port.declare_business_key(SCOPE, cid, sha(str(cid)))
    await port.declare_target_class(SCOPE, cid, "CLONE")
    await port.declare_budget(SCOPE, cid, DEFAULT_GRANT[(T, C)], "EUR", 0)


async def applying(port):
    """propose -> validate -> approve (nonce) -> claim -> begin_apply; returns ids."""
    cid = uuid.uuid4()
    assert await port.propose(SCOPE, cid, "CREATE_DRAFT", BASE, ORG, "clt_alice", uuid.uuid4().hex,
                              DIGEST, "doc1", "v1", None, exp()) == cid
    await declare_inputs(port, cid)
    assert await port.validate(SCOPE, cid) == "VALIDATED"
    nonce = await port.issue_approval_nonce(SCOPE, cid)
    digest = (await port.read_status(SCOPE, cid, as_class="approver"))["approval_digest"]
    assert isinstance(await port.approve(SCOPE, cid, nonce, digest), uuid.UUID)
    tok = await port.claim(SCOPE, cid, None, DEFAULT_GRANT[(T, C)], 0)
    assert tok["change_id"] == cid and tok["generation"] == 1
    call_id = uuid.uuid4()
    assert await port.observe_target(SCOPE, tok["token_id"], BASE, "CLONE") is True
    got = await port.begin_apply(SCOPE, tok["token_id"], call_id, "host-1", "sess-1")
    assert got["token_id"] == tok["token_id"]
    return cid, tok["generation"], call_id


async def evidence(conn, port, cid, kind, content, actor="worker", gen=None, call_id=None):
    """Record one signed evidence record through the port (generation / call id default to the current ones)."""
    if gen is None:
        gen = await conn.fetchval("SELECT claim_generation FROM change_ledger.records WHERE change_id=$1", cid)
    if call_id is None:
        call_id = await conn.fetchval("SELECT call_id FROM change_ledger.dispatch_permits WHERE change_id=$1 "
                                      "AND generation=$2", cid, gen)
    content = {"nonce": uuid.uuid4().hex, **content}
    if kind in ("COMPLETION_PROOF", "OBSERVATION"):
        content = {"generation": gen, "call_id": str(call_id), **content}
    at = datetime.now(UTC) + timedelta(seconds=1)
    ch = await conn.fetchval("SELECT change_ledger.canonical_content_hash($1::jsonb)", json.dumps(content))
    binding = evidence_binding(str(cid), kind, ch, at, gen, call_id)
    kid, kmat, _ = SIGN_KEYS["clt_wri" if actor == "writer" else "clt_wrk"]
    return await port.record_evidence(SCOPE, cid, kind, ch, at, content, kid, binding, sha(f"{kmat}:{binding}"),
                                      gen, call_id, as_class=actor)


async def signed_checkpoint(port, seq, head_hash, kind="REAL", sink_id="s", read_back=True, signature=None,
                            key_id=CHK_KEY_ID, as_class="checkpoint"):
    """record_checkpoint with the exact 007 payload (CheckpointRecord mirrors change_ledger.checkpoint_payload)."""
    signed_at = datetime.now(UTC)
    rec = CheckpointRecord(SCOPE.tenant_id, SCOPE.company_id, seq, head_hash, signed_at, key_id, "", sink_id, kind)
    sig = signature if signature is not None else RealSigner().sign(rec.signing_payload())
    return await port.record_checkpoint(SCOPE, seq, head_hash, kind, sink_id, key_id, sig, signed_at, read_back,
                                        as_class=as_class)


async def apply_seq(conn, cid):
    return await conn.fetchval("SELECT max(seq) FROM change_ledger.events WHERE change_id=$1 "
                               "AND event_type='APPLYING'", cid)


def real_gate(port, sink=None):
    return DispatchGate(port, sink or RealSink(), RealSigner(), RealVerifier(), real_checkpoint_sink=True)


async def refused(coro, code):
    with pytest.raises(LedgerError) as e:
        await coro
    assert e.value.code == code, e.value.code
    return e.value


# ============================================================================ port matches the migrations
async def test_spec_matches_pg_proc_signatures_and_grants(env):
    conn, _ = env
    for key, fn in SPEC.items():
        rows = await conn.fetch(
            "SELECT p.oid, p.proargtypes::oid[] AS args, p.prorettype::regtype::text AS ret "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname='change_ledger' AND p.proname=$1 AND p.pronargs=$2", fn.name, 2 + len(fn.params))
        assert len(rows) == 1, (key, "exactly one overload with this arity")
        r = rows[0]
        types = [await conn.fetchval("SELECT $1::oid::regtype::text", a) for a in r["args"]]
        want = ["text", "text"] + [REGTYPE.get(p, p) for p in fn.params]
        assert types == want, (key, types, want)
        assert r["ret"] == fn.ret, (key, r["ret"])
        granted = {c for c in CLASSES if await conn.fetchval(
            "SELECT has_function_privilege($1, $2::oid, 'EXECUTE')", GROUP[c], r["oid"])}
        assert granted == set(fn.classes), (key, granted)


async def test_raw_functions_are_revoked_and_the_port_has_no_method_for_them(env):
    conn, port = env
    rows = await conn.fetch("SELECT p.oid, p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                            "WHERE n.nspname='change_ledger' AND p.proname = ANY($1::text[])", list(RAW_REVOKED))
    assert {r["proname"] for r in rows} == set(RAW_REVOKED)
    for r in rows:
        for cls in CLASSES:
            assert not await conn.fetchval("SELECT has_function_privilege($1, $2::oid, 'EXECUTE')",
                                           GROUP[cls], r["oid"]), (r["proname"], cls)
    for name in RAW_REVOKED:
        assert name not in SPEC and not hasattr(port, name), name
    # the raw call is refused by SQL under every actor even when issued around the port
    for cls, role in ACTORS.items():
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(f'SET LOCAL ROLE "{role}"')
                await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
                await conn.fetchval("SELECT change_ledger.complete($1,$2,$3,1,'UNKNOWN','{}'::jsonb,NULL)",
                                    T, C, uuid.uuid4())


def test_every_spec_entry_has_a_method_and_error_mapping():
    port_methods = {n for n, _ in inspect.getmembers(SqlChangeLedger, inspect.iscoroutinefunction)}
    missing = [k for k in SPEC if k not in port_methods and k != "recover_sweep_params"]
    assert not missing, missing
    assert code_from_message("APPROVAL_EXPIRED") == "APPROVAL_EXPIRED"
    assert code_from_message("BASE_HOLD: detail") == "BASE_HOLD"
    assert code_from_message("permission denied for function x", "42501") == "NOT_ENTITLED"
    assert code_from_message("weird text", "XX000") == "SQL_XX000"


# ============================================================================ the happy journey and the gate
async def test_journey_propose_to_dispatch_through_the_permit_gate(env):
    conn, port = env
    cid, gen, call_id = await applying(port)
    # no checkpoint at all: SQL refuses, the port maps the code
    await refused(port.issue_permit(SCOPE, cid, gen), "CHECKPOINT_UNAVAILABLE")
    # a TEST checkpoint (recorded directly) never satisfies the permit rule
    head = await port.ledger_head(SCOPE)
    assert head["seq"] >= await apply_seq(conn, cid)
    await signed_checkpoint(port, head["seq"], head["head_hash"], "TEST", "mem")
    await refused(port.issue_permit(SCOPE, cid, gen), "CHECKPOINT_UNAVAILABLE")
    # a checkpoint that was not read back is refused at record time
    await refused(signed_checkpoint(port, head["seq"], head["head_hash"], "REAL", "s", read_back=False),
                  "CHECKPOINT_UNAVAILABLE")
    # 007: a wrong signature, an unregistered key and a non-checkpoint caller are refused at record time
    await refused(signed_checkpoint(port, head["seq"], head["head_hash"], signature="0" * 64),
                  "CHECKPOINT_UNAVAILABLE")
    await refused(signed_checkpoint(port, head["seq"], head["head_hash"], key_id="no-such-key"),
                  "CHECKPOINT_UNAVAILABLE")
    with pytest.raises(ValueError):  # the worker class is not granted record_checkpoint any more
        await signed_checkpoint(port, head["seq"], head["head_hash"], as_class="worker")
    impostor = SqlChangeLedger(conn, {"checkpoint": "clt_wrk"})
    await refused(impostor.record_checkpoint(SCOPE, head["seq"], head["head_hash"], "REAL", "s", CHK_KEY_ID,
                                             "0" * 64, datetime.now(UTC), True), "NOT_ENTITLED")
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.checkpoints") == 1  # only the TEST row
    # a REAL checkpoint with a head hash that is not the ledger event is recorded but cannot cover the head
    await signed_checkpoint(port, head["seq"], "f" * 64, "REAL", "s")
    await refused(port.issue_permit(SCOPE, cid, gen), "CHECKPOINT_UNAVAILABLE")
    assert await conn.fetchval("SELECT dispatch_state FROM change_ledger.records WHERE change_id=$1",
                               cid) == "NOT_PERMITTED"
    # the gate (real sink + real signer): write, read back, record, permit, sign
    sink = RealSink()
    permit = await real_gate(port, sink).issue_permit(SCOPE, cid, gen, await apply_seq(conn, cid))
    assert permit["change_id"] == str(cid) and permit["generation"] == gen
    assert permit["signature"] and permit["signer_key_id"] == CHK_KEY_ID
    assert permit["signature"] == RealSigner().sign(permit_signing_payload(permit["permit_digest"]))
    stored = await conn.fetchrow("SELECT state, signer_key_id, signature, permit_digest FROM "
                                 "change_ledger.dispatch_permits WHERE change_id=$1", cid)
    assert (stored["state"], stored["signer_key_id"], stored["signature"], stored["permit_digest"]) == (
        "PERMITTED", CHK_KEY_ID, permit["signature"], permit["permit_digest"])
    cp = await conn.fetchrow("SELECT sink_kind, read_back_confirmed, verified, written_by, ledger_seq FROM "
                             "change_ledger.checkpoints WHERE sink_id='ext-store-1'")
    assert (cp["sink_kind"], cp["read_back_confirmed"], cp["verified"], cp["written_by"]) == (
        "REAL", True, True, "clt_chk")
    assert cp["ledger_seq"] == head["seq"] or cp["ledger_seq"] >= await apply_seq(conn, cid)
    assert await conn.fetchval("SELECT checkpoint_seq FROM change_ledger.dispatch_permits WHERE change_id=$1",
                               cid) == permit["checkpoint_seq"]
    assert len(sink.rows) == 1
    # writer: fence check, dispatch CAS
    assert (await port.fence_check(SCOPE, cid, gen, call_id))["ok"] is True
    assert await port.record_call(SCOPE, cid, gen, call_id) is True
    assert await conn.fetchval("SELECT dispatch_state FROM change_ledger.records WHERE change_id=$1",
                               cid) == "DISPATCHED"
    # the whole chain verifies for auditor and the head moved
    assert (await port.verify_chain(SCOPE, as_class="auditor"))["ok"] is True
    assert (await port.ledger_head(SCOPE, as_class="auditor"))["seq"] > head["seq"]


async def test_unknown_outcome_then_operator_resolve_is_refused_without_proof(env):
    conn, port = env
    cid, gen, call_id = await applying(port)
    await real_gate(port).issue_permit(SCOPE, cid, gen)
    assert await port.record_call(SCOPE, cid, gen, call_id) is True
    # UNKNOWN needs no proof (complete_signed, no completion record) but opens a CALL_OWNERSHIP hold
    assert await port.complete_signed(SCOPE, cid, gen, "UNKNOWN", None) == "APPLY_UNKNOWN"
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.holds WHERE change_id=$1 AND "
                               "cause='CALL_OWNERSHIP' AND released_at IS NULL", cid) == 1
    # a replayed completion is idempotent; a wrong generation is superseded
    assert await port.complete_signed(SCOPE, cid, gen, "UNKNOWN", None) == "APPLY_UNKNOWN"
    await refused(port.complete_signed(SCOPE, cid, gen + 1, "UNKNOWN", None), "TICKET_SUPERSEDED")
    # an effect found never becomes APPLIED here: it goes to triage (the verdict is the signed observation)
    seen = await evidence(conn, port, cid, "OBSERVATION", {"effect_present": True})
    await refused(port.resolve_unknown_signed(SCOPE, cid, seen, None, False, True), "DIGEST_MISMATCH")
    assert await port.resolve_unknown_signed(SCOPE, cid, seen, None, True, True) == "TRIAGE_REQUIRED"
    # operator_resolve without a witness cosign carrying a completion proof is refused, state unchanged
    await refused(port.operator_resolve(SCOPE, cid, None, False, False), "COMPLETION_PROOF_MISSING")
    await refused(port.operator_resolve(SCOPE, cid, uuid.uuid4(), False, False), "COMPLETION_PROOF_MISSING")
    assert await conn.fetchval("SELECT execution_state FROM change_ledger.records WHERE change_id=$1",
                               cid) == "TRIAGE_REQUIRED"
    # a hold of CALL_OWNERSHIP cannot be released by hand either
    hold = await conn.fetchval("SELECT hold_id FROM change_ledger.holds WHERE change_id=$1", cid)
    await refused(port.release_hold(SCOPE, hold, {"x": 1}), "COMPLETION_PROOF_MISSING")


async def test_absent_resolution_needs_a_proof_class(env):
    conn, port = env
    cid, gen, call_id = await applying(port)
    await real_gate(port).issue_permit(SCOPE, cid, gen)
    await port.record_call(SCOPE, cid, gen, call_id)
    await port.complete_signed(SCOPE, cid, gen, "UNKNOWN", None)
    absent = await evidence(conn, port, cid, "OBSERVATION", {"effect_present": False})
    await refused(port.resolve_unknown_signed(SCOPE, cid, absent, None, False), "COMPLETION_PROOF_MISSING")
    proof = await evidence(conn, port, cid, "COMPLETION_PROOF", {"class": "b", "result_returned": False})
    assert await port.resolve_unknown_signed(SCOPE, cid, absent, proof, False) == "FAILED_APPLY"


async def test_signed_completion_and_verification_through_the_port(env):
    conn, port = env
    cid, gen, call_id = await applying(port)
    await real_gate(port).issue_permit(SCOPE, cid, gen)
    assert await port.record_call(SCOPE, cid, gen, call_id) is True
    # a completion needs the writer's own signed class-a record of this call; no record -> refused
    await refused(port.complete_signed(SCOPE, cid, gen, "SUCCESS", None), "EVIDENCE_UNSIGNED")
    done = await evidence(conn, port, cid, "COMPLETION_PROOF", {"class": "a", "result_returned": True},
                          actor="writer")
    assert await port.complete_signed(SCOPE, cid, gen, "SUCCESS", done) == "APPLIED"
    # verification verdict is derived from three signed typed records, never from a caller flag
    ids = [await evidence(conn, port, cid, k, {"matches": True}) for k in ("FIELD", "MOVEMENT", "VERSION")]
    assert await port.verify_signed(SCOPE, cid, *ids) == "VERIFIED"
    assert await conn.fetchval("SELECT verification_state FROM change_ledger.records WHERE change_id=$1",
                               cid) == "VERIFIED"
    assert (await port.read_status(SCOPE, cid, as_class="auditor"))["verification"] == "VERIFIED"
    assert (await port.verify_chain(SCOPE, as_class="auditor"))["ok"] is True


async def test_approve_compares_the_sql_computed_digest(env):
    conn, port = env
    cid = uuid.uuid4()
    await port.propose(SCOPE, cid, "CREATE_DRAFT", BASE, ORG, "clt_alice", uuid.uuid4().hex, DIGEST, "doc1", "v1",
                       None, exp())
    await declare_inputs(port, cid)
    await port.validate(SCOPE, cid)
    nonce = await port.issue_approval_nonce(SCOPE, cid)
    # the caller can no longer pick the digest: the requester's own payload digest is not the approval digest
    await refused(port.approve(SCOPE, cid, nonce, DIGEST), "DIGEST_MISMATCH")
    status = await port.read_status(SCOPE, cid, as_class="approver")
    assert status["approval_digest"] and status["approved_digest"] is None
    assert isinstance(await port.approve(SCOPE, cid, nonce, status["approval_digest"]), uuid.UUID)
    # 007 A2 / 008 B6b: an already approved change may get a nonce (so that the approver can still reject it), but
    # it can never be approved again with it
    again = await port.issue_approval_nonce(SCOPE, cid)
    await refused(port.approve(SCOPE, cid, again, status["approval_digest"]), "FORBIDDEN_TRANSITION")


# ============================================================================ gate consistency with SQL
async def test_gate_stays_disabled_unless_real_sink_and_non_test_signer(env):
    conn, port = env
    cid, gen, _ = await applying(port)
    cases = [
        DispatchGate(port, RealSink(), RealSigner(), RealVerifier()),                          # flag off
        DispatchGate(port, InMemoryCheckpointSink(), RealSigner(), RealVerifier(),
                     real_checkpoint_sink=True),                                                # TEST sink
        DispatchGate(port, RealSink(), FakeSigner(), RealVerifier(), real_checkpoint_sink=True),
        DispatchGate(port, RealSink(), RealSigner(), FakeVerifier(), real_checkpoint_sink=True),
        DispatchGate(port, RealSink(), RealSigner(), UnwiredVerifier(), real_checkpoint_sink=False),
    ]
    for gate in cases:
        assert gate.enabled is False
        with pytest.raises(GateDisabled):
            await gate.issue_permit(SCOPE, cid, gen, 1)
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.checkpoints") == 0
    assert await conn.fetchval("SELECT dispatch_state FROM change_ledger.records WHERE change_id=$1",
                               cid) == "NOT_PERMITTED"
    assert real_gate(port).enabled is True


async def test_gate_refuses_when_read_back_does_not_match_and_writes_no_checkpoint(env):
    conn, port = env
    cid, gen, _ = await applying(port)

    class LyingSink(RealSink):
        async def read_back(self, scope, seq):
            rec = await super().read_back(scope, seq)
            return CheckpointRecord(**{**rec.__dict__, "head_hash": "0" * 64})

    with pytest.raises(CheckpointUnavailable):
        await real_gate(port, LyingSink()).issue_permit(SCOPE, cid, gen)
    # the Unwired verifier (no Ed25519 yet) fails closed as well
    with pytest.raises(CheckpointUnavailable):
        await DispatchGate(port, RealSink(), RealSigner(), UnwiredVerifier(),
                           real_checkpoint_sink=True).issue_permit(SCOPE, cid, gen)
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.checkpoints") == 0


async def test_gate_maps_a_sql_refusal_after_the_checkpoint(env):
    conn, port = env
    cid, gen, _ = await applying(port)
    await port.kill_switch(SCOPE, "STOP_ADMIT")
    with pytest.raises(PermitRefused) as e:
        await real_gate(port).issue_permit(SCOPE, cid, gen)
    assert e.value.code == "KILL_SWITCH_ACTIVE" or e.value.code.startswith("KILL")
    assert await port.kill_switch(SCOPE, "OFF") == "OFF"


def test_evidence_binding_mirrors_sql_formula():
    at = datetime(2026, 10, 12, 12, 0, 0, 123456, tzinfo=UTC)
    cid = uuid.UUID(int=7)
    call = uuid.UUID(int=9)
    want = hashlib.sha256(f"{cid}:FIELD:{'a' * 64}:2026-10-12T12:00:00.123456Z:3:{call}".encode()).hexdigest()
    assert evidence_binding(str(cid), "FIELD", "a" * 64, at, 3, call) == want
    none = hashlib.sha256(f"{cid}:AUTH_RECEIPT:{'a' * 64}:2026-10-12T12:00:00.123456Z::".encode()).hexdigest()
    assert evidence_binding(str(cid), "AUTH_RECEIPT", "a" * 64, at) == none


async def test_evidence_binding_equals_sql_function(env):
    conn, _ = env
    at = datetime(2026, 10, 12, 12, 0, 0, 123456, tzinfo=UTC)
    cid = uuid.uuid4()
    call = uuid.uuid4()
    sql = await conn.fetchval("SELECT change_ledger.evidence_binding($1,'FIELD',$2,$3,$4,$5)", cid, "a" * 64, at,
                              3, call)
    assert sql == evidence_binding(str(cid), "FIELD", "a" * 64, at, 3, call)
    sql = await conn.fetchval("SELECT change_ledger.evidence_binding($1,'AUTH_RECEIPT',$2,$3,NULL,NULL)", cid,
                              "a" * 64, at)
    assert sql == evidence_binding(str(cid), "AUTH_RECEIPT", "a" * 64, at)


# ============================================================================ roles and scope through the port
async def test_caller_class_and_scope_errors_are_mapped(env):
    conn, port = env
    cid = uuid.uuid4()
    await port.propose(SCOPE, cid, "CREATE_DRAFT", BASE, ORG, "clt_alice", "r1", DIGEST, "d", "v1", None,
                       exp())
    # the requester role is not granted approve: privilege error -> NOT_ENTITLED
    wrong = SqlChangeLedger(conn, {"approver": "clt_alice"})
    await refused(wrong.approve(SCOPE, cid, "n", DIGEST), "NOT_ENTITLED")
    # a class that the function is not granted to is rejected before any SQL
    with pytest.raises(ValueError):
        await port.invoke("approve", SCOPE, cid, "n", DIGEST, as_class="writer")
    with pytest.raises(ValueError):
        SqlChangeLedger(conn, {"nobody": "x"})
    with pytest.raises(ValueError):
        SqlChangeLedger(conn, {"worker": 'x"; drop'})
    # a scope the actor was not granted
    await refused(port.validate(Scope("T2", "C2"), cid), "SCOPE_NOT_GRANTED")
    # a foreign identity argument
    await refused(port.propose(SCOPE, uuid.uuid4(), "CREATE_DRAFT", BASE, ORG, "clt_mallory", "r2", DIGEST,
                               "d", "v1", None, exp()), "NOT_ENTITLED")
    # a naive timestamp never reaches SQL
    with pytest.raises(ValueError):
        await port.propose(SCOPE, uuid.uuid4(), "CREATE_DRAFT", BASE, ORG, "clt_alice", "r3", DIGEST, "d",
                           "v1", None, datetime.now())
    # a rolled-back call leaves the connection usable and no partial rows
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.records") == 1
    assert (await port.verify_chain(SCOPE))["ok"] is True
    assert (await port.read_status(SCOPE, cid))["lifecycle"] == "PROPOSED"


async def test_concurrent_port_calls_keep_one_chain(env):
    conn, port = env
    dsn = require_dsn()
    from _pg_harness import admin_connect
    extra = [await admin_connect(dsn, database=await conn.fetchval("SELECT current_database()"))
             for _ in range(3)]
    try:
        ports = [SqlChangeLedger(c, ACTORS) for c in extra]
        async def work(i, p):
            for j in range(4):  # one connection runs one call at a time
                await p.propose(SCOPE, uuid.uuid4(), "CREATE_DRAFT", BASE, ORG, "clt_alice", f"c{i}-{j}",
                                DIGEST, f"d{i}{j}", "v1", None, exp())
        await asyncio.gather(*[work(i, p) for i, p in enumerate(ports)])
    finally:
        for c in extra:
            await c.close()
    assert await port.verify_chain(SCOPE) == {"ok": True, "count": 12, "bad_seq": None}


# ============================================================================ the non-operational write port
async def test_write_port_is_not_wired():
    port = NonOperationalWritePort()
    ticket = ApplyTicket("c", 1, "call", "POST", T, C, ORG, BASE, "doc1", "v1", "d" * 64)
    permit = DispatchPermit("p", "d", "c", 1, "call", datetime.now(UTC), 1, "k", "s")
    calls = [port.verify_ticket(ticket), port.verify_permit(ticket, permit), port.authenticate_base(ticket),
             port.create_draft(ticket, permit, {}), port.update_draft(ticket, permit, {}),
             port.post(ticket, permit), port.unpost(ticket, permit)]
    for coro in calls:
        with pytest.raises(NotWired, match="WRITE_PORT_NOT_WIRED"):
            await coro
