"""Combined-path PostgreSQL tests (GPT-PM limit R-04): exact canonical wire bytes -> ReferenceWriter ->
SimulatedOneC.apply() -> clone-signed receipt -> change_ledger.record_dispatch_receipt (016-018) -> completion gate.

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database with all migrations (001-018) applied and its own
fresh SimulatedOneC (same label, hence the same receipt key, registered in the ledger as 'receipt_role').
"""
import asyncio
import hashlib
import json
import uuid
from contextlib import nullcontext
from dataclasses import replace
from unittest import mock

import _approval_envelope
import asyncpg
import pytest
from _pg_harness import fails, require_dsn, throwaway_db
from test_change_ledger_sql import C, C2, DEFAULT_GRANT, ORG, T, T2, _setup, exp

from business_ai_gateway.phase2.change import canonical_json
from business_ai_gateway.phase2.change.proposal import DuplicateOverride, payload_digest, payload_to_dict
from business_ai_gateway.phase2.change.types import ChangeKind
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger
from business_ai_gateway.phase2.simulation.clone_1c import SimulatedOneC, encode_payload
from business_ai_gateway.phase2.simulation.reference_writer import ReferenceWriter, WriteStatus
from business_ai_gateway.phase2.simulation.synthetic_dispatch import SyntheticDispatchCoordinator
from business_ai_gateway.phase2.simulation.synthetic_data import SyntheticGenerator

pytestmark = pytest.mark.integration

KEY = "vk-clone"
LABEL = "SIM-CLONE-E2E"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Env:
    def __init__(self, led, clone, writer, gen):
        self.led, self.clone, self.writer, self.gen = led, clone, writer, gen
        self.n = 0

    def base(self):
        self.n += 1
        return f"base-{self.n}"


@pytest.fixture
async def env():
    from test_change_ledger_sql import L
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        clone = SimulatedOneC(LABEL)
        for t, c, kid in ((T, C, KEY), (T2, C2, "vk-clone-t2")):
            await db.conn.execute(
                "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
                "VALUES($1,$2,$3,'receipt_role',$4)", t, c, kid, clone.receipt_public_key_hex)
        yield Env(L(db), clone, ReferenceWriter(clone), SyntheticGenerator(seed=20261016))


# ------------------------------------------------------------------------------------------------ helpers
def patched_envelope(payload):
    """The 009 approval text embeds `payload`; the shared fixture helper defaults to FIXTURE_PAYLOAD, so patch it."""
    if payload is None:
        return nullcontext()
    return mock.patch.object(_approval_envelope, "FIXTURE_PAYLOAD", payload_to_dict(payload))


async def permitted(e, kind, payload, *, target, base=None, **kw):
    """A PERMITTED ledger change whose approved payload digest is the 009 digest of the SYNTHETIC payload."""
    with patched_envelope(payload):
        cid, tok, call_id, _ = await e.led.permitted(
            kind=kind.value, digest=payload_digest(payload, "v1"), target=target, base=base or e.base(), **kw)
    return cid, tok["generation"], call_id


def verify_text(payload):
    return None if payload is None else canonical_json(payload_to_dict(payload))


async def dispatch(e, cid, gen, call_id, kind, payload, target_ref, expected_version, *, require=True, wire=None,
                   verified_payload=...):
    """Ledger side (marker, payload verification, DISPATCHED) then the writer sends the bytes. Returns the WriteOutcome."""
    data = encode_payload(payload) if wire is None else wire
    if require:
        await e.led.call("clt_wri", "require_dispatch_receipt", cid, gen)
    vp = payload if verified_payload is ... else verified_payload
    await e.led.call("clt_wri", "verify_dispatch_payload", cid, gen, verify_text(vp))
    assert await e.led.call("clt_wri", "record_call", cid, gen, call_id) is True
    return e.writer.write(str(cid), gen, kind, data, sha(data), target_ref, expected_version, dispatch_id=str(call_id))


def ledger_receipt(clone, cid, call_id, ledger_digest, version):
    """A receipt signed by the CLONE'S OWN key over the ledger-form digest (see the module docstring)."""
    return clone._sign_receipt(str(cid), str(call_id), ledger_digest, version)


