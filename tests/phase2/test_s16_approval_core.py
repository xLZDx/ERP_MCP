"""REQ-007/008: core owns decisions; approval, revocation and claim are externally observable."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from threading import Barrier

import pytest

from business_ai_gateway.phase2.change.errors import ErrorCode
from business_ai_gateway.phase2.change.killswitch import KillMode, SwitchReading
from business_ai_gateway.phase2.change.proposal import (
    approval_canonical_text,
    digest_of_canonical_text,
)
from business_ai_gateway.phase2.change.transitions import BeginApplyEvidence
from erp_mcp_s16.contracts import ClaimToken, PrincipalRole, TokenClass, canonical_preview_bytes
from erp_mcp_s16.fakes import FakeBeginApplyEvidencePort, InMemoryChangeStore
from tests.phase2.s16_helpers import NOW, approve, build_env, positive_begin_apply_evidence, propose


def test_server_issued_preview_bytes_match_digest_and_valid_human_approval_is_one_use():
    env = build_env(permissive=True)
    snap, page = approve(env)
    import hashlib
    assert page.canonical_preview_bytes == snap.canonical_preview_bytes
    assert hashlib.sha256(page.canonical_preview_bytes).hexdigest() == page.preview_digest == snap.preview_digest
    saved = env.store.get(snap.change_id)
    assert saved.approval is not None and saved.approval.decision == "APPROVE"
    assert page.lifecycle_status == "VALIDATED"
    assert page.authorization_status == "NONE"
    assert page.snapshot_version == snap.version
    assert page.created_at == snap.proposal.created_at
    assert page.approver_person_label == "Approver One"
    assert page.decision_allowed is True
    replay = env.approval_service.submit_decision(env.approver, env.session, page.decision_ref, "APPROVE",
        confirmation_text="", origin="https://127.0.0.1:8443", referer="https://127.0.0.1:8443/approval/",
        now=NOW + timedelta(seconds=2))
    assert replay.error is ErrorCode.APPROVAL_NONCE_INVALID
    assert env.store.get(snap.change_id).approval == saved.approval


def test_approver_alias_for_requester_person_is_refused_before_any_apply_call():
    env = build_env(permissive=True)
    snap = propose(env)
    opened = env.approval_service.open_preview(env.approver, env.session, snap.change_id, now=NOW)
    assert opened.error is None
    env.principals.alias_person(env.approver.principal_id, env.requester.person_id)
    result = env.core.decide(env.approver, env.session, opened.value.decision_ref, "APPROVE",
        origin="https://127.0.0.1:8443", referer="https://127.0.0.1:8443/approval/",
        confirmation_text="", now=NOW + timedelta(seconds=1))
    assert result.error is ErrorCode.APPROVER_NOT_INDEPENDENT
    assert env.store.get(snap.change_id).approval is None
    assert env.apply_port.calls == 0


@pytest.mark.parametrize("mutation,expected", [
    ("kill", ErrorCode.KILL_SWITCH_ACTIVE),
    ("version", ErrorCode.STALE_VERSION),
    ("requester_epoch", ErrorCode.EPOCH_CHANGED),
    ("approver_revoked", ErrorCode.APPROVAL_VOIDED),
    ("scope", ErrorCode.SCOPE_MISMATCH),
])
def test_apply_rechecks_approval_dependencies_and_target_before_apply(mutation, expected):
    env = build_env()
    snap, _ = approve(env)
    if mutation == "kill":
        env.kill_switch.value = SwitchReading(available=True, mode=KillMode.STOP_ADMIT)
    elif mutation == "version":
        env.targets.change_version(snap.scope, replace(env.targets.current(snap.scope).version, value="v2"))
    elif mutation == "requester_epoch":
        env.principals.bump_epoch(env.requester.principal_id)
    elif mutation == "approver_revoked":
        env.principals.revoke(env.approver.principal_id)
    requester = env.requester
    if mutation == "scope":
        requester = replace(env.requester, scope=replace(env.requester.scope, base_fingerprint="base-2"))
    result = env.change_service.apply(requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert result.error is expected
    assert env.apply_port.calls == 0
    assert env.store.claim_count == 0


def test_parallel_apply_claims_once_and_calls_apply_port_once():
    env = build_env()
    snap, _ = approve(env)
    workers = 8
    gate = Barrier(workers)

    def invoke(_):
        gate.wait(timeout=2)
        return env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(invoke, range(workers)))
    assert sum(outcome.value is not None for outcome in outcomes) == 1
    assert env.store.claim_count == 1
    assert env.apply_port.calls == 1


def test_wrong_token_class_cannot_approve_or_apply():
    env = build_env()
    snap = propose(env)
    wrong = replace(env.approver, token_class=TokenClass.CHAT_WRITE, roles=frozenset({PrincipalRole.REQUESTER}))
    result = env.approval_service.open_preview(wrong, env.session, snap.change_id, now=NOW)
    assert result.error is not None
    apply = env.core.apply(replace(env.requester, token_class=TokenClass.READ_ONLY), snap.change_id, now=NOW)
    assert apply.error is ErrorCode.NOT_ENTITLED
    assert env.apply_port.calls == 0


def test_forged_requester_token_epoch_is_still_refused_before_claim():
    env = build_env()
    snap, _ = approve(env)
    forged = replace(env.requester, epoch=env.requester.epoch + 1)
    result = env.change_service.apply(forged, snap.change_id, now=NOW + timedelta(seconds=2))
    assert result.error is ErrorCode.EPOCH_CHANGED
    assert env.store.claim_count == 0
    assert env.apply_port.calls == 0


def test_cross_session_decision_reference_and_exact_nonce_expiry_are_refused():
    env = build_env(permissive=True)
    snap = propose(env)
    page = env.approval_service.open_preview(env.approver, env.session, snap.change_id, now=NOW)
    assert page.error is None
    second_session = env.idp.issue(env.approver, NOW + timedelta(seconds=1))
    assert second_session is not None
    cross_session = env.approval_service.submit_decision(second_session.principal, second_session,
        page.value.decision_ref, "APPROVE", confirmation_text="", origin="https://127.0.0.1:8443",
        referer="https://127.0.0.1:8443/approval/", now=NOW + timedelta(seconds=2))
    assert cross_session.error is ErrorCode.APPROVAL_NONCE_INVALID
    exact_expiry = env.approval_service.submit_decision(env.approver, env.session, page.value.decision_ref,
        "APPROVE", confirmation_text="", origin="https://127.0.0.1:8443",
        referer="https://127.0.0.1:8443/approval/", now=page.value.expires_at)
    assert exact_expiry.error is ErrorCode.APPROVAL_EXPIRED
    assert env.store.get(snap.change_id).approval is None


def test_core_rejects_stored_canonical_preview_tampering_even_with_permissive_decision_store():
    env = build_env(permissive=True)
    snap = propose(env)
    page = env.approval_service.open_preview(env.approver, env.session, snap.change_id, now=NOW)
    assert page.error is None
    stored = env.store.get(snap.change_id)
    env.store._receipts[snap.change_id] = replace(
        stored, snapshot=replace(stored.snapshot, canonical_preview_bytes=stored.snapshot.canonical_preview_bytes + b" "))
    result = env.approval_service.submit_decision(env.approver, env.session, page.value.decision_ref,
        "APPROVE", confirmation_text="", origin="https://127.0.0.1:8443",
        referer="https://127.0.0.1:8443/approval/", now=NOW + timedelta(seconds=1))
    assert result.error is ErrorCode.DIGEST_MISMATCH
    assert env.store.get(snap.change_id).approval is None


def test_apply_exception_becomes_unknown_and_cannot_retry_the_apply_port():
    env = build_env()
    snap, _ = approve(env)
    env.apply_port.fail = True
    first = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    second = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=3))
    assert first.error is ErrorCode.APPLY_UNKNOWN
    assert second.error is not None
    assert env.store.claim_count == 1
    assert env.apply_port.calls == 1
    unknown = env.store.get(snap.change_id).s12_record
    from business_ai_gateway.phase2.change.types import Authorization, Execution, TokenState
    # T6 is durably recorded before the port call; an uncertain exception keeps that
    # applying record latched so a retry cannot release and claim again.
    assert unknown.execution is Execution.APPLYING
    assert unknown.authorization is Authorization.CLAIMED
    assert unknown.token is TokenState.CONSUMED


def test_approver_session_expires_at_the_fifteen_minute_boundary():
    env = build_env()
    assert env.idp.validate_session(env.session, NOW + timedelta(minutes=15)) is None


def test_missing_begin_apply_reader_fails_closed_before_apply_port():
    env = build_env(positive_begin_apply=False)
    snap, _ = approve(env)
    result = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert result.error is ErrorCode.CHECKPOINT_UNAVAILABLE
    assert env.apply_port.calls == 0
    _assert_claim_released(env, snap.change_id)


def test_begin_apply_reader_exception_releases_claim_before_refusing():
    class UnavailableReader:
        def read(self, receipt, claim, now):
            raise OSError("source evidence unavailable")

    env = build_env(positive_begin_apply=False, begin_apply_evidence=UnavailableReader())
    snap, _ = approve(env)
    result = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert result.error is ErrorCode.CHECKPOINT_UNAVAILABLE
    assert env.apply_port.calls == 0
    _assert_claim_released(env, snap.change_id)


@pytest.mark.parametrize("evidence,expected", [
    ("period_closed", ErrorCode.PERIOD_CLOSED),
    ("period_unobserved", ErrorCode.DIGEST_MISMATCH),
    ("state_changed", ErrorCode.DIGEST_MISMATCH),
    ("writer_lock_missing", ErrorCode.LOCK_BUSY),
    ("ownership_missing", ErrorCode.AUDIT_UNAVAILABLE),
])
def test_begin_apply_source_evidence_guards_refuse_before_apply_port(evidence, expected):
    base = positive_begin_apply_evidence()
    changes = {
        "period_closed": {"period_closed": True, "period_observed_open": False},
        "period_unobserved": {"period_observed_open": False},
        "state_changed": {"state_digest_equal": False},
        "writer_lock_missing": {"writer_lock_held": False},
        "ownership_missing": {"ownership_row_committed": False},
    }[evidence]
    reader = FakeBeginApplyEvidencePort(replace(base, **changes))
    env = build_env(positive_begin_apply=False, begin_apply_evidence=reader)
    snap, _ = approve(env)
    result = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert result.error is expected
    assert env.apply_port.calls == 0
    _assert_claim_released(env, snap.change_id)


def _assert_claim_released(env, change_id):
    from business_ai_gateway.phase2.change.types import (
        Authorization,
        Execution,
        Reservation,
        TokenState,
    )

    record = env.store.get(change_id).s12_record
    assert env.store.claim_count == 0
    assert record.authorization is Authorization.APPROVED
    assert record.execution is Execution.NOT_STARTED
    assert record.token is TokenState.SUPERSEDED
    assert record.reservation is Reservation.RELEASED


def test_t6_guard_refusal_releases_claim_and_explicit_retry_claims_new_generation():
    reader = FakeBeginApplyEvidencePort(replace(
        positive_begin_apply_evidence(), period_observed_open=False))
    env = build_env(positive_begin_apply=False, begin_apply_evidence=reader)
    snap, _ = approve(env)

    refused = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert refused.error is ErrorCode.DIGEST_MISMATCH
    assert env.apply_port.calls == 0
    _assert_claim_released(env, snap.change_id)

    env.core.begin_apply_evidence = FakeBeginApplyEvidencePort(positive_begin_apply_evidence())
    retried = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=3))
    assert retried.value is not None
    assert env.apply_port.calls == 1
    record = env.store.get(snap.change_id).s12_record
    assert record.claim_generation == 2
    assert env.store.claim_count == 1


@pytest.mark.parametrize("release_failure", ["raises", "false_ack", "lying_ack"])
def test_release_failure_fails_closed_then_reconciles_before_a_fresh_claim(release_failure):
    from erp_mcp_s16.fakes import InMemoryChangeStore

    class UnreliableReleaseStore(InMemoryChangeStore):
        def __init__(self):
            super().__init__()
            self.fail_release = True
            self.claim_tokens = []

        def claim_once(self, *args, **kwargs):
            result = super().claim_once(*args, **kwargs)
            if hasattr(result, "token"):
                self.claim_tokens.append(result.token)
            return result

        def release_claim(self, *args, **kwargs):
            if self.fail_release:
                if release_failure == "raises":
                    raise OSError("storage unavailable")
                if release_failure == "false_ack":
                    return False
                return True  # maliciously claims success without changing the stored receipt
            return super().release_claim(*args, **kwargs)

    store = UnreliableReleaseStore()
    bad_reader = FakeBeginApplyEvidencePort(replace(
        positive_begin_apply_evidence(), writer_lock_held=False))
    env = build_env(store=store, positive_begin_apply=False, begin_apply_evidence=bad_reader)
    snap, _ = approve(env)

    refused = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert refused.error is ErrorCode.AUDIT_UNAVAILABLE
    assert env.apply_port.calls == 0
    assert store.claim_count == 1
    assert store.get(snap.change_id).s12_record.authorization.value == "CLAIMED"
    assert len(store.claim_tokens) == 1

    store.fail_release = False
    env.core.begin_apply_evidence = FakeBeginApplyEvidencePort(positive_begin_apply_evidence())
    retried = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=3))
    assert retried.value is not None
    assert env.apply_port.calls == 1
    assert store.claim_count == 1
    assert len(store.claim_tokens) == 2
    assert store.claim_tokens[0] != store.claim_tokens[1]
    assert store.get(snap.change_id).s12_record.claim_generation == 2


def test_begin_apply_core_overwrites_source_claim_generation_and_identity_facts():
    forged = replace(positive_begin_apply_evidence(), generation=77, caller=None,
                     own_change=False, epoch_deps_equal_claim_epoch=False,
                     fingerprint_authenticated=False, version_equals_approved=False)
    env = build_env(positive_begin_apply=False,
                    begin_apply_evidence=FakeBeginApplyEvidencePort(forged))
    snap, _ = approve(env)
    result = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert result.value is not None
    assert env.apply_port.calls == 1


def test_restart_without_in_memory_issuance_anchor_fails_closed():
    from erp_mcp_s16.core import S16Core

    env = build_env()
    snap, _ = approve(env)
    restarted = S16Core(store=env.store, principals=env.principals, targets=env.targets,
                        kill_switch=env.kill_switch, apply_port=env.apply_port,
                        verify_port=env.verify_port,
                        begin_apply_evidence=FakeBeginApplyEvidencePort(positive_begin_apply_evidence()),
                        clock=env.clock)
    result = restarted.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert result.error is ErrorCode.APPROVAL_VOIDED
    assert env.apply_port.calls == 0


def test_stale_claim_token_from_store_never_reaches_evidence_or_apply_port():
    from erp_mcp_s16.contracts import Claimed

    class StaleClaimStore(InMemoryChangeStore):
        def claim_once(self, change_id, *, expected_version, expected_approval_digest,
                       claimant_id, s12_record=None):
            return Claimed(ClaimToken("stale-claim", change_id, expected_version + 1,
                                      expected_approval_digest))

    store = StaleClaimStore()
    evidence_port = FakeBeginApplyEvidencePort(positive_begin_apply_evidence())
    env = build_env(store=store, positive_begin_apply=False, begin_apply_evidence=evidence_port)
    snap, _ = approve(env)
    result = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert result.error is ErrorCode.CLAIM_EXPIRED
    assert evidence_port.calls == 0
    assert env.apply_port.calls == 0


def _self_consistent_replacement(receipt):
    """Forge a coherent replacement envelope to test the core's issuance anchor, not hash syntax."""
    import hashlib
    import json

    proposal = replace(receipt.proposal, reason="attacker supplied benign preview")
    preview = canonical_preview_bytes(proposal, target_version=receipt.target_version.value,
                                      target_class=receipt.scope.target_class)
    preview_digest = hashlib.sha256(preview).hexdigest()
    proposal = replace(proposal, preview_digest=preview_digest)
    nonce = json.loads(receipt.snapshot.approval_canonical_text)["approval_nonce"]
    approval_text = approval_canonical_text(proposal, approval_nonce=nonce,
                                             declared_target_class=receipt.scope.target_class)
    snapshot = replace(receipt.snapshot, proposal=proposal, canonical_preview_bytes=preview,
                       preview_digest=preview_digest, approval_canonical_text=approval_text,
                       approval_digest=digest_of_canonical_text(approval_text))
    return replace(receipt, proposal=proposal, snapshot=snapshot)


