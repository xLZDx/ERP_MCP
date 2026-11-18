"""Contract §11 crash-window mappings to the offline S12 transition reducer.

These tests exercise a deterministic local state model only. They do not claim that a
database transaction, durable ledger restore, checkpoint service, or real COM writer
survives a process crash.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

import business_ai_gateway.phase2.change as ch
from business_ai_gateway.phase2.change import (
    Authorization,
    CallerClass,
    CallOwnership,
    Dispatch,
    EffectKind,
    ErrorCode,
    Event,
    Execution,
    Hold,
    HoldCause,
    Lifecycle,
    Reservation,
    TokenState,
    Verification,
    apply_transition,
)
from tests.phase2 import _change_helpers as h
from tests.phase2._change_helpers import (
    T0,
    applied,
    applying,
    claimed,
    dispatched,
    good,
    proposed,
    triage,
    unknown,
)


def step(record, event, now=T0, **over):
    return apply_transition(record, event, h.good(event, record, now, **over))


def ok(result, transition=None):
    assert type(result) is ch.Applied, result
    if transition is not None:
        assert result.transition == transition
    return result.record


def refused(result, code, transition=None):
    assert type(result) is ch.Refusal, result
    assert result.code is ErrorCode(code)
    if transition is not None:
        assert result.transition == transition


def test_s12_w1_before_intent_has_no_transitionable_record():
    # The pure reducer cannot persist an intent: absent input remains a refusal, not a record.
    result = apply_transition(None, Event.VALIDATE, good(Event.VALIDATE, None))
    assert type(result) is ch.Refusal
    assert result.code is ErrorCode.SCHEMA_INVALID


def test_s12_w2_unapproved_intent_has_no_reservation_or_locks():
    result = step(proposed(), Event.VALIDATE)
    record = ok(result, "T2")
    assert record.lifecycle is Lifecycle.VALIDATED
    assert record.authorization is Authorization.NONE
    assert (record.reservation, record.target_lock, record.key_lock, record.lease) == (
        Reservation.NONE, False, False, False)


def test_s12_w3_failed_claim_guard_leaves_the_local_input_unchanged():
    before = h.approved()
    result = step(before, Event.CLAIM, target_lock_owner="another-change")
    refused(result, "LOCK_BUSY", "T5")
    assert before.authorization is Authorization.APPROVED
    assert (before.reservation, before.target_lock, before.key_lock, before.lease) == (
        Reservation.NONE, False, False, False)
    # This proves reducer purity on refusal, not rollback of a real in-flight transaction.


def test_s12_w4_expired_claim_unwinds_without_begin_apply():
    record = ok(step(claimed(), Event.RELEASE_CLAIM, now=T0 + timedelta(seconds=120)), "T5x")
    assert record.authorization is Authorization.APPROVED
    assert record.execution is Execution.NOT_STARTED
    assert record.token is TokenState.SUPERSEDED
    assert (record.target_lock, record.key_lock, record.lease, record.reservation) == (
        False, False, False, Reservation.RELEASED)
    refused(step(record, Event.BEGIN_APPLY), "TICKET_SUPERSEDED", "T6")


def test_s12_w5_applying_without_checkpoint_permit_unwinds_via_t6r():
    before = applying()
    result = step(before, Event.PERMIT_NOT_ISSUED)
    record = ok(result, "T6r")
    assert before.execution is Execution.APPLYING and before.dispatch is Dispatch.NOT_PERMITTED
    assert record.execution is Execution.NOT_STARTED
    assert record.authorization is Authorization.APPROVED and record.token is TokenState.SUPERSEDED
    assert (record.target_lock, record.key_lock, record.lease, record.reservation) == (
        False, False, False, Reservation.RELEASED)


def test_s12_w5b_same_generation_replay_does_not_dispatch_or_create_a_second_permit():
    before = applying()
    replay = step(before, Event.BEGIN_APPLY)
    replayed = ok(replay, "T6")
    assert replayed is before
    assert replay.effects == (EffectKind.REPLAY_EXISTING_TICKET,)
    assert replayed.claim_generation == before.claim_generation
    assert replayed.dispatch is Dispatch.NOT_PERMITTED
    permitted = ok(step(replayed, Event.ISSUE_PERMIT), "T6p")
    assert permitted.claim_generation == before.claim_generation
    assert permitted.dispatch is Dispatch.PERMITTED
    refused(step(permitted, Event.ISSUE_PERMIT), "PERMIT_MISSING", "T6p")


def test_s12_w5c_kill_switch_cancel_wins_before_dispatched_and_invalidates_permit():
    permitted = applying(Dispatch.PERMITTED)
    result = step(permitted, Event.CANCEL_PERMIT)
    cancelled = ok(result, "T6c")
    assert cancelled.dispatch is Dispatch.CANCELLED_UNDISPATCHED
    assert cancelled.execution is Execution.NOT_STARTED
    assert EffectKind.INVALIDATE_PERMIT in result.effects
    assert (cancelled.target_lock, cancelled.key_lock, cancelled.lease, cancelled.reservation) == (
        False, False, False, Reservation.RELEASED)
    refused(step(cancelled, Event.MARK_DISPATCHED), "PERMIT_MISSING", "T6p")


def test_s12_w5c_expired_permit_is_cancelled_by_recovery_without_dispatch():
    permitted = applying(Dispatch.PERMITTED)
    result = apply_transition(
        permitted,
        Event.CANCEL_PERMIT,
        h.good(Event.CANCEL_PERMIT, permitted, T0 + timedelta(seconds=61), kill=h.SWITCH_OFF),
    )
    cancelled = ok(result, "T6c")
    assert cancelled.dispatch is Dispatch.CANCELLED_UNDISPATCHED
    assert cancelled.execution is Execution.NOT_STARTED
    assert EffectKind.INVALIDATE_PERMIT in result.effects
    refused(step(cancelled, Event.MARK_DISPATCHED), "PERMIT_MISSING", "T6p")


@pytest.mark.parametrize("window", ["W5d-dispatched-before-call", "W6-call-sent-no-response"])
def test_s12_w5d_w6_uncertain_call_keeps_ownership_hold_and_forbids_cancel(window):
    del window  # parameter names are the contract rows covered by this identical local transition.
    sent = dispatched()
    result = step(sent, Event.CALL_UNKNOWN)
    record = ok(result, "T9")
    assert record.execution is Execution.APPLY_UNKNOWN
    assert record.call_ownership is CallOwnership.POSSIBLY_EXECUTING
    assert (record.target_lock, record.key_lock, record.lease, record.reservation) == (
        True, True, True, Reservation.RESERVED)
    assert EffectKind.OPEN_HOLD_CALL_OWNERSHIP in result.effects
    refused(step(record, Event.CANCEL_PERMIT), "LOCK_BUSY", "T6c")


def test_s12_w7_response_not_ledgered_stays_unknown_until_proof_or_triage():
    before = unknown()
    aged = ok(step(before, Event.AGE_LIMIT), "T12")
    assert aged.execution is Execution.TRIAGE_REQUIRED
    assert aged.call_ownership is CallOwnership.POSSIBLY_EXECUTING
    assert (aged.target_lock, aged.key_lock, aged.lease, aged.reservation) == (
        True, True, True, Reservation.RESERVED)
    assert before.execution is Execution.APPLY_UNKNOWN


def test_s12_w8_applied_without_verification_keeps_target_lock_until_verified():
    before = applied(target_lock=True, key_lock=True)
    assert before.verification is Verification.NOT_VERIFIED
    assert before.target_lock is True
    verified = ok(step(before, Event.VERIFY_OK), "T13")
    assert verified.execution is Execution.APPLIED
    assert verified.verification is Verification.VERIFIED
    assert (verified.target_lock, verified.key_lock, verified.reservation) == (
        False, False, Reservation.CONSUMED)


def test_s12_w9_missing_checkpoint_refuses_permit_then_t6r_releases_claim():
    before = applying()
    refused(step(before, Event.ISSUE_PERMIT, checkpoint_covers_head=False),
            "CHECKPOINT_UNAVAILABLE", "T6p")
    assert before.dispatch is Dispatch.NOT_PERMITTED
    released = ok(step(before, Event.PERMIT_NOT_ISSUED), "T6r")
    assert released.dispatch is Dispatch.NOT_PERMITTED
    assert released.execution is Execution.NOT_STARTED
    assert (released.target_lock, released.key_lock, released.lease, released.reservation) == (
        False, False, False, Reservation.RELEASED)


def test_s12_w10_anchor_gap_hold_refuses_permit_and_never_reaches_dispatched():
    before = applying()
    anchor_gap = Hold("anchor-gap", HoldCause.ANCHOR_GAP, before.change_id)
    refused(step(before, Event.ISSUE_PERMIT, holds=(anchor_gap,)), "BASE_HOLD", "T6p")
    assert before.dispatch is Dispatch.NOT_PERMITTED
    refused(step(before, Event.MARK_DISPATCHED), "PERMIT_MISSING", "T6p")
    # The reducer accepts a hold as an input; it cannot verify a restored ledger/head hash itself.


def test_s12_w11_claim_hands_target_lock_to_repair_without_unlocking():
    result = step(h.repair_rec(), Event.CLAIM)
    repair = ok(result, "T5")
    assert EffectKind.HAND_LOCK_TO_REPAIR in result.effects
    assert repair.target_lock is True and repair.key_lock is True and repair.lease is True
    assert repair.reservation is Reservation.RESERVED


def test_s12_w11b_zero_effect_repair_handback_invalidates_auth_and_returns_lock():
    result = step(h.repair_live(claimed), Event.RELEASE_CLAIM)
    returned = ok(result, "T5x")
    assert {EffectKind.INVALIDATE_REPAIR_AUTH, EffectKind.HAND_LOCK_BACK_TO_PARENT} <= set(result.effects)
    assert returned.repair is None
    assert (returned.target_lock, returned.key_lock, returned.lease, returned.reservation) == (
        False, False, False, Reservation.RELEASED)
    # The pure result represents either side of the documented handback; it does not emulate DB atomicity.


@pytest.mark.parametrize("sensitive", [
    "payload=accounting-row-SECRET-1",
    "credential=Bearer runtime-secret-2",
    "tenant=foreign-tenant-3",
    "path=D:\\private\\ledger\\secret-4.db",
    "RuntimeError: token secret-5 at D:\\private\\source.py:99",
])
def test_s12_public_error_rendering_never_echoes_sensitive_input(sensitive):
    public = ch.render(sensitive)
    refusal = ch.Refusal(ErrorCode.SCHEMA_INVALID)
    assert public is ch.ERROR_INFO[ErrorCode.SCHEMA_INVALID]
    assert sensitive not in public.message
    assert sensitive not in repr(public)
    assert sensitive not in refusal.message
    assert sensitive not in repr(refusal)


@pytest.mark.parametrize("field,value", [
    ("comment", "payload=accounting-row-SECRET-1"),
    ("currency", "credential=Bearer runtime-secret-2"),
    ("organization_ref", "tenant=foreign-tenant-3"),
    ("supplier_document_number", "path=D:\\private\\ledger\\secret-4.db"),
    ("comment", "RuntimeError: token secret-5 at D:\\private\\source.py:99"),
])
def test_s12_parse_refusal_does_not_echo_sensitive_request_content(field, value):
    if field == "organization_ref":
        raw = h.raw_create(payload_over={field: value})
    elif field in {"comment", "currency"}:
        raw = h.raw_create(payload_over={field: value, "unknown_key": "force-safe-schema-refusal"})
    else:
        raw = h.raw_create(**{field: value})
    result = ch.parse_proposal(raw, h.ctx())
    refused(result, "SCOPE_MISMATCH" if field == "organization_ref" else "SCHEMA_INVALID")
    assert value not in result.message
    assert value not in repr(result)


@pytest.mark.parametrize("lane", [None, "PROD"])
def test_s12_proposal_parser_rejects_missing_or_non_test_lane(lane):
    result = ch.parse_proposal(h.raw_create(), h.ctx(lane=lane))
    refused(result, "SCHEMA_INVALID")


def test_s12_proposal_parser_rejects_uninitialized_missing_lane_without_raising():
    missing_lane = object.__new__(h.ProposalContext)
    result = ch.parse_proposal(h.raw_create(), missing_lane)
    refused(result, "SCHEMA_INVALID")


def test_s12_identity_evidence_is_test_lane_registry_backed_and_has_no_real_sink():
    from tests.phase2.s16_helpers import build_env

    env = build_env()
    requester_record = env.principals.current(env.requester.principal_id)
    approver_record = env.principals.current(env.approver.principal_id)
    target = env.targets.current(env.requester.scope)
    assert env.requester.lane == env.approver.lane == "TEST"
    assert requester_record is not None and requester_record.lane == "TEST"
    assert approver_record is not None and approver_record.lane == "TEST"
    assert target is not None and target.scope.target_class == "TEST"
    assert env.idp.authenticate(env.approver) is True
    assert env.idp.authenticate(env.requester) is False
    assert env.apply_port.calls == 0


@pytest.mark.parametrize("lane,target_class", [(None, "TEST"), ("PROD", "TEST"), ("TEST", "PROD")])
def test_s12_identity_adapter_refuses_missing_or_non_test_principal_scope(lane, target_class):
    from tests.phase2.s16_helpers import build_env

    env = build_env()
    candidate = replace(env.approver, lane=lane,
                        scope=replace(env.approver.scope, target_class=target_class))
    assert env.idp.authenticate(candidate) is False
    assert env.idp.issue(candidate, env.clock.now()) is None
    assert env.apply_port.calls == 0


def test_s12_identity_registry_requires_test_lane_for_current_epoch():
    from tests.phase2.s16_helpers import build_env

    env = build_env()
    current = env.principals.current(env.approver.principal_id)
    assert current is not None
    env.principals.put(replace(current, lane=None))
    assert env.principals.epochs_current(((env.approver.principal_id, env.approver.epoch),)) is False
    assert env.idp.authenticate(env.approver) is False
    assert env.apply_port.calls == 0


def test_s12_identity_registry_refuses_a_principal_person_mapping_change():
    from tests.phase2.s16_helpers import build_env

    env = build_env()
    env.principals.alias_person(env.approver.principal_id, "different-synthetic-person")
    assert env.idp.authenticate(env.approver) is False
    assert env.apply_port.calls == 0


@pytest.mark.parametrize("lane", [None, "PROD"])
def test_s12_core_apply_refuses_missing_or_non_test_lane_before_claim_or_sink(lane):
    from tests.phase2.s16_helpers import build_env, propose

    env = build_env(permissive=True)
    snapshot = propose(env)
    caller = replace(env.requester, lane=lane)
    result = env.core.apply(caller, snapshot.change_id, now=env.clock.now())
    assert result.error is ErrorCode.NOT_ENTITLED
    assert env.store.claim_count == 0
    assert env.apply_port.calls == 0


def test_s12_two_person_operator_resolution_requires_distinct_synthetic_identities():
    state = triage()
    evidence = h.good(Event.OPERATOR_RESOLVE, state)
    result = step(state, Event.OPERATOR_RESOLVE)
    resolved = ok(result, "T16")
    assert resolved.execution in (Execution.FAILED_APPLY, Execution.APPLIED)
    assert evidence.operator_class is CallerClass.OPERATOR
    assert evidence.witness_class is CallerClass.RECOVERY_WITNESS
    assert evidence.operator_person_id != evidence.witness_person_id
    assert evidence.operator_person_id != state.requester_person_id
    assert evidence.witness_person_id != state.requester_person_id
    same_person = replace(evidence, witness_person_id=evidence.operator_person_id)
    refused(apply_transition(state, Event.OPERATOR_RESOLVE, same_person),
            ErrorCode.APPROVER_NOT_INDEPENDENT, "T16")