async def put(e, cid, gen, rc, key=KEY, role="clt_wri", t=T, c=C):
    return await e.led.call(role, "record_dispatch_receipt", cid, gen, key, rc["received_payload_sha256"],
                            rc["new_version"], rc["signature"], t=t, c=c)


async def n_receipts(e, cid):
    return await e.led.conn.fetchval("SELECT count(*) FROM change_ledger.dispatch_receipts WHERE change_id=$1", cid)


async def approved_digest(e, cid):
    return (await e.led.rec(cid))["payload_digest"]


async def seed_doc(e, payload=None):
    """A document that already exists on the clone (created outside the ledger under test); returns (ref, version)."""
    payload = payload or e.gen.draft_payload()
    data = encode_payload(payload)
    out = e.writer.write(f"seed-{uuid.uuid4().hex[:8]}", 1, ChangeKind.CREATE_DRAFT, data, sha(data), None, None)
    assert out.success
    return e.clone.target_refs()[-1], out.new_version, payload


async def full_success(e, kind, payload, target_ref, expected_version, *, target=None, **permit_args):
    """One change through the whole combined path; returns (cid, outcome, receipt row)."""
    cid, gen, call_id = await permitted(e, kind, payload, target=target or target_ref or f"doc-{uuid.uuid4().hex[:6]}",
                                        **permit_args)
    out = await dispatch(e, cid, gen, call_id, kind, payload, target_ref, expected_version)
    assert out.success and out.status is WriteStatus.APPLIED_VERIFIED, (out.status, out.code)
    assert out.received_payload_sha256 == sha(encode_payload(payload))          # real wire bytes
    rc = out.receipt
    assert rc is not None and rc["received_payload_sha256"] == sha(encode_payload(payload))
    rid = await put(e, cid, gen, rc)
    assert rid is not None and await n_receipts(e, cid) == 1
    assert await e.led.complete(cid, gen, "SUCCESS") == "APPLIED"
    return cid, out, rid


# ======================================================================== (0) exact bytes are bound end to end
async def test_real_wire_receipt_is_accepted_and_bound_to_canonical_bytes(env):
    e = env
    p = e.gen.draft_payload()
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, p, target="doc-gap")
    out = await dispatch(e, cid, gen, call_id, ChangeKind.CREATE_DRAFT, p, None, None)
    assert out.success and out.receipt is not None
    data = encode_payload(p)
    assert data == canonical_json(payload_to_dict(p)).encode("utf-8")
    assert out.receipt["received_payload_sha256"] == sha(data)
    assert out.receipt["change_id"] == str(cid) and out.receipt["dispatch_id"] == str(call_id)
    row = await e.led.conn.fetchrow(
        "SELECT payload_digest,wire_payload_sha256 FROM change_ledger.change_dispatch_verifications "
        "WHERE change_id=$1 AND generation=$2", cid, gen)
    assert row["payload_digest"] == await approved_digest(e, cid)  # typed approval digest remains independent
    assert row["wire_payload_sha256"] == sha(data) != row["payload_digest"]
    rid = await put(e, cid, gen, out.receipt)
    assert rid is not None and await n_receipts(e, cid) == 1
    assert await put(e, cid, gen, out.receipt) == rid  # exact clone receipt replay is idempotent
    assert await e.led.complete(cid, gen, "SUCCESS") == "APPLIED"


