"""S12 crash-window crosswalk for the deterministic offline transition reducer.

These cases verify the local reducer model only. They do not establish persistence,
transactional atomicity, durable recovery, or behavior of a real ERP writer.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

import business_ai_gateway.phase2.change as ch
from business_ai_gateway.phase2.change import (
    Authorization,
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
from tests.phase2._change_helpers import T0, applied, applying, claimed, dispatched, proposed, unknown


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


def test_s12_w1_absent_record_cannot_become_transitionable():
    result = apply_transition(None, Event.VALIDATE, h.good(Event.VALIDATE, None))
    refused(result, "SCHEMA_INVALID")


def test_s12_w2_unapproved_intent_has_no_reservation_or_locks():
    record = ok(step(proposed(), Event.VALIDATE), "T2")
    assert record.lifecycle is Lifecycle.VALIDATED
    assert record.authorization is Authorization.NONE
    assert (record.reservation, record.target_lock, record.key_lock, record.lease) == (
        Reservation.NONE, False, False, False)


def test_s12_w3_failed_claim_guard_leaves_local_input_unchanged():
    before = h.approved()
    refused(step(before, Event.CLAIM, target_lock_owner="another-change"), "LOCK_BUSY", "T5")
    assert before.authorization is Authorization.APPROVED
    assert (before.reservation, before.target_lock, before.key_lock, before.lease) == (
        Reservation.NONE, False, False, False)
    # Reducer purity only; this does not prove rollback of a database transaction.


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
    record = ok(step(before, Event.PERMIT_NOT_ISSUED), "T6r")
    assert before.execution is Execution.APPLYING and before.dispatch is Dispatch.NOT_PERMITTED
    assert record.execution is Execution.NOT_STARTED
    assert record.authorization is Authorization.APPROVED and record.token is TokenState.SUPERSEDED
    assert (record.target_lock, record.key_lock, record.lease, record.reservation) == (
        False, False, False, Reservation.RELEASED)


def test_s12_w5b_same_generation_replay_does_not_dispatch_or_create_second_permit():
    before = applying()
    replay = ok(step(before, Event.BEGIN_APPLY), "T6")
    assert replay is before
    permitted = ok(step(replay, Event.ISSUE_PERMIT), "T6p")
    assert permitted.claim_generation == before.claim_generation
    assert permitted.dispatch is Dispatch.PERMITTED
    refused(step(permitted, Event.ISSUE_PERMIT), "PERMIT_MISSING", "T6p")


def test_s12_w5c_cancel_before_dispatch_invalidates_permit():
    permitted = applying(Dispatch.PERMITTED)
    result = step(permitted, Event.CANCEL_PERMIT)
    cancelled = ok(result, "T6c")
    assert cancelled.dispatch is Dispatch.CANCELLED_UNDISPATCHED
    assert cancelled.execution is Execution.NOT_STARTED
    assert EffectKind.INVALIDATE_PERMIT in result.effects
    assert (cancelled.target_lock, cancelled.key_lock, cancelled.lease, cancelled.reservation) == (
        False, False, False, Reservation.RELEASED)
    refused(step(cancelled, Event.MARK_DISPATCHED), "PERMIT_MISSING", "T6p")


def test_s12_w5c_expired_permit_recovers_with_switch_off_without_dispatch():
    permitted = applying(Dispatch.PERMITTED)
    result = apply_transition(
        permitted, Event.CANCEL_PERMIT,
        h.good(Event.CANCEL_PERMIT, permitted, T0 + timedelta(seconds=61), kill=h.SWITCH_OFF),
    )
    cancelled = ok(result, "T6c")
    assert cancelled.dispatch is Dispatch.CANCELLED_UNDISPATCHED
    assert cancelled.execution is Execution.NOT_STARTED
    assert EffectKind.INVALIDATE_PERMIT in result.effects
    refused(step(cancelled, Event.MARK_DISPATCHED), "PERMIT_MISSING", "T6p")


@pytest.mark.parametrize("window", ["W5d-dispatched-before-call", "W6-call-sent-no-response"])
def test_s12_w5d_w6_uncertain_call_preserves_ownership_hold_and_refuses_cancel(window):
    del window
    result = step(dispatched(), Event.CALL_UNKNOWN)
    record = ok(result, "T9")
    assert record.execution is Execution.APPLY_UNKNOWN
    assert record.call_ownership is CallOwnership.POSSIBLY_EXECUTING
    assert (record.target_lock, record.key_lock, record.lease, record.reservation) == (
        True, True, True, Reservation.RESERVED)
    assert EffectKind.OPEN_HOLD_CALL_OWNERSHIP in result.effects
    refused(step(record, Event.CANCEL_PERMIT), "LOCK_BUSY", "T6c")


def test_s12_w7_unledgered_response_stays_unknown_until_proof_or_triage():
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
    # Reducer consumes a hold input; it does not verify restored-ledger or head hashes.


def test_s12_w11_repair_claim_hands_lock_to_repair_without_unlocking():
    result = step(h.repair_rec(), Event.CLAIM)
    repair = ok(result, "T5")
    assert EffectKind.HAND_LOCK_TO_REPAIR in result.effects
    assert repair.target_lock is True and repair.key_lock is True and repair.lease is True
    assert repair.reservation is Reservation.RESERVED


def test_s12_w11b_zero_effect_handback_invalidates_auth_and_returns_lock():
    result = step(h.repair_live(claimed), Event.RELEASE_CLAIM)
    returned = ok(result, "T5x")
    assert {EffectKind.INVALIDATE_REPAIR_AUTH, EffectKind.HAND_LOCK_BACK_TO_PARENT} <= set(result.effects)
    assert returned.repair is None
    assert (returned.target_lock, returned.key_lock, returned.lease, returned.reservation) == (
        False, False, False, Reservation.RELEASED)
    # Reducer projection only; no database atomicity claim.


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


@pytest.mark.parametrize("lane", [None, "PROD"])
def test_s12_proposal_parser_rejects_missing_or_non_test_lane(lane):
    result = ch.parse_proposal(h.raw_create(), h.ctx(lane=lane))
    refused(result, "SCHEMA_INVALID")


def test_s12_proposal_parser_rejects_uninitialized_missing_lane_without_raising():
    missing_lane = object.__new__(h.ProposalContext)
    result = ch.parse_proposal(h.raw_create(), missing_lane)
    refused(result, "SCHEMA_INVALID")