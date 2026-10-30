"""REQ-007 / S2.1 AC-1..3: S16 service transitions conform to the S12 transition contract."""
from datetime import timedelta

from business_ai_gateway.phase2.change.types import Authorization, Lifecycle
from tests.phase2.s16_helpers import NOW, approve, build_env, propose


def test_propose_validate_approve_claim_and_repeated_claim_follow_s12_states():
    env = build_env()
    snap = propose(env)
    proposed = env.store.get(snap.change_id)
    assert proposed.s12_record.lifecycle is Lifecycle.VALIDATED
    assert proposed.s12_record.authorization is Authorization.NONE

    approve(env, snap)
    approved = env.store.get(snap.change_id)
    assert approved.s12_record.authorization is Authorization.APPROVED
    first = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert first.value is not None
    claimed = env.store.get(snap.change_id)
    assert claimed.s12_record.authorization is Authorization.CLAIMED
    repeated = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=3))
    assert repeated.error is not None
    assert env.store.claim_count == 1 and env.apply_port.calls == 1


def test_reject_and_expire_are_distinct_terminal_lifecycle_transitions():
    rejected_env = build_env()
    rejected_snapshot = propose(rejected_env)
    page = rejected_env.approval_service.open_preview(rejected_env.approver, rejected_env.session,
        rejected_snapshot.change_id, now=NOW)
    assert page.error is None
    rejected = rejected_env.approval_service.submit_decision(rejected_env.approver, rejected_env.session,
        page.value.decision_ref, "REJECT", confirmation_text="", origin="https://127.0.0.1:8443",
        referer="https://127.0.0.1:8443/approval/", now=NOW + timedelta(seconds=1))
    assert rejected.value is not None and rejected.value.decision == "REJECT"
    assert rejected_env.store.get(rejected_snapshot.change_id).s12_record.authorization is Authorization.NONE
    assert rejected_env.store.get(rejected_snapshot.change_id).s12_record.lifecycle is Lifecycle.REJECTED

    expired_env = build_env()
    expired_snapshot = propose(expired_env)
    expiry_time = expired_snapshot.expires_at + timedelta(microseconds=1)
    expired = expired_env.core.expire(expired_snapshot.change_id, now=expiry_time)
    assert expired.value is not None
    assert expired.value.s12_record.lifecycle is Lifecycle.EXPIRED_QUEUED


def test_requester_class_cannot_take_approver_decision_transition():
    env = build_env()
    snap = propose(env)
    page = env.approval_service.open_preview(env.approver, env.session, snap.change_id, now=NOW)
    assert page.error is None
    result = env.core.decide(env.requester, env.session, page.value.decision_ref, "APPROVE",
        confirmation_text="", origin="https://127.0.0.1:8443",
        referer="https://127.0.0.1:8443/approval/", now=NOW + timedelta(seconds=1))
    assert result.error is not None
    assert env.store.get(snap.change_id).approval is None