async def test_coordinator_persists_verified_sql_receipt_and_completes(env):
    """Exercise the production SQL wrapper methods through the synthetic coordinator."""
    e = env
    payload = e.gen.draft_payload()
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, payload, target="doc-coordinator")
    # The legacy helper above registers the key alias used by `put`; the coordinator correctly
    # forwards the clone's signed key ID, which must also exist in the SQL verifier registry.
    await e.led.conn.execute(
        "INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
        "VALUES($1,$2,$3,'receipt_role',$4)", T, C, e.clone.receipt_key_id, e.clone.receipt_public_key_hex)
    sql_ledger = SqlChangeLedger(e.led.conn, {"writer": "clt_wri"})
    coordinator = SyntheticDispatchCoordinator(sql_ledger, e.writer)

    out = await coordinator.dispatch(Scope(T, C), cid, gen, call_id, ChangeKind.CREATE_DRAFT,
                                     payload, None, None)

    assert out.status is WriteStatus.APPLIED_VERIFIED and out.receipt is not None
    row = await e.led.conn.fetchrow(
        "SELECT signer_key_id,received_payload_sha256,new_version FROM change_ledger.dispatch_receipts "
        "WHERE change_id=$1 AND generation=$2", cid, gen)
    assert row is not None
    assert row["signer_key_id"] == e.clone.receipt_key_id
    assert row["received_payload_sha256"] == sha(encode_payload(payload))
    assert row["new_version"] == out.new_version
    assert await n_receipts(e, cid) == 1
    assert e.clone.write_count == 1 and len(e.clone.truth_log()) == 1
    assert await e.led.complete(cid, gen, "SUCCESS") == "APPLIED"
    assert (await e.led.rec(cid))["execution_state"] == "APPLIED"


@pytest.mark.parametrize("failure", ["crash_before_write", "crash_after_write"])
async def test_coordinator_unknown_outcome_does_not_persist_retry_or_complete(env, failure):
    """Unknown writer outcomes stop at dispatch; recovery/completion remains a separate decision."""
    e = env
    payload = e.gen.draft_payload()
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, payload, target=f"doc-{failure}")
    sql_ledger = SqlChangeLedger(e.led.conn, {"writer": "clt_wri"})
    coordinator = SyntheticDispatchCoordinator(sql_ledger, e.writer)
    e.clone.fail_next(failure)

    out = await coordinator.dispatch(Scope(T, C), cid, gen, call_id, ChangeKind.CREATE_DRAFT,
                                     payload, None, None)

    assert out.status is WriteStatus.UNKNOWN_CRASH and out.receipt is None
    assert await n_receipts(e, cid) == 0
    assert (await e.led.rec(cid))["execution_state"] == "APPLYING"
    assert e.clone.truth_log()[-1]["outcome"] == failure.upper()
    assert len(e.clone.truth_log()) == 1  # one writer attempt; coordinator issued no retry


async def test_noncanonical_wire_encoding_cannot_satisfy_the_canonical_receipt_gate(env):
    e = env
    p = e.gen.draft_payload()
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, p, target="doc-wire-encoding")
    alternate = json.dumps(payload_to_dict(p), ensure_ascii=False, indent=2).encode("utf-8")
    canonical = encode_payload(p)
    assert alternate != canonical and json.loads(alternate) == json.loads(canonical)
    out = await dispatch(e, cid, gen, call_id, ChangeKind.CREATE_DRAFT, p, None, None, wire=alternate)
    assert out.success and out.receipt is not None  # clone applied and signed the exact bytes it received
    assert out.receipt["received_payload_sha256"] == sha(alternate)
    verified = await e.led.conn.fetchval(
        "SELECT wire_payload_sha256 FROM change_ledger.change_dispatch_verifications "
        "WHERE change_id=$1 AND generation=$2", cid, gen)
    assert verified == sha(canonical) and verified != out.receipt["received_payload_sha256"]
    await fails("DIGEST_MISMATCH", put(e, cid, gen, out.receipt))
    await fails("EVIDENCE_UNSIGNED", e.led.complete(cid, gen, "SUCCESS"))
    assert (await e.led.rec(cid))["execution_state"] == "APPLYING"
    assert await n_receipts(e, cid) == 0


