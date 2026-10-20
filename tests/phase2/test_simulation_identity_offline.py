"""Offline tests for the simulated IdP (no Postgres, no network)."""
from __future__ import annotations

import pytest

from business_ai_gateway.phase2.simulation.identity import (
    MfaAttestationError, SimulatedIdP, TwoPersonError, build_two_person_approval, verify_mfa_attestation)

NOW = 1_000_000


def _setup():
    idp = SimulatedIdP()
    idp.provision_person("ALICE")
    idp.provision_person("BOB")
    sa, sb = idp.open_session("ALICE"), idp.open_session("BOB")
    return idp, sa, sb


def _code(fn) -> str:
    with pytest.raises(MfaAttestationError) as ei:
        fn()
    return ei.value.code


def test_persons_deterministic_distinct_synthetic():
    p1, p2 = SimulatedIdP().provision_person("ALICE"), SimulatedIdP().provision_person("ALICE")
    assert p1 == p2
    bob = SimulatedIdP().provision_person("BOB")
    assert bob.login != p1.login and bob.public_key_hex != p1.public_key_hex
    assert p1.lane == "TEST" and p1.synthetic is True and p1.production_entitlement is False
    assert SimulatedIdP("OTHER").provision_person("ALICE").public_key_hex != p1.public_key_hex


def test_sessions_separate():
    idp, sa, sb = _setup()
    assert sa != sb and idp.open_session("ALICE") != sa
    assert idp.session_owner(sa) == "ALICE"


def test_valid_attestation_accepted_once():
    idp, sa, _ = _setup()
    att = idp.issue_mfa_attestation("ALICE", sa, NOW)
    assert att["lane"] == "TEST"
    assert idp.verify(att, NOW + 1, "ALICE", sa) is True
    assert _code(lambda: idp.verify(att, NOW + 1, "ALICE", sa)) == "MFA_NONCE_REPLAYED"


def test_forged_signature_and_tamper_rejected():
    idp, sa, _ = _setup()
    att = idp.issue_mfa_attestation("ALICE", sa, NOW)
    bad = dict(att, signature="00" * 64)
    assert _code(lambda: verify_mfa_attestation(idp.public_key_hex, bad, NOW, "ALICE", sa)) == "MFA_SIGNATURE_INVALID"
    tampered = dict(att, expires_at=att["expires_at"] + 9999)
    assert _code(lambda: verify_mfa_attestation(idp.public_key_hex, tampered, NOW, "ALICE", sa)) == "MFA_SIGNATURE_INVALID"
    other = SimulatedIdP("ROGUE")
    assert _code(lambda: verify_mfa_attestation(other.public_key_hex, att, NOW, "ALICE", sa)) == "MFA_SIGNATURE_INVALID"


def test_expired_and_not_yet_valid():
    idp, sa, _ = _setup()
    att = idp.issue_mfa_attestation("ALICE", sa, NOW, ttl_seconds=60)
    assert _code(lambda: verify_mfa_attestation(idp.public_key_hex, att, NOW + 60, "ALICE", sa)) == "MFA_EXPIRED"
    assert _code(lambda: verify_mfa_attestation(idp.public_key_hex, att, NOW - 1, "ALICE", sa)) == "MFA_EXPIRED"


def test_wrong_person_and_session():
    idp, sa, sb = _setup()
    att = idp.issue_mfa_attestation("ALICE", sa, NOW)
    assert _code(lambda: verify_mfa_attestation(idp.public_key_hex, att, NOW, "BOB", sa)) == "MFA_PERSON_MISMATCH"
    assert _code(lambda: verify_mfa_attestation(idp.public_key_hex, att, NOW, "ALICE", sb)) == "MFA_SESSION_MISMATCH"


def test_failed_check_does_not_burn_nonce():
    idp, sa, _ = _setup()
    att = idp.issue_mfa_attestation("ALICE", sa, NOW)
    seen: set[str] = set()
    _code(lambda: verify_mfa_attestation(idp.public_key_hex, att, NOW, "BOB", sa, seen_nonces=seen))
    assert not seen
    assert verify_mfa_attestation(idp.public_key_hex, att, NOW, "ALICE", sa, seen_nonces=seen)


def test_missing_or_wrong_lane_marker():
    idp, sa, _ = _setup()
    att = idp.issue_mfa_attestation("ALICE", sa, NOW)
    no_lane = {k: v for k, v in att.items() if k != "lane"}
    assert _code(lambda: verify_mfa_attestation(idp.public_key_hex, no_lane, NOW, "ALICE", sa)) == "MFA_SHAPE_INVALID"
    prod = dict(att, lane="PROD")
    assert _code(lambda: verify_mfa_attestation(idp.public_key_hex, prod, NOW, "ALICE", sa)) == "MFA_LANE_MARKER_MISSING"


def test_session_must_belong_to_person_on_issue():
    idp, sa, _ = _setup()
    with pytest.raises(ValueError):
        idp.issue_mfa_attestation("BOB", sa, NOW)


def test_two_person_approval_ok():
    idp, sa, sb = _setup()
    mat = build_two_person_approval(idp, "ALICE", sa, "BOB", sb, NOW)
    assert mat["lane"] == "TEST"
    assert mat["requester"]["login"] != mat["approver"]["login"]
    assert idp.verify(mat["requester"]["mfa"], NOW, "ALICE", sa)
    assert idp.verify(mat["approver"]["mfa"], NOW, "BOB", sb)


def test_two_person_refusals():
    idp, sa, sb = _setup()
    sa2 = idp.open_session("ALICE")
    for args, code in [(("ALICE", sa, "ALICE", sa2), "SAME_PERSON"),
                       (("ALICE", sa, "BOB", sa), "SAME_SESSION"),
                       (("ALICE", sa, "BOB", sa2), "SESSION_OWNER_MISMATCH")]:
        with pytest.raises(TwoPersonError, match=code):
            build_two_person_approval(idp, *args, NOW)
