"""P5 offline end-to-end scenarios on synthetic data (no Postgres, no network, no real 1C)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from business_ai_gateway.phase2.change.proposal import DraftPayload, DuplicateOverride
from business_ai_gateway.phase2.change.types import ChangeKind
from business_ai_gateway.phase2.simulation.attestation import SimulatedAttestor
from business_ai_gateway.phase2.simulation.clone_1c import CloneRejected, SimulatedOneC, encode_payload
from business_ai_gateway.phase2.simulation.reference_writer import (
    ApprovedDigestMismatch, ReferenceWriter, WriteStatus)
from business_ai_gateway.phase2.simulation.synthetic_data import SyntheticGenerator, populate


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _send(writer: ReferenceWriter, kind: ChangeKind, payload: DraftPayload | None, target_ref: str | None = None,
          expected_version: str | None = None, change_id: str = "SIM-CHG-000001", generation: int = 1):
    data = encode_payload(payload)
    return writer.write(change_id, generation, kind, data, _sha(data), target_ref, expected_version)


def _classify_crash(clone: SimulatedOneC, refs_before: tuple[str, ...], target_ref: str | None,
                    state_before: dict | None) -> str:
    """Decide from READS ONLY (never truth_log) whether a crashed write landed: WRITE_LANDED or NO_WRITE."""
    if target_ref is None:
        return "WRITE_LANDED" if clone.target_refs() != refs_before else "NO_WRITE"
    return "WRITE_LANDED" if clone.read_state(target_ref) != state_before else "NO_WRITE"


@pytest.fixture()
def env():
    clone = SimulatedOneC("SIM-CLONE-P5")
    return clone, ReferenceWriter(clone, clone.receipt_public_key_hex), SyntheticGenerator(seed=20261015)


def test_all_four_operation_kinds_applied_with_verified_receipts(env):
    clone, writer, gen = env
    p = gen.draft_payload()
    created = _send(writer, ChangeKind.CREATE_DRAFT, p, generation=1)
    assert created.success and created.status is WriteStatus.APPLIED_VERIFIED and created.new_version == "V1"
    ref = clone.target_refs()[0]
    assert clone.read_state(ref)["status"] == "DRAFT"

    upd = replace(gen.draft_payload(lines=2, counterparty_ref=p.counterparty_ref), expected_target_version="V1")
    updated = _send(writer, ChangeKind.UPDATE_DRAFT, upd, ref, "V1", generation=2)
    assert updated.success and updated.new_version == "V2"
    assert len(clone.read_state(ref)["payload"]["lines"]) == 2

    posted = _send(writer, ChangeKind.POST, None, ref, "V2", generation=3)
    assert posted.success and posted.new_version == "V3"
    state = clone.read_state(ref)
    assert state["status"] == "POSTED" and state["movements"] and all(v == 2 for v in state["movements"].values())

    unposted = _send(writer, ChangeKind.UNPOST, None, ref, "V3", generation=4)
    assert unposted.success and unposted.new_version == "V4"
    state = clone.read_state(ref)
    assert state["status"] == "DRAFT" and state["movements"] == {}

    for out, gen_no in ((created, 1), (updated, 2), (posted, 3), (unposted, 4)):
        assert out.receipt["change_id"] == "SIM-CHG-000001"
        assert out.receipt["dispatch_id"] == f"{out.receipt['change_id']}:g{gen_no}"
        assert out.received_payload_sha256 == out.approved_payload_sha256
    assert clone.write_count == 4
    assert [e["write_applied"] for e in clone.truth_log()] == [True] * 4


def test_pre_send_digest_mismatch_sends_nothing(env):
    clone, writer, gen = env
    data = encode_payload(gen.draft_payload())
    with pytest.raises(ApprovedDigestMismatch):
        writer.write("SIM-CHG-000001", 1, ChangeKind.CREATE_DRAFT, data, "0" * 64, None, None)
    assert clone.truth_log() == () and clone.write_count == 0


def test_timeout_then_repair_via_state_read_then_retry_without_duplicate(env):
    clone, writer, gen = env
    populate(clone, gen, 1)
    ref = clone.target_refs()[0]
    before = clone.read_state(ref)
    digest_before = clone.observed_state_digest(ref)
    upd = replace(gen.draft_payload(counterparty_ref=before["payload"]["counterparty_ref"]),
                  expected_target_version="V1")

    clone.fail_next("timeout")
    out = _send(writer, ChangeKind.UPDATE_DRAFT, upd, ref, "V1")
    assert out.status is WriteStatus.UNKNOWN_TIMEOUT and not out.success
    # repair: observe the target; unchanged digest and version prove nothing landed
    assert clone.observed_state_digest(ref) == digest_before
    assert clone.read_state(ref)["version"] == "V1"
    retry = _send(writer, ChangeKind.UPDATE_DRAFT, upd, ref, "V1")
    assert retry.success and retry.new_version == "V2"
    assert clone.write_count == 2  # populate create + exactly one update
    assert clone.observed_state_digest(ref) != digest_before
    # a second blind retry must not apply again
    again = _send(writer, ChangeKind.UPDATE_DRAFT, upd, ref, "V1")
    assert again.status is WriteStatus.REJECTED and again.code == "STALE_VERSION"
    assert clone.write_count == 2


def test_timeout_on_create_leaves_no_document_and_retry_creates_exactly_one(env):
    clone, writer, gen = env
    p = gen.draft_payload()
    clone.fail_next("timeout")
    assert _send(writer, ChangeKind.CREATE_DRAFT, p).status is WriteStatus.UNKNOWN_TIMEOUT
    assert clone.target_refs() == () and clone.find_duplicates(p) == ()
    assert _send(writer, ChangeKind.CREATE_DRAFT, p).success
    assert len(clone.target_refs()) == 1 and len(clone.find_duplicates(p)) == 1


def test_duplicate_detection_override_and_injected_duplicate_mode(env):
    clone, writer, gen = env
    p = gen.draft_payload()
    assert _send(writer, ChangeKind.CREATE_DRAFT, p).success
    first = clone.target_refs()[0]
    assert clone.find_duplicates(p) == (first,)
    assert clone.find_duplicates(p, exclude_ref=first) == ()

    twin = replace(gen.draft_payload(), counterparty_ref=p.counterparty_ref,
                   supplier_document_number=p.supplier_document_number,
                   supplier_document_date=p.supplier_document_date)
    refused = _send(writer, ChangeKind.CREATE_DRAFT, twin)
    assert refused.status is WriteStatus.REJECTED and refused.code == "DUPLICATE"
    assert len(clone.target_refs()) == 1

    overridden = replace(twin, duplicate_override=DuplicateOverride(first, "Synthetic justified duplicate"))
    ok = _send(writer, ChangeKind.CREATE_DRAFT, overridden)
    assert ok.success and len(clone.target_refs()) == 2
    assert len(clone.find_duplicates(p)) == 2

    clone.fail_next("duplicate")
    fresh = gen.draft_payload()
    injected = _send(writer, ChangeKind.CREATE_DRAFT, fresh)
    assert injected.status is WriteStatus.REJECTED and injected.code == "DUPLICATE"
    assert clone.find_duplicates(fresh) == () and clone.write_count == 2
    assert clone.truth_log()[-1]["outcome"] == "REFUSED:INJECTED_DUPLICATE"


def test_stale_expected_version_is_rejected_without_write(env):
    clone, writer, gen = env
    populate(clone, gen, 1)
    ref = clone.target_refs()[0]
    cpt = clone.read_state(ref)["payload"]["counterparty_ref"]
    assert _send(writer, ChangeKind.POST, None, ref, "V1").success  # now V2
    snapshot = clone.read_state(ref)
    stale = _send(writer, ChangeKind.UNPOST, None, ref, "V1")
    assert stale.status is WriteStatus.REJECTED and stale.code == "STALE_VERSION"
    missing = _send(writer, ChangeKind.UNPOST, None, ref, None)
    assert missing.code == "STALE_VERSION"
    assert clone.read_state(ref) == snapshot
    # draft update whose payload version disagrees with expected_version is also stale
    assert _send(writer, ChangeKind.UNPOST, None, ref, "V2").success
    mismatch = replace(gen.draft_payload(counterparty_ref=cpt), expected_target_version="V1")
    out = _send(writer, ChangeKind.UPDATE_DRAFT, mismatch, ref, "V3")
    assert out.status is WriteStatus.REJECTED and out.code == "STALE_VERSION"


def test_tampered_bytes_detected_and_truth_log_shows_what_landed(env):
    clone, writer, gen = env
    p = gen.draft_payload()
    data = encode_payload(p)
    approved = _sha(data)
    clone.tamper()
    out = writer.write("SIM-CHG-000001", 1, ChangeKind.CREATE_DRAFT, data, approved, None, None)
    assert out.status is WriteStatus.TAMPER_DETECTED and not out.success
    assert out.code == "RECEIVED_DIGEST_MISMATCH" and out.received_payload_sha256 != approved
    entry = clone.truth_log()[-1]
    # ground truth: the tampered bytes WERE applied although the writer reported non-success
    assert entry["write_applied"] is True and entry["received_payload_sha256"] == out.received_payload_sha256
    assert entry["received_payload_sha256"] != approved
    assert len(clone.target_refs()) == 1
    landed = clone.read_state(clone.target_refs()[0])["payload"]
    intended = {k: v for k, v in json.loads(data.decode("ascii")).items()
                if k != "expected_target_version"}
    landed_cmp = {k: v for k, v in landed.items() if k != "expected_target_version"}
    assert landed_cmp != intended  # what really landed differs from what was approved
    # tamper is one-shot: the next write is clean
    assert _send(writer, ChangeKind.CREATE_DRAFT, gen.draft_payload(), change_id="SIM-CHG-000002").success


def test_tamper_on_refused_write_is_tamper_detected_and_nothing_lands(env):
    clone, writer, gen = env
    populate(clone, gen, 1)
    ref = clone.target_refs()[0]
    clone.tamper()
    out = _send(writer, ChangeKind.POST, None, ref, "V1")  # b"{}" has no digit: first byte flipped -> invalid
    assert out.status is WriteStatus.TAMPER_DETECTED
    assert clone.truth_log()[-1]["write_applied"] is False
    assert clone.read_state(ref)["status"] == "DRAFT"


def test_crash_before_vs_after_write_distinguished_by_state_read(env):
    clone, writer, gen = env
    # CREATE: distinguish by the set of documents
    p1 = gen.draft_payload()
    refs0 = clone.target_refs()
    clone.fail_next("crash_before_write")
    out = _send(writer, ChangeKind.CREATE_DRAFT, p1)
    assert out.status is WriteStatus.UNKNOWN_CRASH
    assert _classify_crash(clone, refs0, None, None) == "NO_WRITE"
    assert clone.truth_log()[-1]["outcome"] == "CRASH_BEFORE_WRITE"

    clone.fail_next("crash_after_write")
    out = _send(writer, ChangeKind.CREATE_DRAFT, p1)
    assert out.status is WriteStatus.UNKNOWN_CRASH and out.receipt is None
    assert _classify_crash(clone, refs0, None, None) == "WRITE_LANDED"
    assert clone.truth_log()[-1]["outcome"] == "CRASH_AFTER_WRITE"
    assert len(clone.find_duplicates(p1)) == 1  # repair must NOT recreate

    # POST: distinguish by the target state
    ref = clone.target_refs()[0]
    before = clone.read_state(ref)
    clone.fail_next("crash_before_write")
    assert _send(writer, ChangeKind.POST, None, ref, "V1").status is WriteStatus.UNKNOWN_CRASH
    assert _classify_crash(clone, (), ref, before) == "NO_WRITE"
    clone.fail_next("crash_after_write")
    assert _send(writer, ChangeKind.POST, None, ref, "V1").status is WriteStatus.UNKNOWN_CRASH
    assert _classify_crash(clone, (), ref, before) == "WRITE_LANDED"
    assert clone.read_state(ref)["status"] == "POSTED" and clone.read_state(ref)["version"] == "V2"
    # retry with the old version is refused: repair cannot double-post
    assert _send(writer, ChangeKind.POST, None, ref, "V1").code == "STALE_VERSION"
    assert clone.write_count == 2


def test_populate_50_plus_documents_is_deterministic_by_seed():
    def build(seed: int):
        clone = SimulatedOneC("SIM-CLONE-DET")
        refs = populate(clone, SyntheticGenerator(seed=seed), 60, post_every=5)
        return clone, refs

    a, refs_a = build(7)
    b, refs_b = build(7)
    c, _ = build(8)
    assert len(refs_a) == 60 and len(set(refs_a)) == 60 and refs_a == refs_b
    assert a.state_fingerprint() == b.state_fingerprint() != c.state_fingerprint()
    assert [a.observed_state_digest(r) for r in refs_a] == [b.observed_state_digest(r) for r in refs_b]
    posted = [r for r in refs_a if a.read_state(r)["status"] == "POSTED"]
    assert len(posted) == 12
    assert a.write_count == 72
    for r in refs_a:
        state = a.read_state(r)
        assert r.startswith("SIM-DOC-") and state["lane"] == "TEST"
        assert state["payload"]["supplier_document_number"].startswith("SIM-INV-")


def test_two_interleaved_writers_only_one_wins_on_expected_version(env):
    clone, writer_a, gen = env
    writer_b = ReferenceWriter(clone, clone.receipt_public_key_hex)
    populate(clone, gen, 1)
    ref = clone.target_refs()[0]
    cpt = clone.read_state(ref)["payload"]["counterparty_ref"]
    seen_a = clone.read_state(ref)["version"]
    seen_b = clone.read_state(ref)["version"]
    assert seen_a == seen_b == "V1"
    pa = replace(gen.draft_payload(counterparty_ref=cpt), expected_target_version=seen_a, comment="writer A")
    pb = replace(gen.draft_payload(counterparty_ref=cpt), expected_target_version=seen_b, comment="writer B")
    won = _send(writer_a, ChangeKind.UPDATE_DRAFT, pa, ref, seen_a, change_id="SIM-CHG-00000A")
    lost = _send(writer_b, ChangeKind.UPDATE_DRAFT, pb, ref, seen_b, change_id="SIM-CHG-00000B")
    assert won.success and won.new_version == "V2"
    assert lost.status is WriteStatus.REJECTED and lost.code == "STALE_VERSION"
    state = clone.read_state(ref)
    assert state["payload"]["comment"] == "writer A" and state["version"] == "V2"
    assert [e["write_applied"] for e in clone.truth_log()][-2:] == [True, False]
    # loser re-reads and wins on the new version
    pb2 = replace(pb, expected_target_version="V2")
    assert _send(writer_b, ChangeKind.UPDATE_DRAFT, pb2, ref, "V2", change_id="SIM-CHG-00000B", generation=2).success
    assert clone.read_state(ref)["payload"]["comment"] == "writer B"


def test_separate_clone_labels_are_isolated():
    gen = SyntheticGenerator(seed=5)
    a, b = SimulatedOneC("SIM-TENANT-A"), SimulatedOneC("SIM-TENANT-B")
    att_a, att_b = SimulatedAttestor("SIM-ATT-A"), SimulatedAttestor("SIM-ATT-B")
    wa = ReferenceWriter(a, a.receipt_public_key_hex)
    wb = ReferenceWriter(b, b.receipt_public_key_hex)
    p = gen.draft_payload()
    assert _send(wa, ChangeKind.CREATE_DRAFT, p).success
    assert b.target_refs() == () and b.write_count == 0 and b.truth_log() == ()
    assert b.find_duplicates(p) == ()
    # A's document reference is unknown to B: no cross-clone reach
    assert _send(wb, ChangeKind.POST, None, a.target_refs()[0], "V1").code == "NOT_FOUND"
    with pytest.raises(CloneRejected):
        b.read_state(a.target_refs()[0])
    # same content on both clones: fingerprints differ because the label is part of the state
    assert _send(wb, ChangeKind.CREATE_DRAFT, p, change_id="SIM-CHG-000002").success
    assert a.state_fingerprint() != b.state_fingerprint()
    # mutating B leaves A untouched even though both use the same document reference
    fp_a = a.state_fingerprint()
    assert a.target_refs() == b.target_refs()
    assert _send(wb, ChangeKind.POST, None, b.target_refs()[0], "V1", change_id="SIM-CHG-000003").success
    assert a.state_fingerprint() == fp_a and a.read_state(a.target_refs()[0])["status"] == "DRAFT"
    # a receipt from attestor A is not accepted under B's trusted key
    cross = ReferenceWriter(a, trusted_public_key_hex=att_b.public_key_hex)
    out = _send(cross, ChangeKind.POST, None, a.target_refs()[0], "V1", change_id="SIM-CHG-000004")
    assert out.status is WriteStatus.RECEIPT_INVALID and out.code == "RECEIPT_SIGNATURE_INVALID"