# ======================================================================== (1) four kinds, receipt, completion
async def test_all_four_operation_kinds_through_writer_receipt_and_ledger_completion(env):
    e = env
    p = e.gen.draft_payload()
    cid1, out1, rid1 = await full_success(e, ChangeKind.CREATE_DRAFT, p, None, None, target="doc-new")
    ref = e.clone.target_refs()[0]
    assert out1.new_version == "V1" and e.clone.read_state(ref)["status"] == "DRAFT"

    upd = replace(e.gen.draft_payload(lines=2, counterparty_ref=p.counterparty_ref), expected_target_version="V1")
    cid2, out2, _ = await full_success(e, ChangeKind.UPDATE_DRAFT, upd, ref, "V1")
    assert out2.new_version == "V2" and len(e.clone.read_state(ref)["payload"]["lines"]) == 2

    cid3, out3, _ = await full_success(e, ChangeKind.POST, None, ref, "V2")
    st = e.clone.read_state(ref)
    assert out3.new_version == "V3" and st["status"] == "POSTED" and st["movements"]

    cid4, out4, _ = await full_success(e, ChangeKind.UNPOST, None, ref, "V3")
    st = e.clone.read_state(ref)
    assert out4.new_version == "V4" and st["status"] == "DRAFT" and st["movements"] == {}

    assert e.clone.write_count == 4 and [x["write_applied"] for x in e.clone.truth_log()] == [True] * 4
    for cid in (cid1, cid2, cid3, cid4):
        row = await e.led.conn.fetchrow("SELECT * FROM change_ledger.dispatch_receipts WHERE change_id=$1", cid)
        assert row["signer_key_id"] == KEY and (await e.led.rec(cid))["execution_state"] == "APPLIED"
        assert await e.led.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 AND event_type='DISPATCH_RECEIPT_RECORDED'",
            cid) == 1
    assert (await e.led.call("clt_aud", "verify_chain"))["ok"] is True


# ======================================================================== (2) tampered bytes
async def test_clone_tamper_gives_no_matching_receipt_and_completion_is_refused(env):
    e = env
    p = e.gen.draft_payload()
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, p, target="doc-t1")
    e.clone.tamper()                                                       # bad transport: one byte flipped
    out = await dispatch(e, cid, gen, call_id, ChangeKind.CREATE_DRAFT, p, None, None)
    assert out.status is WriteStatus.TAMPER_DETECTED and out.received_payload_sha256 != out.approved_payload_sha256
    digest = await approved_digest(e, cid)
    # Exercise rejection of an arbitrary mismatching digest. This does not prove the ledger
    # rejects a receipt over the actual received wire bytes (the ledger uses the 009 payload digest).
    other = sha((digest + ":other-bytes").encode())
    await fails("DIGEST_MISMATCH", put(e, cid, gen, ledger_receipt(e.clone, cid, call_id, other, "V1")))
    # a receipt over the approved digest is only possible if the clone signed it; the writer cannot mint one
    forged = {**ledger_receipt(e.clone, cid, call_id, digest, "V1"), "signature": "0" * 128}
    await fails("EVIDENCE_UNSIGNED", put(e, cid, gen, forged))
    assert await n_receipts(e, cid) == 0
    await fails("EVIDENCE_UNSIGNED", e.led.complete(cid, gen, "SUCCESS"))
    assert (await e.led.rec(cid))["execution_state"] == "APPLYING"


async def test_writer_sending_different_bytes_is_caught_by_the_ledger(env):
    e = env
    p = e.gen.draft_payload()
    other = e.gen.draft_payload()
    assert payload_digest(other, "v1") != payload_digest(p, "v1")
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, p, target="doc-t2")
    # (a) asking the ledger to verify the substituted payload is refused before dispatch; permit stays PERMITTED
    await fails("DIGEST_MISMATCH", e.led.call("clt_wri", "verify_dispatch_payload", cid, gen, verify_text(other)))
    assert (await e.led.rec(cid))["dispatch_state"] != "DISPATCHED"
    # (b) a writer that verifies approved text but SENDS other bytes: the clone receipt binds those substituted bytes.
    out = await dispatch(e, cid, gen, call_id, ChangeKind.CREATE_DRAFT, p, None, None, wire=encode_payload(other))
    assert out.success                       # the writer only compares its own bytes with its own sha: it cannot know
    assert e.clone.truth_log()[-1]["received_payload_sha256"] == sha(encode_payload(other))
    # the clone signs what it received; the receipt is rejected against the ledger's canonical verified bytes.
    rc = out.receipt
    assert rc is not None and rc["received_payload_sha256"] == sha(encode_payload(other))
    await fails("DIGEST_MISMATCH", put(e, cid, gen, rc))
    await fails("EVIDENCE_UNSIGNED", e.led.complete(cid, gen, "SUCCESS"))
    assert await n_receipts(e, cid) == 0 and (await e.led.rec(cid))["execution_state"] == "APPLYING"


