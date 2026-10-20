"""Offline tests for the simulation ReferenceWriter (no Postgres, no docker)."""
from __future__ import annotations

import dataclasses
import hashlib

import pytest

from business_ai_gateway.phase2.change.types import ChangeKind
from business_ai_gateway.phase2.simulation.clone_1c import FAILURE_MODES, SimulatedOneC, encode_payload
from business_ai_gateway.phase2.simulation.reference_writer import (
    ApprovedDigestMismatch, ReferenceWriter, WriteStatus)
from business_ai_gateway.phase2.simulation.synthetic_data import SyntheticGenerator


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


@pytest.fixture()
def env():
    clone = SimulatedOneC()
    payload = SyntheticGenerator(7).draft_payload()
    data = encode_payload(payload)
    return clone, None, ReferenceWriter(clone), data


def _create(w, data, digest=None):
    return w.write("chg-1", 1, ChangeKind.CREATE_DRAFT, data, digest or _sha(data), None, None)


def test_happy_path_sends_exact_bytes(env):
    clone, _, w, data = env
    out = _create(w, data)
    assert out.success and out.status is WriteStatus.APPLIED_VERIFIED
    assert out.received_payload_sha256 == out.approved_payload_sha256 == _sha(data)
    assert out.new_version == "V1" and clone.write_count == 1
    assert clone.truth_log()[0]["received_payload_sha256"] == _sha(data)
    assert out.receipt["received_payload_sha256"] == _sha(data)


def test_pre_send_digest_mismatch_sends_nothing(env):
    clone, _, w, data = env
    with pytest.raises(ApprovedDigestMismatch):
        _create(w, data, digest=_sha(data + b" "))
    with pytest.raises(ApprovedDigestMismatch):
        _create(w, data, digest="not-a-digest")
    assert clone.truth_log() == () and clone.write_count == 0


def test_tamper_detected(env):
    clone, _, w, data = env
    clone.tamper()
    out = _create(w, data)
    assert not out.success and out.status is WriteStatus.TAMPER_DETECTED
    assert out.received_payload_sha256 != out.approved_payload_sha256


@pytest.mark.parametrize("mode,status", [
    ("timeout", WriteStatus.UNKNOWN_TIMEOUT), ("crash_before_write", WriteStatus.UNKNOWN_CRASH),
    ("crash_after_write", WriteStatus.UNKNOWN_CRASH), ("reject", WriteStatus.REJECTED),
    ("duplicate", WriteStatus.REJECTED)])
def test_failure_modes_are_explicit_non_success(env, mode, status):
    clone, _, w, data = env
    assert mode in FAILURE_MODES
    clone.fail_next(mode)
    out = _create(w, data)
    assert not out.success and out.status is status and out.receipt is None and out.new_version is None
    assert clone.write_count == (1 if mode == "crash_after_write" else 0)


def test_stale_expected_version_rejected(env):
    clone, _, w, data = env
    first = _create(w, data)
    target = clone.target_refs()[0]
    assert first.success
    out = w.write("chg-2", 1, ChangeKind.POST, b"{}", _sha(b"{}"), target, "V0")
    assert out.status is WriteStatus.REJECTED and out.code == "STALE_VERSION"
    assert clone.write_count == 1
    ok = w.write("chg-3", 1, ChangeKind.POST, b"{}", _sha(b"{}"), target, "V1")
    assert ok.success and ok.new_version == "V2"


def test_receipt_signature_forgery_rejected(env):
    clone, _, _, data = env
    forged = ReferenceWriter(clone, trusted_public_key_hex=SimulatedOneC("OTHER-CLONE").receipt_public_key_hex)
    out = _create(forged, data)
    assert out.status is WriteStatus.RECEIPT_INVALID and out.code == "RECEIPT_SIGNATURE_INVALID" and not out.success


def test_receipt_with_tampered_field_rejected(env):
    _, _, _, data = env

    class Forging(SimulatedOneC):
        def apply(self, *a, **k):
            r = super().apply(*a, **k)
            return dataclasses.replace(r, receipt={**r.receipt, "new_version": "V99"})  # signature no longer covers it

    clone = Forging()
    out = _create(ReferenceWriter(clone), data)
    assert out.status is WriteStatus.RECEIPT_INVALID and out.code == "RECEIPT_SIGNATURE_INVALID"


def test_missing_receipt_is_not_success(env):
    _, _, _, data = env

    class NoReceipt(SimulatedOneC):
        def apply(self, *a, **k):
            return dataclasses.replace(super().apply(*a, **k), receipt=None)

    out = _create(ReferenceWriter(NoReceipt()), data)
    assert out.status is WriteStatus.RECEIPT_INVALID and out.code == "RECEIPT_MISSING" and not out.success


def test_receipt_for_another_dispatch_is_a_binding_mismatch(env):
    _, _, _, data = env

    class Replaying(SimulatedOneC):
        def apply(self, kind, payload_bytes, target_ref, expected_version, *, change_id=None, dispatch_id=None):
            return super().apply(kind, payload_bytes, target_ref, expected_version, change_id=change_id,
                                 dispatch_id="other-dispatch")

    out = _create(ReferenceWriter(Replaying()), data)
    assert out.status is WriteStatus.RECEIPT_INVALID and out.code == "RECEIPT_BINDING_MISMATCH"
