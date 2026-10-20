"""Offline tests of the simulation stand-ins: SimulatedOneC, SimulatedAttestor and the synthetic generator.

No database, no network, no real 1C. Every assertion would fail if the guarded behavior were broken.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest

from business_ai_gateway.phase2.change.errors import Refusal
from business_ai_gateway.phase2.change.proposal import (
    ChangeProposal, DuplicateOverride, canonical_json, parse_proposal, sha256_hex,
)
from business_ai_gateway.phase2.change.types import ChangeKind
from business_ai_gateway.phase2.simulation.attestation import SimulatedAttestor, verify_attestation
from business_ai_gateway.phase2.simulation.clone_1c import (
    LANE, SYNTHETIC_MARKER, CloneCrash, CloneRejected, CloneTimeout, SimulatedOneC, decode_payload, encode_payload,
    receipt_signing_text, verify_clone_receipt,
)
from business_ai_gateway.phase2.simulation.synthetic_data import SyntheticGenerator, populate

CREATE, UPDATE, POST, UNPOST = (ChangeKind.CREATE_DRAFT, ChangeKind.UPDATE_DRAFT, ChangeKind.POST, ChangeKind.UNPOST)
EMPTY = encode_payload(None)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _create(clone: SimulatedOneC, gen: SyntheticGenerator, **kw):
    payload = gen.draft_payload(**kw)
    return payload, clone.apply(CREATE, encode_payload(payload), None, None)


# ---- synthetic data -------------------------------------------------------------------------------------------

def test_same_seed_same_data_different_seed_different_data():
    a, b, c = SyntheticGenerator(7), SyntheticGenerator(7), SyntheticGenerator(8)
    assert a.universe == b.universe
    pa, pb, pc = a.payloads(25), b.payloads(25), c.payloads(25)
    assert pa == pb
    assert [encode_payload(p) for p in pa] == [encode_payload(p) for p in pb]
    assert pa != pc
    assert len({(p.counterparty_ref, p.supplier_document_number, p.supplier_document_date) for p in pa}) == 25


def test_every_generated_payload_is_accepted_by_the_real_parser():
    gen = SyntheticGenerator(11, organizations=2, counterparties=6, items=9)
    for index in range(40):
        org = gen.universe.organizations[index % 2]
        scope = gen.scope(org)
        payload = gen.draft_payload(organization_ref=org)
        parsed = parse_proposal(gen.envelope(CREATE, payload), gen.context(scope))
        assert type(parsed) is ChangeProposal, parsed
        assert parsed.payload == payload
        upd = replace(payload, expected_target_version="V1")
        parsed_u = parse_proposal(gen.envelope(UPDATE, upd, target_ref="SIM-DOC-000001", target_version="V1"),
                                  gen.context(scope, target_refs=("SIM-DOC-000001",)))
        assert type(parsed_u) is ChangeProposal and parsed_u.target_version == "V1", parsed_u
        assert type(parsed_u) is ChangeProposal, parsed_u


def test_real_parser_refuses_what_the_generator_does_not_produce():
    gen = SyntheticGenerator(3)
    scope = gen.scope()
    two_lines = gen.draft_payload(lines=2)
    assert type(parse_proposal(gen.envelope(CREATE, two_lines), gen.context(scope))) is Refusal  # shape not qualified
    other_org = SyntheticGenerator(3, organizations=2).universe.organizations[1]
    wrong = gen.draft_payload(organization_ref=other_org)
    assert type(parse_proposal(gen.envelope(CREATE, wrong), gen.context(scope))) is Refusal  # scope mismatch


def test_payload_wire_roundtrip_and_post_envelope():
    gen = SyntheticGenerator(5)
    payload = gen.draft_payload()
    assert decode_payload(encode_payload(payload)) == payload
    assert decode_payload(EMPTY) is None
    scope = gen.scope()
    ctx = gen.context(scope, business_state_digest="a" * 64, target_refs=("SIM-DOC-000001",))
    parsed = parse_proposal(gen.envelope(POST, target_ref="SIM-DOC-000001", target_version="V1",
                                         parent_change_id="SIM-CHG-000000"), ctx)
    assert type(parsed) is ChangeProposal and parsed.kind is POST
    for bad in (b"", b"[]", b"{\"a\":1}", b"\xff", b"not json"):
        with pytest.raises(CloneRejected) as exc:
            decode_payload(bad)
        assert exc.value.code == "PAYLOAD_INVALID"


def test_populate_seeds_n_documents_deterministically():
    def build():
        clone = SimulatedOneC()
        refs = populate(clone, SyntheticGenerator(21), 12, post_every=4)
        return clone, refs

    (c1, r1), (c2, r2) = build(), build()
    assert r1 == r2 and len(r1) == 12 == len(c1.target_refs())
    assert c1.state_fingerprint() == c2.state_fingerprint()
    statuses = [c1.read_state(r)["status"] for r in r1]
    assert statuses.count("POSTED") == 3 and statuses.count("DRAFT") == 9
    assert all(c1.read_state(r)["lane"] == LANE == "TEST" and c1.read_state(r)["synthetic_marker"] == SYNTHETIC_MARKER
               for r in r1)


# ---- clone semantics --------------------------------------------------------------------------------------------

def test_create_update_post_unpost_and_repair_correction():
    gen = SyntheticGenerator(1)
    clone = SimulatedOneC()
    payload, created = _create(clone, gen)
    ref = created.target_ref
    assert (created.new_version, created.effects["documents_created"]) == ("V1", 1)
    assert clone.read_state(ref)["status"] == "DRAFT" and clone.read_state(ref)["movements"] == {}

    updated_payload = replace(gen.draft_payload(counterparty_ref=payload.counterparty_ref), expected_target_version="V1")
    upd = clone.apply(UPDATE, encode_payload(updated_payload), ref, "V1")
    assert upd.new_version == "V2" and upd.effects["documents_updated"] == 1
    assert clone.read_state(ref)["payload"]["comment"] == updated_payload.comment
    assert clone.read_state(ref)["payload"]["expected_target_version"] is None  # transport-only guard is not stored

    posted = clone.apply(POST, EMPTY, ref, "V2")
    assert posted.new_version == "V3" and posted.effects["movement_rows_added"] == 2  # 2 registers x 1 line
    state = clone.read_state(ref)
    assert state["status"] == "POSTED" and sorted(state["movements"].values()) == [1, 1]
    with pytest.raises(CloneRejected) as exc:
        clone.apply(POST, EMPTY, ref, "V3")
    assert exc.value.code == "NOT_DRAFT"
    with pytest.raises(CloneRejected) as exc:  # a posted document cannot be edited without UNPOST
        clone.apply(UPDATE, encode_payload(replace(updated_payload, expected_target_version="V3")), ref, "V3")
    assert exc.value.code == "NOT_DRAFT"

    # repair-style correction of a posted document: UNPOST -> UPDATE -> POST, each version-checked
    unposted = clone.apply(UNPOST, EMPTY, ref, "V3")
    assert unposted.new_version == "V4" and unposted.effects["movement_rows_removed"] == 2
    assert clone.read_state(ref)["status"] == "DRAFT" and clone.read_state(ref)["movements"] == {}
    corrected = replace(updated_payload, comment="Synthetic correction", expected_target_version="V4")
    assert clone.apply(UPDATE, encode_payload(corrected), ref, "V4").new_version == "V5"
    assert clone.apply(POST, EMPTY, ref, "V5").new_version == "V6"
    final = clone.read_state(ref)
    assert final["status"] == "POSTED" and final["payload"]["comment"] == "Synthetic correction"
    with pytest.raises(CloneRejected) as exc:
        clone.apply(UNPOST, EMPTY, "SIM-DOC-999999", "V1")
    assert exc.value.code == "NOT_FOUND"
    _, second = _create(clone, gen)
    with pytest.raises(CloneRejected) as exc:  # UNPOST of a draft
        clone.apply(UNPOST, EMPTY, second.target_ref, "V1")
    assert exc.value.code == "NOT_POSTED"


def test_stale_expected_version_is_refused_without_write():
    gen = SyntheticGenerator(2)
    clone = SimulatedOneC()
    payload, created = _create(clone, gen)
    ref = created.target_ref
    clone.apply(UPDATE, encode_payload(replace(gen.draft_payload(counterparty_ref=payload.counterparty_ref),
                                               expected_target_version="V1")), ref, "V1")
    before, writes = clone.state_fingerprint(), clone.write_count
    stale = replace(gen.draft_payload(counterparty_ref=payload.counterparty_ref), expected_target_version="V1")
    for kind, data, expected in ((UPDATE, encode_payload(stale), "V1"), (POST, EMPTY, "V1"), (POST, EMPTY, None)):
        with pytest.raises(CloneRejected) as exc:
            clone.apply(kind, data, ref, expected)
        assert exc.value.code == "STALE_VERSION"
    mismatch = replace(stale, expected_target_version="V1")  # payload guard disagrees with the call's version
    with pytest.raises(CloneRejected) as exc:
        clone.apply(UPDATE, encode_payload(mismatch), ref, "V2")
    assert exc.value.code == "STALE_VERSION"
    assert clone.state_fingerprint() == before and clone.write_count == writes


def test_duplicate_detection_by_counterparty_number_date_and_override():
    gen = SyntheticGenerator(4)
    clone = SimulatedOneC()
    first, created = _create(clone, gen)
    same_key = gen.draft_payload(counterparty_ref=first.counterparty_ref,
                                 supplier_document_number=first.supplier_document_number,
                                 supplier_document_date=first.supplier_document_date)
    with pytest.raises(CloneRejected) as exc:
        clone.apply(CREATE, encode_payload(same_key), None, None)
    assert exc.value.code == "DUPLICATE" and len(clone.target_refs()) == 1
    other_cpt = next(c for c in gen.universe.counterparties if c != first.counterparty_ref)
    assert _create(clone, gen, counterparty_ref=other_cpt,
                   supplier_document_number=first.supplier_document_number,
                   supplier_document_date=first.supplier_document_date)[1].new_version == "V1"
    other_date = gen.draft_payload(counterparty_ref=first.counterparty_ref,
                                   supplier_document_number=first.supplier_document_number,
                                   supplier_document_date="2026-12-31")
    clone.apply(CREATE, encode_payload(other_date), None, None)
    assert len(clone.target_refs()) == 3
    assert clone.find_duplicates(same_key) == (created.target_ref,)
    overridden = replace(same_key, duplicate_override=DuplicateOverride(created.target_ref, "synthetic override"))
    assert clone.apply(CREATE, encode_payload(overridden), None, None).effects["documents_created"] == 1
    assert len(clone.target_refs()) == 4
    # updating a document to collide with another is refused, updating it to itself is not
    refs = clone.target_refs()
    colliding = replace(same_key, expected_target_version="V1")
    with pytest.raises(CloneRejected) as exc:
        clone.apply(UPDATE, encode_payload(colliding), refs[1], "V1")
    assert exc.value.code == "DUPLICATE"
    self_update = replace(other_date, expected_target_version="V1")
    assert clone.apply(UPDATE, encode_payload(self_update), refs[2], "V1").new_version == "V2"


# ---- failure injection ------------------------------------------------------------------------------------------

def test_injected_failures_and_their_ground_truth_effects():
    gen = SyntheticGenerator(6)
    clone = SimulatedOneC()
    _, created = _create(clone, gen)
    ref = created.target_ref
    snapshot = clone.state_fingerprint()

    for mode, exc_type in (("timeout", CloneTimeout), ("crash_before_write", CloneCrash), ("reject", CloneRejected),
                           ("duplicate", CloneRejected)):
        clone.fail_next(mode)
        with pytest.raises(exc_type):
            clone.apply(POST, EMPTY, ref, "V1")
        assert clone.state_fingerprint() == snapshot, mode  # none of these wrote
    clone.fail_next("reject")
    with pytest.raises(CloneRejected) as exc:
        clone.apply(POST, EMPTY, ref, "V1")
    assert exc.value.code == "REJECTED" and exc.value.received_payload_sha256 == _sha(EMPTY)

    clone.fail_next("crash_after_write")
    with pytest.raises(CloneCrash):
        clone.apply(POST, EMPTY, ref, "V1")
    assert clone.state_fingerprint() != snapshot  # unknown outcome: the write IS applied
    state = clone.read_state(ref)
    assert state["status"] == "POSTED" and state["version"] == "V2"
    # the caller must resolve the unknown outcome by reading state; a blind retry is refused by the version check
    with pytest.raises(CloneRejected) as exc:
        clone.apply(POST, EMPTY, ref, "V1")
    assert exc.value.code == "STALE_VERSION"
    outcomes = [e["outcome"] for e in clone.truth_log()]
    assert outcomes[1:] == ["TIMEOUT_NO_WRITE", "CRASH_BEFORE_WRITE", "REFUSED:INJECTED_REJECT",
                            "REFUSED:INJECTED_DUPLICATE", "REFUSED:INJECTED_REJECT", "CRASH_AFTER_WRITE",
                            "REFUSED:STALE_VERSION"]
    assert [e["write_applied"] for e in clone.truth_log()] == [True, False, False, False, False, False, True, False]
    assert clone.write_count == 2


def test_crash_after_create_makes_blind_retry_a_duplicate():
    gen = SyntheticGenerator(9)
    clone = SimulatedOneC()
    payload = gen.draft_payload()
    clone.fail_next("crash_after_write")
    with pytest.raises(CloneCrash):
        clone.apply(CREATE, encode_payload(payload), None, None)
    assert len(clone.target_refs()) == 1
    with pytest.raises(CloneRejected) as exc:
        clone.apply(CREATE, encode_payload(payload), None, None)
    assert exc.value.code == "DUPLICATE" and len(clone.target_refs()) == 1


def test_failures_are_consumed_fifo_one_per_call_and_validated():
    gen = SyntheticGenerator(10)
    clone = SimulatedOneC()
    with pytest.raises(ValueError):
        clone.fail_next("explode")
    clone.fail_next("timeout")
    clone.fail_next("reject")
    p1 = gen.draft_payload()
    with pytest.raises(CloneTimeout):
        clone.apply(CREATE, encode_payload(p1), None, None)
    with pytest.raises(CloneRejected):
        clone.apply(CREATE, encode_payload(p1), None, None)
    assert clone.apply(CREATE, encode_payload(p1), None, None).new_version == "V1"  # queue drained


# ---- digests ----------------------------------------------------------------------------------------------------

def test_preview_and_state_digests_are_stable_and_follow_state():
    gen = SyntheticGenerator(12)
    clone = SimulatedOneC()
    payload = gen.draft_payload()
    p1 = clone.preview(CREATE, payload, None)
    assert p1 == clone.preview(CREATE, payload, None) and p1.sha256 == _sha(p1.text.encode("ascii"))
    assert clone.write_count == 0 and not clone.target_refs()  # preview never writes
    assert '"lane":"TEST"' in p1.text and SYNTHETIC_MARKER in p1.text
    assert p1.sha256 != clone.preview(CREATE, gen.draft_payload(), None).sha256

    created = clone.apply(CREATE, encode_payload(payload), None, None)
    ref = created.target_ref
    d1 = clone.observed_state_digest(ref)
    assert d1 == clone.observed_state_digest(ref) and len(d1) == 64
    pv_post = clone.preview(POST, None, ref)
    assert pv_post.sha256 == clone.preview(POST, None, ref).sha256
    fp1 = clone.state_fingerprint()

    clone.apply(POST, EMPTY, ref, "V1")
    assert clone.observed_state_digest(ref) != d1  # business state changed
    assert clone.preview(POST, None, ref).sha256 != pv_post.sha256  # preview follows state (and predicts a refusal)
    assert '"refusal":"NOT_DRAFT"' in clone.preview(POST, None, ref).text
    assert clone.state_fingerprint() != fp1
    clone.apply(UNPOST, EMPTY, ref, "V2")
    assert clone.observed_state_digest(ref) == d1  # content equals the original draft again ...
    assert clone.read_state(ref)["version"] == "V3"  # ... but the version moved on
    assert clone.state_fingerprint() != fp1
    # an identical clone built the same way has the identical fingerprint (determinism)
    twin = SimulatedOneC()
    twin.apply(CREATE, encode_payload(payload), None, None)
    twin.apply(POST, EMPTY, ref, "V1")
    twin.apply(UNPOST, EMPTY, ref, "V2")
    assert twin.state_fingerprint() == clone.state_fingerprint()
    with pytest.raises(CloneRejected):
        clone.observed_state_digest("SIM-DOC-999999")


def test_received_payload_digest_equals_sent_bytes_and_differs_under_tamper():
    gen = SyntheticGenerator(13)
    clone = SimulatedOneC()
    payload = gen.draft_payload()
    data = encode_payload(payload)
    result = clone.apply(CREATE, data, None, None)
    assert result.received_payload_sha256 == _sha(data)
    assert result.lane == "TEST" and result.synthetic_marker == SYNTHETIC_MARKER

    clone.tamper()
    payload2 = gen.draft_payload()
    data2 = encode_payload(payload2)
    try:
        tampered = clone.apply(CREATE, data2, None, None)
        got = tampered.received_payload_sha256
        written = clone.read_state(tampered.target_ref)["payload"]
        assert written != payload_dict(payload2)  # the bad transport silently corrupted what was written
    except CloneRejected as exc:  # a byte flip may also make the payload unparsable: still a digest mismatch
        got = exc.received_payload_sha256
    assert got != _sha(data2)
    assert data2 == encode_payload(payload2)  # the caller's own bytes are never mutated
    assert sum(1 for e in clone.truth_log() if e["received_payload_sha256"] != _sha(data2)) >= 1
    # tamper is one-shot
    payload3 = gen.draft_payload()
    assert clone.apply(CREATE, encode_payload(payload3), None, None).received_payload_sha256 == _sha(encode_payload(payload3))


def payload_dict(payload):
    from business_ai_gateway.phase2.change.proposal import payload_to_dict
    return {**payload_to_dict(payload), "expected_target_version": None}


def test_tamper_on_empty_payload_is_refused_with_differing_digest():
    gen = SyntheticGenerator(14)
    clone = SimulatedOneC()
    _, created = _create(clone, gen)
    clone.tamper()
    with pytest.raises(CloneRejected) as exc:
        clone.apply(POST, EMPTY, created.target_ref, "V1")
    assert exc.value.code == "PAYLOAD_INVALID" and exc.value.received_payload_sha256 != _sha(EMPTY)
    assert clone.read_state(created.target_ref)["status"] == "DRAFT"


# ---- attestations -----------------------------------------------------------------------------------------------

def test_attestations_verify_and_fail_on_any_change_or_wrong_key():
    attestor = SimulatedAttestor("SIM-ATTESTOR-A")
    other = SimulatedAttestor("SIM-ATTESTOR-B")
    assert attestor.public_key_hex != other.public_key_hex
    assert SimulatedAttestor("SIM-ATTESTOR-A").public_key_hex == attestor.public_key_hex  # deterministic seed
    d1, d2 = sha256_hex("preview"), sha256_hex("state")
    cases = [
        attestor.preview_attestation("SIM-CHG-1", "SIM-DOC-000001", "V1", d1),
        attestor.preview_attestation("SIM-CHG-1", None, None, d1),
        attestor.state_attestation("SIM-CHG-1", "SIM-DOC-000001", "V1", d2),
        attestor.receipt_attestation("SIM-CHG-1", 3, d1, "V2"),
    ]
    mutations = {
        "change_id": "SIM-CHG-2", "target_ref": "SIM-DOC-000002", "target_version": "V9", "preview_sha256": d2,
        "business_state_digest": d1, "generation": 4, "received_payload_sha256": d2, "new_version": "V3",
        "type": "STATE", "lane": "PROD", "key_id": "sim-key-0000000000000000",
    }
    for att in cases:
        assert att["lane"] == "TEST" and att["key_id"] == attestor.key_id and att["public_key"] == attestor.public_key_hex
        assert verify_attestation(attestor.public_key_hex, att) is True
        assert verify_attestation(other.public_key_hex, att) is False  # wrong key
        for name, value in mutations.items():
            if name in att and att[name] != value:
                assert verify_attestation(attestor.public_key_hex, {**att, name: value}) is False, name
        sig = bytearray.fromhex(att["signature"])
        sig[0] ^= 1
        assert verify_attestation(attestor.public_key_hex, {**att, "signature": sig.hex()}) is False
        assert verify_attestation(attestor.public_key_hex, {**att, "public_key": other.public_key_hex}) is False
        assert verify_attestation(attestor.public_key_hex, {**att, "extra": "x"}) is False
        assert verify_attestation(attestor.public_key_hex, {k: v for k, v in att.items() if k != "lane"}) is False
    forged = {**cases[3], "signature": other.receipt_attestation("SIM-CHG-1", 3, d1, "V2")["signature"]}
    assert verify_attestation(attestor.public_key_hex, forged) is False  # signature by another key, same fields
    for junk in (None, "x", {}, {"type": "RECEIPT"}):
        assert verify_attestation(attestor.public_key_hex, junk) is False  # never raises
    assert verify_attestation("zz", cases[0]) is False


def test_attestor_rejects_malformed_inputs_and_binds_to_clone_artifacts():
    attestor = SimulatedAttestor()
    with pytest.raises(ValueError):
        attestor.preview_attestation("SIM-CHG-1", None, None, "not-a-digest")
    with pytest.raises(ValueError):
        attestor.receipt_attestation("SIM-CHG-1", -1, sha256_hex("x"), "V1")
    with pytest.raises(ValueError):
        attestor.receipt_attestation("has space", 1, sha256_hex("x"), "V1")
    # end to end: a receipt attests the digest of the bytes the clone received; a tampered receipt does not match
    gen = SyntheticGenerator(15)
    clone = SimulatedOneC()
    data = encode_payload(gen.draft_payload())
    result = clone.apply(CREATE, data, None, None)
    receipt = attestor.receipt_attestation("SIM-CHG-1", 1, result.received_payload_sha256, result.new_version)
    assert verify_attestation(attestor.public_key_hex, receipt)
    assert receipt["received_payload_sha256"] == _sha(data)
    state_att = attestor.state_attestation("SIM-CHG-1", result.target_ref, result.new_version,
                                           clone.observed_state_digest(result.target_ref))
    assert verify_attestation(attestor.public_key_hex, state_att)
    assert canonical_json(state_att)  # attestations are canonical-JSON serializable


# ---- clone-signed receipt (F-01): the clone owns the key, a caller only forwards the receipt ----------------------

def test_clone_signs_its_own_receipt_over_change_dispatch_digest_version():
    clone = SimulatedOneC("SIM-CLONE-R1")
    data = encode_payload(SyntheticGenerator(21).draft_payload())
    result = clone.apply(CREATE, data, None, None, change_id="chg-1", dispatch_id="disp-1")
    rc = result.receipt
    assert rc is not None and rc["received_payload_sha256"] == _sha(data) and rc["new_version"] == result.new_version
    assert rc["change_id"] == "chg-1" and rc["dispatch_id"] == "disp-1" and rc["key_id"] == clone.receipt_key_id
    assert verify_clone_receipt(clone.receipt_public_key_hex, rc)
    assert receipt_signing_text("chg-1", "disp-1", _sha(data), result.new_version).startswith("change-ledger-receipt|v1|")
    # no secret leaks through the public surface: the receipt and key attributes hold public data only
    assert clone._receipt_seed.hex() not in repr(rc) + clone.receipt_public_key_hex


def test_clone_receipt_fails_for_every_changed_field_and_other_keys():
    clone, other = SimulatedOneC("SIM-CLONE-R1"), SimulatedOneC("SIM-CLONE-R2")
    data = encode_payload(SyntheticGenerator(22).draft_payload())
    rc = clone.apply(CREATE, data, None, None, change_id="chg-1", dispatch_id="disp-1").receipt
    pub = clone.receipt_public_key_hex
    assert not verify_clone_receipt(other.receipt_public_key_hex, rc)               # wrong key
    for field, value in (("change_id", "chg-2"), ("dispatch_id", "disp-2"), ("new_version", "V9"),
                         ("received_payload_sha256", "0" * 64), ("lane", "PROD"), ("type", "PREVIEW")):
        assert not verify_clone_receipt(pub, {**rc, field: value}), field
    assert not verify_clone_receipt(pub, {**rc, "signature": "00" * 64})
    assert not verify_clone_receipt(pub, {k: v for k, v in rc.items() if k != "signature"})
    assert not verify_clone_receipt(pub, {**rc, "extra": 1}) and not verify_clone_receipt(pub, None)


def test_clone_receipt_binds_the_bytes_actually_received_and_is_absent_without_ids_or_success():
    clone = SimulatedOneC("SIM-CLONE-R1")
    data = encode_payload(SyntheticGenerator(23).draft_payload())
    assert clone.apply(CREATE, data, None, None).receipt is None                    # no ids: no receipt (old callers)
    clone.tamper()
    with pytest.raises(CloneRejected) as exc:                                       # tampered bytes never get a receipt
        clone.apply(CREATE, data, None, None, change_id="chg-1", dispatch_id="disp-1")
    assert exc.value.received_payload_sha256 != _sha(data)
    clone.fail_next("timeout")
    with pytest.raises(CloneTimeout):
        clone.apply(CREATE, data, None, None, change_id="chg-1", dispatch_id="disp-1")
    with pytest.raises(ValueError):
        clone.apply(CREATE, data, None, None, change_id="chg-1")                    # ids come as a pair
    with pytest.raises(ValueError):
        clone.apply(CREATE, data, None, None, change_id="a|b", dispatch_id="disp-1")