async def test_without_the_marker_tampered_dispatch_still_completes_named_limit(env):
    """016 NAMED LIMIT (opt-in marker): characterization of what is enforced, not an endorsement."""
    e = env
    p = e.gen.draft_payload()
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, p, target="doc-t3")
    e.clone.tamper()
    out = await dispatch(e, cid, gen, call_id, ChangeKind.CREATE_DRAFT, p, None, None, require=False)
    assert out.status is WriteStatus.TAMPER_DETECTED
    assert await e.led.complete(cid, gen, "SUCCESS") == "APPLIED" and await n_receipts(e, cid) == 0


# ======================================================================== (3) stale preview
async def test_stale_preview_is_refused_and_ledger_cannot_complete_it(env):
    e = env
    ref, v1, p0 = await seed_doc(e)
    upd = replace(e.gen.draft_payload(counterparty_ref=p0.counterparty_ref), expected_target_version=v1,
                  comment="based on V1")
    preview_v1 = e.clone.preview(ChangeKind.UPDATE_DRAFT, upd, ref).sha256
    cid, gen, call_id = await permitted(e, ChangeKind.UPDATE_DRAFT, upd, target=ref)
    # another change moves the target after the preview was taken
    moved = replace(e.gen.draft_payload(counterparty_ref=p0.counterparty_ref), expected_target_version=v1)
    data = encode_payload(moved)
    other = e.writer.write("other-change", 1, ChangeKind.UPDATE_DRAFT, data, sha(data), ref, v1)
    assert other.success and other.new_version == "V2"
    assert e.clone.preview(ChangeKind.UPDATE_DRAFT, upd, ref).sha256 != preview_v1          # the preview went stale
    writes_before = e.clone.write_count
    out = await dispatch(e, cid, gen, call_id, ChangeKind.UPDATE_DRAFT, upd, ref, v1)
    assert out.status is WriteStatus.REJECTED and out.code == "STALE_VERSION" and out.receipt is None
    assert e.clone.write_count == writes_before and e.clone.read_state(ref)["version"] == "V2"
    # the receipt of the other change cannot be replayed on this dispatch
    replay = ledger_receipt(e.clone, "other-change", "other-change:g1", await approved_digest(e, cid), "V2")
    await fails("EVIDENCE_UNSIGNED", put(e, cid, gen, replay))
    await fails("EVIDENCE_UNSIGNED", e.led.complete(cid, gen, "SUCCESS"))
    assert await n_receipts(e, cid) == 0 and (await e.led.rec(cid))["execution_state"] == "APPLYING"


# ======================================================================== (4) crash after write, recovery
async def test_crash_after_write_recovery_does_not_duplicate(env):
    e = env
    p = e.gen.draft_payload()
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, p, target="doc-c1")
    e.clone.fail_next("crash_after_write")
    out = await dispatch(e, cid, gen, call_id, ChangeKind.CREATE_DRAFT, p, None, None)
    assert out.status is WriteStatus.UNKNOWN_CRASH and out.receipt is None
    assert len(e.clone.target_refs()) == 1                                  # the write landed, the receipt was lost
    assert e.clone.truth_log()[-1]["outcome"] == "CRASH_AFTER_WRITE"
    assert await e.led.complete(cid, gen, "UNKNOWN") == "APPLY_UNKNOWN"
    # recovery by READS: the document is there, so the writer must not re-send; a blind retry is refused by the clone
    assert len(e.clone.find_duplicates(p)) == 1
    retry = e.writer.write(str(cid), gen + 1, ChangeKind.CREATE_DRAFT, encode_payload(p), sha(encode_payload(p)),
                           None, None, dispatch_id=str(uuid.uuid4()))
    assert retry.status is WriteStatus.REJECTED and retry.code == "DUPLICATE"
    assert len(e.clone.target_refs()) == 1 and e.clone.write_count == 1
    # ledger recovery: signed observation 'effect present', then triage
    assert await e.led.resolve_unknown(cid, True, attributed=True) == "TRIAGE_REQUIRED"
    assert await n_receipts(e, cid) == 0
    w = await e.led.cosign("clt_erin", cid, "a", attribution=True)
    # the receipt-required marker is still in force for this generation and no receipt can exist (the crash lost it):
    # the completion gate (trigger on records) refuses even the operator path to APPLIED.
    await fails("EVIDENCE_UNSIGNED", e.led.call("clt_dave", "operator_resolve", cid, w, True, True))
    assert (await e.led.rec(cid))["execution_state"] != "APPLIED" and len(e.clone.target_refs()) == 1