def test_self_consistent_resealed_preview_and_proposal_cannot_replace_issued_anchor():
    env = build_env(permissive=True)
    snap = propose(env)
    receipt = env.store.get(snap.change_id)
    env.store._receipts[snap.change_id] = _self_consistent_replacement(receipt)
    result = env.approval_service.open_preview(env.approver, env.session, snap.change_id, now=NOW)
    assert result.error is ErrorCode.DIGEST_MISMATCH
    assert env.store.get(snap.change_id).approval is None


def test_proposal_tampered_after_approval_is_refused_before_claim_and_apply():
    env = build_env()
    snap, _ = approve(env)
    receipt = env.store.get(snap.change_id)
    env.store._receipts[snap.change_id] = _self_consistent_replacement(receipt)
    result = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert result.error is ErrorCode.DIGEST_MISMATCH
    assert env.store.claim_count == 0
    assert env.apply_port.calls == 0


def test_expiry_during_begin_apply_observation_is_rechecked_before_apply():
    class AdvancingReader(FakeBeginApplyEvidencePort):
        def __init__(self, evidence, clock):
            super().__init__(evidence)
            self.clock = clock

        def read(self, receipt, claim, now):
            value = super().read(receipt, claim, now)
            self.clock.advance(timedelta(minutes=5))
            return value

    env = build_env(positive_begin_apply=False)
    reader = AdvancingReader(positive_begin_apply_evidence(), env.clock)
    env.core.begin_apply_evidence = reader
    snap, _ = approve(env)
    result = env.change_service.apply(env.requester, snap.change_id, now=NOW + timedelta(seconds=2))
    assert result.error is ErrorCode.APPROVAL_EXPIRED
    assert env.apply_port.calls == 0