async def test_crash_before_write_recovery_proves_absence_without_retry(env):
    e = env
    p = e.gen.draft_payload()
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, p, target="doc-c0")
    e.clone.fail_next("crash_before_write")
    out = await dispatch(e, cid, gen, call_id, ChangeKind.CREATE_DRAFT, p, None, None)
    assert out.status is WriteStatus.UNKNOWN_CRASH and out.receipt is None
    assert e.clone.write_count == 0 and e.clone.target_refs() == ()
    assert e.clone.truth_log()[-1]["outcome"] == "CRASH_BEFORE_WRITE"
    assert await e.led.complete(cid, gen, "UNKNOWN") == "APPLY_UNKNOWN"
    # Only the signed observation plus independent completion proof resolves absence; no replay is needed.
    assert await e.led.resolve_unknown(cid, False, proof="b") == "FAILED_APPLY"
    assert e.clone.write_count == 0 and e.clone.target_refs() == ()
    assert (await e.led.rec(cid))["execution_state"] == "FAILED_APPLY"


async def test_repair_unposts_failed_post_and_verification_releases_halt(env):
    e = env
    base = "base-1"
    draft = e.gen.draft_payload()
    draft_id, _, _ = await full_success(e, ChangeKind.CREATE_DRAFT, draft, None, None, target="new-doc")
    ref = e.clone.target_refs()[0]
    assert await e.led.verify(draft_id, True) == "VERIFIED"

    post_id, _, _ = await full_success(e, ChangeKind.POST, None, ref, "V1", target=ref, base=base,
                                       parent=draft_id)
    assert e.clone.read_state(ref)["status"] == "POSTED"
    assert await e.led.verify(post_id, False) == "FAILED_VERIFY"
    assert await e.led.open_holds("FAILED_VERIFY_HALT") == 1

    repair_id, outcome, _ = await full_success(e, ChangeKind.UNPOST, None, ref, "V2", target=ref, base=base,
                                               parent=post_id, repair_for=post_id, approver="clt_carol")
    assert outcome.new_version == "V3" and e.clone.read_state(ref)["status"] == "DRAFT"
    assert await e.led.verify(repair_id, True) == "VERIFIED"
    assert await e.led.open_holds("FAILED_VERIFY_HALT") == 0
    assert await e.led.tl_owner(base, ref) is None


async def test_anchor_gap_after_restore_blocks_new_effects(env):
    e = env
    base = "base-1"
    await e.led.approved(request_id="anchor-before", base=base, target="anchor-doc")
    await e.led.checkpoint()
    earlier = await e.led.call("clt_chk", "ledger_head")
    await e.led.approved(request_id="anchor-after", base=base, target="anchor-doc-2")
    await e.led.checkpoint()
    anchored = await e.led.call("clt_chk", "ledger_head")
    assert anchored["seq"] > earlier["seq"]

    # Model loss of post-checkpoint history in this test's isolated database only.
    await e.led.conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable")
    try:
        await e.led.conn.execute("DELETE FROM change_ledger.events WHERE seq>$1", earlier["seq"])
    finally:
        await e.led.conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable")
    result = await e.led.call("clt_wrk", "check_anchor", anchored["seq"], anchored["head_hash"])
    assert result["ok"] is False and result["holds_opened"] > 0
    assert await e.led.open_holds("ANCHOR_GAP") == result["holds_opened"]
    # The anchor hold is an effect gate, not only an audit alert.
    blocked = await e.led.approved(request_id="blocked-after-gap", kind="CREATE_DRAFT", base=base,
                                   target="blocked-after-gap")
    await fails("BASE_HOLD", e.led.claimed(blocked, key="6" * 64))


# ======================================================================== (5) duplicate override
async def test_duplicate_override_path_end_to_end(env):
    e = env
    first_payload = e.gen.draft_payload()
    # the first document exists on the clone through its own change
    cid_a, _, _ = await full_success(e, ChangeKind.CREATE_DRAFT, first_payload, None, None, target="doc-a")
    first_ref = e.clone.target_refs()[0]
    twin = replace(e.gen.draft_payload(), counterparty_ref=first_payload.counterparty_ref,
                   supplier_document_number=first_payload.supplier_document_number,
                   supplier_document_date=first_payload.supplier_document_date)
    # clone side: a twin without override is refused
    data = encode_payload(twin)
    refused = e.writer.write("twin-plain", 1, ChangeKind.CREATE_DRAFT, data, sha(data), None, None)
    assert refused.status is WriteStatus.REJECTED and refused.code == "DUPLICATE" and len(e.clone.target_refs()) == 1
    # ledger side: the same business key twice parks the second change (no dispatch is possible for it)
    key = "7" * 64
    base = e.base()
    with patched_envelope(twin):
        a = await e.led.validated(base=base, target="doc-k1", key=key, digest=payload_digest(twin, "v1"))
        parked = await e.led.propose(base=base, target="doc-k2", key=key, digest=payload_digest(twin, "v1"))
    assert await e.led.call("clt_alice", "validate", parked) == "DUPLICATE_PARKED"
    # the override change: names the colliding change, approver-bound (carol), then dispatches with the override payload
    ovr = replace(twin, duplicate_override=DuplicateOverride(first_ref, "Synthetic justified duplicate"))
    odigest = payload_digest(ovr, "v1")
    o = await e.led.propose(base=base, target="doc-ovr", digest=odigest, budget=False)
    await e.led.call("clt_alice", "declare_business_key", o, key, str(a), "Synthetic justified duplicate")
    await e.led.call("clt_alice", "declare_target_class", o, "CLONE")
    await e.led.call("clt_alice", "declare_budget", o, DEFAULT_GRANT[(T, C)], "EUR", 0, False, False)
    assert await e.led.call("clt_alice", "validate", o) == "VALIDATED"
    ovr_digest = await e.led.conn.fetchval("SELECT override_digest FROM change_ledger.business_keys WHERE change_id=$1", o)
    assert await e.led.call("clt_carol", "bind_duplicate_override", o, ovr_digest) is True
    with patched_envelope(ovr):
        nonce = await e.led.call("clt_carol", "issue_approval_nonce", o)
        dg = await e.led.approval_digest(o)
    await e.led.call("clt_carol", "approve", o, nonce, dg)
    tok = await e.led.claimed(o)
    call_id = uuid.uuid4()
    await e.led.call("clt_alice", "begin_apply", tok["token_id"], call_id, "host-1", "sess-1")
    await e.led.checkpoint()
    await e.led.call("clt_wrk", "issue_permit", o, tok["generation"])
    out = await dispatch(e, o, tok["generation"], call_id, ChangeKind.CREATE_DRAFT, ovr, None, None)
    assert out.success and len(e.clone.target_refs()) == 2 and len(e.clone.find_duplicates(first_payload)) == 2
    rc = out.receipt
    assert rc is not None and rc["received_payload_sha256"] == sha(encode_payload(ovr))
    assert await put(e, o, tok["generation"], rc) is not None
    assert await e.led.complete(o, tok["generation"], "SUCCESS") == "APPLIED"


# ======================================================================== (6) kill switch
async def test_kill_switch_blocks_dispatch_so_nothing_is_written_and_resumes_after_off(env):
    e = env
    p = e.gen.draft_payload()
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, p, target="doc-k")
    await e.led.call("clt_wri", "require_dispatch_receipt", cid, gen)
    await e.led.call("clt_wri", "verify_dispatch_payload", cid, gen, verify_text(p))
    assert await e.led.call("clt_dave", "kill_switch", "STOP_EFFECTS") == "STOP_EFFECTS"
    await fails("KILL_SWITCH_ACTIVE", e.led.call("clt_wri", "record_call", cid, gen, call_id))
    assert (await e.led.rec(cid))["dispatch_state"] != "DISPATCHED"
    # the writer discipline is: no record_call, no write; nothing reached the clone
    assert e.clone.write_count == 0 and e.clone.truth_log() == () and e.clone.target_refs() == ()
    # a receipt for a dispatch that never happened cannot be recorded either
    rc = ledger_receipt(e.clone, cid, call_id, await approved_digest(e, cid), "V1")
    await fails("PERMIT_MISSING", put(e, cid, gen, rc))
    await e.led.call("clt_dave", "kill_switch", "OFF")
    # STOP_EFFECTS cancels the pending permit; resumption requires a fresh claim and permit.
    assert (await e.led.rec(cid))["dispatch_state"] == "CANCELLED_UNDISPATCHED"
    resumed, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, p, target="doc-k-resumed")
    data = encode_payload(p)
    out = await dispatch(e, resumed, gen, call_id, ChangeKind.CREATE_DRAFT, p, None, None)
    assert out.success
    assert out.receipt is not None and await put(e, resumed, gen, out.receipt) is not None
    assert await e.led.complete(resumed, gen, "SUCCESS") == "APPLIED"


# ======================================================================== (7) tenant isolation
async def test_second_tenant_cannot_record_a_receipt_for_the_first_tenants_dispatch(env):
    e = env
    p = e.gen.draft_payload()
    cid, gen, call_id = await permitted(e, ChangeKind.CREATE_DRAFT, p, target="doc-i")
    out = await dispatch(e, cid, gen, call_id, ChangeKind.CREATE_DRAFT, p, None, None)
    assert out.success
    rc = out.receipt
    assert rc is not None and rc["received_payload_sha256"] == sha(encode_payload(p))
    # tenant B's requester: addressing tenant A is outside its scope, addressing its own scope finds no such change
    with pytest.raises(asyncpg.PostgresError):
        await put(e, cid, gen, rc, role="clt_zed", t=T, c=C)
    await fails("CHANGE_NOT_FOUND", put(e, cid, gen, rc, role="clt_zed", t=T2, c=C2, key="vk-clone-t2"))
    # a receipt key registered only for tenant B is not a key of tenant A
    await fails("EVIDENCE_UNSIGNED", put(e, cid, gen, rc, key="vk-clone-t2"))
    assert await n_receipts(e, cid) == 0
    assert await put(e, cid, gen, rc) is not None                            # the legitimate writer of tenant A
    assert await e.led.conn.fetchval("SELECT tenant_id FROM change_ledger.dispatch_receipts WHERE change_id=$1", cid) == T


# ======================================================================== (8) two concurrent writers
async def test_two_concurrent_writers_on_the_same_change_only_one_dispatches_and_writes(env):
    e = env
    ref, v1, _ = await seed_doc(e)
    cid, gen, call_id = await permitted(e, ChangeKind.POST, None, target=ref)
    await e.led.call("clt_wri", "require_dispatch_receipt", cid, gen)
    conn2 = await e.led.db.connect()
    try:
        res = await asyncio.gather(
            e.led.call("clt_wri", "record_call", cid, gen, call_id),
            e.led.call("clt_wri", "record_call", cid, gen, call_id, conn=conn2), return_exceptions=True)
    finally:
        await conn2.close()
    wins = [r for r in res if r is True]
    assert len(wins) == 1, res
    assert all(r is True or isinstance(r, (asyncpg.PostgresError, bool)) for r in res), res
    assert await e.led.conn.fetchval("SELECT count(*) FROM change_ledger.dispatch_permits WHERE change_id=$1 "
                                     "AND generation=$2 AND state='DISPATCHED'", cid, gen) == 1
    # each writer only writes when ITS record_call won: exactly one POST reaches the clone
    writes_before = e.clone.write_count
    outs = [e.writer.write(str(cid), gen, ChangeKind.POST, b"{}", sha(b"{}"), ref, v1, dispatch_id=str(call_id))
            for r in res if r is True]
    assert len(outs) == 1 and outs[0].success and e.clone.write_count == writes_before + 1
    assert e.clone.read_state(ref)["status"] == "POSTED"
    rc = outs[0].receipt
    assert rc is not None and rc["received_payload_sha256"] == sha(b"{}")
    assert await put(e, cid, gen, rc) is not None
    assert await e.led.complete(cid, gen, "SUCCESS") == "APPLIED"
    assert await e.led.conn.fetchval("SELECT count(*) FROM change_ledger.dispatch_receipts WHERE change_id=$1", cid) == 1
