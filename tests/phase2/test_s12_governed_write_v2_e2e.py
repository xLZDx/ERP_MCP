"""Synthetic end-to-end journeys for the frozen S12 governed-write contract.

All state is in memory and all keys are synthetic. These tests do not connect to
PostgreSQL, Docker, COM, or a production service. The module is the E2E evidence
for bounded local dispatch state transitions, not formal runtime gate evidence.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
from threading import Event, Lock
import unittest

from business_ai_gateway.phase2 import ed25519
from business_ai_gateway.phase2.change.evidence import (
    CompletionProof,
    DispatchAttempt,
    DispatchReceipt,
    OutcomeEvidence,
    seal_record_fixture,
    verify_record_signature,
)
from business_ai_gateway.phase2.simulation.governed_write_v2 import (
    GovernedWriteCoordinator,
    GovernedWriteState,
    InMemoryGovernedLedger,
    SyntheticAuthorizationDecision,
    SyntheticNoInvocationGuard,
    SyntheticWriterResult,
)

_WRITER_SEED = bytes.fromhex("11" * 32)
_VERIFIER_SEED = bytes.fromhex("22" * 32)
_WRITER_KEY = ed25519.public_key_from_seed(_WRITER_SEED)
_VERIFIER_KEY = ed25519.public_key_from_seed(_VERIFIER_SEED)
_ZERO = "0" * 64
_WHEN = "2026-10-16T12:00:00.000000Z"
_CHANGE = "11111111-1111-4111-8111-111111111111"
_CALL = "22222222-2222-4222-8222-222222222222"
_CAS = "33333333-3333-4333-8333-333333333333"
_RECEIPT = "44444444-4444-4444-8444-444444444444"
_PROOF = "55555555-5555-4555-8555-555555555555"
_PERMIT = "abababab-abab-4bab-8bab-abababababab"


def _attempt(*, operation_kind: str = "POST") -> DispatchAttempt:
    return DispatchAttempt(
        tenant_id="tenant-test", company_id="company-test", organization_ref="org-test",
        base_fingerprint="base-fingerprint-test", change_id=_CHANGE,
        claim_generation=1, dispatch_generation=1, dispatch_cas_id=_CAS, call_id=_CALL,
        operation_kind=operation_kind, approval_digest=_ZERO,
        expected_target_ref=None if operation_kind == "CREATE_DRAFT" else "doc-17",
        auth_epoch=3, permit_id=_PERMIT, permit_digest=_ZERO,
        expected_pre_version=None if operation_kind == "CREATE_DRAFT" else "v4",
        writer_service_id="writer-test", writer_host_id="host-test",
        writer_process_instance_id="66666666-6666-4666-8666-666666666666",
        onec_session_instance_id="session-instance-test",
    )


def _record_fields(record_type: type, **updates: object) -> dict[str, object]:
    """Supply a complete closed schema while retaining readable fixture overrides."""
    fields: dict[str, object] = {name: "fixture" for name in record_type.SCHEMA}
    fields.update(updates)
    return fields


def _receipt(
    attempt: DispatchAttempt,
    *,
    no_effect: bool = False,
    no_effect_digest: str | None = None,
    returned_target_ref: str | None = None,
    returned_version: str | None = None,
) -> DispatchReceipt:
    fields = _record_fields(
        DispatchReceipt,
        receipt_version="1", tenant_id=attempt.tenant_id, company_id=attempt.company_id,
        organization_ref=attempt.organization_ref, base_fingerprint=attempt.base_fingerprint,
        target_class="CLONE", expected_target_ref=attempt.expected_target_ref,
        expected_pre_version=attempt.expected_pre_version, change_id=attempt.change_id,
        request_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", claim_generation=attempt.claim_generation,
        approval_digest_version="2", approval_digest=attempt.approval_digest,
        auth_epoch=attempt.auth_epoch, permit_id=attempt.permit_id,
        permit_digest=attempt.permit_digest, receipt_id=_RECEIPT,
        call_id=attempt.call_id, dispatch_generation=attempt.dispatch_generation,
        dispatch_cas_id=attempt.dispatch_cas_id, writer_service_id=attempt.writer_service_id,
        writer_host_id=attempt.writer_host_id, writer_process_instance_id=attempt.writer_process_instance_id,
        onec_session_id="session-test", onec_session_instance_id=attempt.onec_session_instance_id,
        operation_kind=attempt.operation_kind, started_at=_WHEN,
        write_invocation_stage="NOT_INVOKED" if no_effect else "INVOKED",
        call_returned=not no_effect, returned_at=None if no_effect else _WHEN,
        result_class="PRE_WRITE_NO_EFFECT" if no_effect else "CALL_RETURNED_SUCCESS",
        returned_target_ref=None if no_effect else (
            returned_target_ref or attempt.expected_target_ref or "doc-created"
        ),
        returned_version=None if no_effect else (returned_version or "v5"),
        no_effect_evidence_digest=(no_effect_digest or _ZERO) if no_effect else None,
        error_family=None, mapping_version="mapping-v1", configuration_fingerprint=_ZERO,
        approved_payload_digest=_ZERO, mapped_property_manifest_sha256=_ZERO,
        COM_operation_manifest_sha256=_ZERO, signer_key_id="writer-key", key_version="writer-key-v1",
        signer_role="writer_receipt", algorithm="Ed25519", signed_payload_digest=_ZERO, signature="",
    )
    return seal_record_fixture(DispatchReceipt, fields, _WRITER_SEED)  # type: ignore[return-value]


def _completion(attempt: DispatchAttempt) -> CompletionProof:
    fields = _record_fields(
        CompletionProof,
        proof_version="1", completion_proof_id=_PROOF, tenant_id=attempt.tenant_id,
        company_id=attempt.company_id, organization_ref=attempt.organization_ref,
        base_fingerprint=attempt.base_fingerprint, change_id=attempt.change_id,
        claim_generation=attempt.claim_generation, dispatch_generation=attempt.dispatch_generation,
        dispatch_cas_id=attempt.dispatch_cas_id, call_id=attempt.call_id,
        operation_kind=attempt.operation_kind,
        writer_process_instance_id=attempt.writer_process_instance_id,
        onec_session_instance_id=attempt.onec_session_instance_id,
        proof_class="WRITER_CALL_RETURNED", source_service_id=attempt.writer_service_id,
        source_host_id=attempt.writer_host_id,
        source_process_instance_id=attempt.writer_process_instance_id,
        source_session_instance_id=attempt.onec_session_instance_id,
        observed_session_instance_id=attempt.onec_session_instance_id,
        evidence_ref="synthetic-writer-return", evidence_digest=_ZERO, observed_at=_WHEN,
        signer_key_id="writer-key", key_version="writer-key-v1", signer_role="writer_receipt",
        algorithm="Ed25519", canonical_evidence_digest=_ZERO, signature="",
    )
    return seal_record_fixture(CompletionProof, fields, _WRITER_SEED)  # type: ignore[return-value]


def _outcome(
    attempt: DispatchAttempt,
    *,
    expected_effect_digest: str = _ZERO,
    observed_effect_digest: str = _ZERO,
    completion_proof_class: str = "WRITER_CALL_RETURNED",
    document_posting_state: str | None = None,
    version_relation: str | None = None,
    target_ref: str | None = None,
    pre_version: str | None = None,
    observed_version: str = "v5",
) -> OutcomeEvidence:
    fields = _record_fields(
        OutcomeEvidence,
        evidence_version="1", tenant_id=attempt.tenant_id, company_id=attempt.company_id,
        organization_ref=attempt.organization_ref, base_fingerprint=attempt.base_fingerprint,
        change_id=attempt.change_id, claim_generation=attempt.claim_generation,
        call_id=attempt.call_id, dispatch_receipt_id=_RECEIPT,
        approval_digest=attempt.approval_digest, verifier_service_id="verifier-test",
        verifier_host_id="verifier-host-test", signer_key_id="verifier-key",
        key_version="verifier-key-v1", algorithm="Ed25519", role="verification_worker",
        operation_kind=attempt.operation_kind, observed_at=_WHEN, read_session_id="independent-read-session",
        target_ref=target_ref or attempt.expected_target_ref or "doc-created",
        pre_version=pre_version or attempt.expected_pre_version, observed_version=observed_version,
        document_posting_state=document_posting_state or (
            "POSTED" if attempt.operation_kind == "POST" else "UNPOSTED"
        ), field_snapshot_digest=_ZERO,
        lines_digest=_ZERO, movement_multiset=(), registrar="registrar-test",
        register_catalogue_version="catalogue-v1", movement_count_by_register={},
        movement_digest_by_register={}, movement_multiset_digest=hashlib.sha256(b"[]").hexdigest(),
        expected_effect_digest=expected_effect_digest, observed_effect_digest=observed_effect_digest,
        fields_match=True,
        movements_match=True, version_relation=version_relation or (
            "CREATED" if attempt.operation_kind == "CREATE_DRAFT" else "ADVANCED"
        ), reader_health="HEALTHY",
        observation_complete=True, effect_presence="PRESENT", effect_identity="MATCH",
        completion_proof_class=completion_proof_class, attribution_result="PROVEN",
        attribution_evidence_ref="independent-attribution-test", uncertainties=(),
        canonical_evidence_digest=_ZERO, signature="",
    )
    return seal_record_fixture(OutcomeEvidence, fields, _VERIFIER_SEED)  # type: ignore[return-value]


def _no_invocation_guard(attempt: DispatchAttempt) -> SyntheticNoInvocationGuard:
    draft = SyntheticNoInvocationGuard(
        dispatch_cas_id=attempt.dispatch_cas_id, call_id=attempt.call_id,
        writer_process_instance_id=attempt.writer_process_instance_id,
        evidence_digest="", durable=True,
    )
    return replace(draft, evidence_digest=draft.calculated_digest())


class _Authorization:
    def __init__(self, *, revoke_at: str | None = None, deny_pre_cas: bool = False) -> None:
        self.revoke_at = revoke_at
        self.deny_pre_cas = deny_pre_cas
        self.phases: list[str] = []

    def check(self, attempt: DispatchAttempt, phase: str) -> SyntheticAuthorizationDecision:
        self.phases.append(phase)
        allowed = not (phase == "PRE_CAS" and self.deny_pre_cas) and phase != self.revoke_at
        return SyntheticAuthorizationDecision(
            allowed, attempt.auth_epoch, attempt.permit_id, attempt.permit_digest,
        )


class _Writer:
    def __init__(self, result: SyntheticWriterResult | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def invoke(self, attempt: DispatchAttempt) -> SyntheticWriterResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class _BlockingWriter:
    def __init__(self, result: SyntheticWriterResult) -> None:
        self.result = result
        self.entered = Event()
        self.release = Event()
        self._lock = Lock()
        self.calls = 0

    def invoke(self, attempt: DispatchAttempt) -> SyntheticWriterResult:
        with self._lock:
            self.calls += 1
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("synthetic writer release timed out")
        return self.result


def _system(
    authorization: _Authorization | None = None,
) -> tuple[GovernedWriteCoordinator, InMemoryGovernedLedger]:
    ledger = InMemoryGovernedLedger({
        "writer-key": ("writer_receipt", _WRITER_KEY),
        "verifier-key": ("verification_worker", _VERIFIER_KEY),
    })
    return GovernedWriteCoordinator(ledger, authorization or _Authorization()), ledger


class GovernedWriteE2ETests(unittest.TestCase):
    def test_dispatch_generation_is_fenced_and_fake_writer_is_invoked_once(self) -> None:
        attempt = _attempt()
        coordinator, ledger = _system()
        writer = _Writer(SyntheticWriterResult(_receipt(attempt), _completion(attempt), True))

        first = coordinator.dispatch(attempt, writer)
        duplicate = coordinator.dispatch(attempt, writer)

        self.assertIs(first.state, GovernedWriteState.APPLIED)
        self.assertEqual(duplicate, first)
        self.assertEqual(writer.calls, 1)
        self.assertEqual(first.invocation_count, 1)
        with self.assertRaisesRegex(ValueError, "GENERATION_ATTEMPT_CONFLICT"):
            ledger.begin(replace(attempt, call_id="77777777-7777-4777-8777-777777777777"))
        second_base_call = replace(
            attempt, change_id="88888888-8888-4888-8888-888888888888",
            claim_generation=2, dispatch_generation=2,
            dispatch_cas_id="99999999-9999-4999-8999-999999999999",
            call_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )
        with self.assertRaisesRegex(ValueError, "BASE_CALL_OWNERSHIP_HOLD"):
            ledger.begin(second_base_call)

    def test_concurrent_dispatch_of_one_generation_has_one_writer_call(self) -> None:
        attempt = _attempt()
        coordinator, ledger = _system()
        writer = _BlockingWriter(SyntheticWriterResult(_receipt(attempt), _completion(attempt), True))

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(coordinator.dispatch, attempt, writer)
            self.assertTrue(writer.entered.wait(timeout=5), "first dispatch did not reach fake writer")
            second = pool.submit(coordinator.dispatch, attempt, writer)
            second_snapshot = second.result(timeout=5)
            writer.release.set()
            first_snapshot = first.result(timeout=5)

        self.assertEqual(writer.calls, 1)
        self.assertIs(first_snapshot.state, GovernedWriteState.APPLIED)
        self.assertIs(second_snapshot.state, GovernedWriteState.DISPATCHED)
        final_snapshot = ledger.get(attempt)
        self.assertIs(final_snapshot.state, GovernedWriteState.APPLIED)
        self.assertEqual(final_snapshot.invocation_count, 1)

    def test_truthy_non_bool_call_may_have_started_cannot_prove_applied(self) -> None:
        attempt = _attempt()
        coordinator, ledger = _system()
        writer = _Writer(SyntheticWriterResult(_receipt(attempt), _completion(attempt), 1))  # type: ignore[arg-type]

        result = coordinator.dispatch(attempt, writer)

        self.assertIs(result.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertIsNot(result.state, GovernedWriteState.APPLIED)
        self.assertTrue(result.hold_retained)
        self.assertEqual(result.invocation_count, 1)
        self.assertEqual(writer.calls, 1)
        self.assertEqual(ledger.get(attempt), result)


    def test_signed_pre_write_no_effect_releases_hold_without_applying(self) -> None:
        attempt = _attempt()
        coordinator, ledger = _system()
        guard = _no_invocation_guard(attempt)
        writer = _Writer(SyntheticWriterResult(
            _receipt(attempt, no_effect=True, no_effect_digest=guard.evidence_digest),
            None, False, guard,
        ))

        result = coordinator.dispatch(attempt, writer)

        self.assertIs(result.state, GovernedWriteState.PRE_DISPATCH)
        self.assertFalse(result.hold_retained)
        self.assertEqual(result.invocation_count, 1)
        self.assertEqual(writer.calls, 1)
        next_attempt = replace(
            attempt, change_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", claim_generation=2,
            dispatch_generation=2, dispatch_cas_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            call_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        )
        self.assertIs(ledger.begin(next_attempt).state, GovernedWriteState.DISPATCHED)

    def test_no_effect_without_exact_durable_guard_or_with_possible_start_stays_unknown(self) -> None:
        variants = (
            ("missing", None, False),
            ("mismatched", replace(_no_invocation_guard(_attempt()), call_id="ffffffff-ffff-4fff-8fff-ffffffffffff"), False),
            ("possible-start", _no_invocation_guard(_attempt()), True),
        )
        for label, guard, may_have_started in variants:
            with self.subTest(label=label):
                attempt = _attempt()
                coordinator, ledger = _system()
                valid_guard = _no_invocation_guard(attempt)
                receipt = _receipt(
                    attempt, no_effect=True, no_effect_digest=valid_guard.evidence_digest,
                )
                selected_guard = guard
                if label == "mismatched":
                    selected_guard = replace(valid_guard, call_id="ffffffff-ffff-4fff-8fff-ffffffffffff")
                elif label == "possible-start":
                    selected_guard = valid_guard
                writer = _Writer(SyntheticWriterResult(
                    receipt, None, may_have_started, selected_guard,
                ))

                result = coordinator.dispatch(attempt, writer)

                self.assertIs(result.state, GovernedWriteState.APPLY_UNKNOWN)
                self.assertTrue(result.hold_retained)
                self.assertEqual(result.receipt, receipt)
                self.assertEqual(writer.calls, 1)

    def test_pre_cas_denial_creates_no_ledger_attempt_and_never_calls_writer(self) -> None:
        attempt = _attempt()
        authorization = _Authorization(deny_pre_cas=True)
        coordinator, ledger = _system(authorization)
        writer = _Writer(SyntheticWriterResult(_receipt(attempt), _completion(attempt), True))

        with self.assertRaisesRegex(ValueError, "AUTHORIZATION_PRE_CAS_DENIED"):
            coordinator.dispatch(attempt, writer)

        self.assertEqual(authorization.phases, ["PRE_CAS"])
        self.assertEqual(writer.calls, 0)
        with self.assertRaisesRegex(ValueError, "DISPATCH_ATTEMPT_NOT_FOUND"):
            ledger.get(attempt)

    def test_post_cas_revocation_is_unknown_held_and_never_calls_writer(self) -> None:
        attempt = _attempt()
        authorization = _Authorization(revoke_at="POST_CAS_PRE_WRITER")
        coordinator, ledger = _system(authorization)
        writer = _Writer(SyntheticWriterResult(_receipt(attempt), _completion(attempt), True))

        result = coordinator.dispatch(attempt, writer)

        self.assertIs(result.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertTrue(result.hold_retained)
        self.assertEqual(result.invocation_count, 1)
        self.assertEqual(authorization.phases, ["PRE_CAS", "POST_CAS_PRE_WRITER"])
        self.assertEqual(writer.calls, 0)
        self.assertEqual(ledger.get(attempt), result)

    def test_same_public_key_cannot_be_registered_for_writer_and_verifier_roles(self) -> None:
        with self.assertRaisesRegex(ValueError, "SYNTHETIC_SIGNER_KEY_REUSED_ACROSS_ROLES"):
            InMemoryGovernedLedger({
                "writer-key": ("writer_receipt", _WRITER_KEY),
                "verifier-key": ("verification_worker", _WRITER_KEY),
            })


    def test_exception_after_fake_writer_entry_is_unknown_held_and_never_retried(self) -> None:
        attempt = _attempt()
        coordinator, ledger = _system()
        writer = _Writer(error=RuntimeError("synthetic failure after call entry"))

        with self.assertRaisesRegex(RuntimeError, "after call entry"):
            coordinator.dispatch(attempt, writer)
        after_exception = ledger.get(attempt)
        duplicate = coordinator.dispatch(attempt, writer)

        self.assertIs(after_exception.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertTrue(after_exception.hold_retained)
        self.assertEqual(after_exception.invocation_count, 1)
        self.assertEqual(duplicate, after_exception)
        self.assertEqual(writer.calls, 1)

    def test_partial_receipt_is_retained_when_completion_proof_is_missing(self) -> None:
        attempt = _attempt()
        coordinator, ledger = _system()
        partial_receipt = _receipt(attempt)
        writer = _Writer(SyntheticWriterResult(partial_receipt, None, True))

        result = coordinator.dispatch(attempt, writer)

        self.assertIs(result.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertTrue(result.hold_retained)
        self.assertEqual(result.receipt, partial_receipt)
        self.assertIsNone(result.completion)
        self.assertEqual(ledger.get(attempt), result)

    def test_consumed_dispatch_recovers_unknown_and_cannot_be_retried(self) -> None:
        attempt = _attempt()
        coordinator, ledger = _system()
        ledger.begin(attempt)
        ledger.consume_dispatch(attempt)
        writer = _Writer(SyntheticWriterResult(_receipt(attempt), _completion(attempt), True))

        recovered = coordinator.recover_unresolved(attempt)
        after_duplicate_dispatch = coordinator.dispatch(attempt, writer)

        self.assertIs(recovered.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertTrue(recovered.hold_retained)
        self.assertEqual(recovered.invocation_count, 1)
        self.assertEqual(after_duplicate_dispatch, recovered)
        self.assertEqual(writer.calls, 0)

    def test_preconsume_dispatch_recovers_unknown_held_without_authorizing_writer(self) -> None:
        attempt = _attempt()
        authorization = _Authorization()
        coordinator, ledger = _system(authorization)
        ledger.begin(attempt)
        writer = _Writer(SyntheticWriterResult(_receipt(attempt), _completion(attempt), True))

        recovered = coordinator.recover_unresolved(attempt)
        after_duplicate_dispatch = coordinator.dispatch(attempt, writer)

        self.assertIs(recovered.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertTrue(recovered.hold_retained)
        self.assertEqual(recovered.invocation_count, 0)
        self.assertEqual(after_duplicate_dispatch, recovered)
        self.assertEqual(authorization.phases, ["PRE_CAS"])
        self.assertNotIn("POST_CAS_PRE_WRITER", authorization.phases)
        self.assertEqual(writer.calls, 0)

    def test_unknown_state_can_reconcile_signed_writer_evidence_without_calling_writer(self) -> None:
        attempt = _attempt()
        coordinator, ledger = _system()
        ledger.begin(attempt)
        ledger.consume_dispatch(attempt)
        coordinator.recover_unresolved(attempt)
        writer = _Writer()

        reconciled = coordinator.reconcile_writer_evidence(
            attempt, SyntheticWriterResult(_receipt(attempt), _completion(attempt), True),
        )

        self.assertIs(reconciled.state, GovernedWriteState.APPLIED)
        self.assertEqual(reconciled.invocation_count, 1)
        self.assertEqual(writer.calls, 0)


    def test_receipt_and_completion_prove_applied_but_only_independent_outcome_verifies(self) -> None:
        attempt = _attempt()
        coordinator, _ledger = _system()
        writer = _Writer(SyntheticWriterResult(_receipt(attempt), _completion(attempt), True))

        applied = coordinator.dispatch(attempt, writer)
        self.assertIs(applied.state, GovernedWriteState.APPLIED)
        self.assertIsNotNone(applied.receipt)
        self.assertIsNotNone(applied.completion)
        self.assertIsNone(applied.outcome)
        self.assertTrue(applied.hold_retained)

        verified = coordinator.record_outcome(attempt, _outcome(attempt))
        self.assertIs(verified.state, GovernedWriteState.VERIFIED)
        self.assertIsNotNone(verified.outcome)
        self.assertFalse(verified.hold_retained)
        self.assertEqual(verified.invocation_count, 1)

    def test_unpost_signed_receipt_and_independent_unposted_outcome_verify(self) -> None:
        attempt = _attempt(operation_kind="UNPOST")
        coordinator, ledger = _system()
        receipt = _receipt(attempt)
        writer = _Writer(SyntheticWriterResult(receipt, _completion(attempt), True))

        applied = coordinator.dispatch(attempt, writer)
        self.assertIs(applied.state, GovernedWriteState.APPLIED)
        self.assertTrue(applied.hold_retained)
        self.assertTrue(verify_record_signature(receipt, _WRITER_KEY))

        evidence = _outcome(attempt)
        self.assertTrue(verify_record_signature(evidence, _VERIFIER_KEY))
        self.assertEqual(evidence.document_posting_state, "UNPOSTED")
        self.assertEqual(evidence.target_ref, receipt.returned_target_ref)
        self.assertEqual(evidence.pre_version, attempt.expected_pre_version)
        self.assertEqual(evidence.observed_version, receipt.returned_version)
        self.assertEqual(evidence.version_relation, "ADVANCED")

        verified = coordinator.record_outcome(attempt, evidence)
        self.assertIs(verified.state, GovernedWriteState.VERIFIED)
        self.assertFalse(verified.hold_retained)
        self.assertEqual(verified.outcome, evidence)
        self.assertEqual(verified.invocation_count, 1)
        self.assertEqual(ledger.get(attempt), verified)

    def test_unpost_posted_or_nonadvanced_outcome_is_rejected_and_keeps_hold(self) -> None:
        invalid_outcomes = (
            ("still-posted", {"document_posting_state": "POSTED"}),
            ("version-not-advanced", {"version_relation": "UNCHANGED", "observed_version": "v4"}),
        )
        for label, outcome_args in invalid_outcomes:
            with self.subTest(label=label):
                attempt = _attempt(operation_kind="UNPOST")
                coordinator, ledger = _system()
                receipt = _receipt(attempt)
                writer = _Writer(SyntheticWriterResult(receipt, _completion(attempt), True))
                applied = coordinator.dispatch(attempt, writer)
                self.assertIs(applied.state, GovernedWriteState.APPLIED)
                self.assertTrue(applied.hold_retained)

                evidence = _outcome(attempt, **outcome_args)
                self.assertTrue(verify_record_signature(evidence, _VERIFIER_KEY))
                with self.assertRaises(ValueError):
                    coordinator.record_outcome(attempt, evidence)

                rejected = ledger.get(attempt)
                self.assertIs(rejected.state, GovernedWriteState.APPLIED)
                self.assertTrue(rejected.hold_retained)
                self.assertIsNone(rejected.outcome)

    def test_contradictory_effect_digest_or_completion_class_cannot_verify_or_release_hold(self) -> None:
        bad_outcomes = (
            ("effect-digest", {"expected_effect_digest": _ZERO, "observed_effect_digest": "f" * 64}),
            ("completion-class", {"completion_proof_class": "INDEPENDENT_SESSION_AND_PROCESS_CLOSED"}),
        )
        for label, evidence_args in bad_outcomes:
            with self.subTest(label=label):
                attempt = _attempt()
                coordinator, ledger = _system()
                writer = _Writer(SyntheticWriterResult(_receipt(attempt), _completion(attempt), True))
                applied = coordinator.dispatch(attempt, writer)
                self.assertIs(applied.state, GovernedWriteState.APPLIED)
                self.assertTrue(applied.hold_retained)

                with self.assertRaises(ValueError):
                    coordinator.record_outcome(attempt, _outcome(attempt, **evidence_args))

                after_rejection = ledger.get(attempt)
                self.assertIs(after_rejection.state, GovernedWriteState.APPLIED)
                self.assertTrue(after_rejection.hold_retained)
                self.assertIsNone(after_rejection.outcome)

    def test_post_outcome_must_report_posted_state_and_advanced_version(self) -> None:
        # Each fixture is re-sealed with the verifier test key, so these are
        # validly signed, digest-matching claims whose operation semantics are
        # contradictory or unknown. A signature cannot make them acceptable.
        invalid_outcomes = (
            ("unposted", {"document_posting_state": "UNPOSTED"}),
            ("unknown-version-relation", {"version_relation": "UNKNOWN"}),
            ("unchanged-version-relation", {"version_relation": "UNCHANGED"}),
        )
        for label, evidence_args in invalid_outcomes:
            with self.subTest(label=label):
                attempt = _attempt()
                coordinator, ledger = _system()
                writer = _Writer(SyntheticWriterResult(_receipt(attempt), _completion(attempt), True))
                applied = coordinator.dispatch(attempt, writer)
                self.assertIs(applied.state, GovernedWriteState.APPLIED)
                self.assertTrue(applied.hold_retained)

                evidence = _outcome(attempt, **evidence_args)
                self.assertTrue(verify_record_signature(evidence, _VERIFIER_KEY))
                self.assertEqual(
                    evidence.expected_effect_digest,
                    evidence.observed_effect_digest,
                )

                with self.assertRaises(ValueError):
                    coordinator.record_outcome(attempt, evidence)

                after_rejection = ledger.get(attempt)
                self.assertIs(after_rejection.state, GovernedWriteState.APPLIED)
                self.assertTrue(after_rejection.hold_retained)
                self.assertIsNone(after_rejection.outcome)

    def test_outcome_must_match_signed_writer_receipt_target_and_version(self) -> None:
        invalid_cases = (
            (
                "post-version-differs-from-receipt",
                _attempt(),
                {},
                {"observed_version": "v6"},
            ),
            (
                "create-draft-target-differs-from-receipt",
                _attempt(operation_kind="CREATE_DRAFT"),
                {"returned_target_ref": "doc-created-17", "returned_version": "v1"},
                {"target_ref": "doc-created-18", "observed_version": "v1"},
            ),
            (
                "create-draft-version-differs-from-receipt",
                _attempt(operation_kind="CREATE_DRAFT"),
                {"returned_target_ref": "doc-created-17", "returned_version": "v1"},
                {"target_ref": "doc-created-17", "observed_version": "v2"},
            ),
        )
        for label, attempt, receipt_args, outcome_args in invalid_cases:
            with self.subTest(label=label):
                coordinator, ledger = _system()
                receipt = _receipt(attempt, **receipt_args)
                completion = _completion(attempt)
                writer = _Writer(SyntheticWriterResult(receipt, completion, True))
                applied = coordinator.dispatch(attempt, writer)
                self.assertIs(applied.state, GovernedWriteState.APPLIED)
                self.assertTrue(applied.hold_retained)
                self.assertTrue(verify_record_signature(receipt, _WRITER_KEY))

                evidence = _outcome(attempt, **outcome_args)
                self.assertTrue(verify_record_signature(evidence, _VERIFIER_KEY))
                with self.assertRaises(ValueError):
                    coordinator.record_outcome(attempt, evidence)

                after_rejection = ledger.get(attempt)
                self.assertIs(after_rejection.state, GovernedWriteState.APPLIED)
                self.assertTrue(after_rejection.hold_retained)
                self.assertIsNone(after_rejection.outcome)

    def test_post_and_unpost_outcomes_must_match_intended_target_and_preimage(self) -> None:
        invalid_cases = (
            ("post-target-mismatch", "POST", {"target_ref": "other-doc"}),
            ("post-pre-version-mismatch", "POST", {"pre_version": "v3"}),
            ("unpost-target-mismatch", "UNPOST", {"target_ref": "other-doc"}),
            ("unpost-pre-version-mismatch", "UNPOST", {"pre_version": "v3"}),
        )
        for label, operation_kind, outcome_args in invalid_cases:
            with self.subTest(label=label):
                attempt = _attempt(operation_kind=operation_kind)
                coordinator, ledger = _system()
                receipt = _receipt(attempt)
                writer = _Writer(SyntheticWriterResult(receipt, _completion(attempt), True))
                applied = coordinator.dispatch(attempt, writer)
                self.assertIs(applied.state, GovernedWriteState.APPLIED)
                self.assertTrue(applied.hold_retained)
                self.assertTrue(verify_record_signature(receipt, _WRITER_KEY))

                evidence = _outcome(attempt, **outcome_args)
                self.assertTrue(verify_record_signature(evidence, _VERIFIER_KEY))
                with self.assertRaises(ValueError):
                    coordinator.record_outcome(attempt, evidence)

                after_rejection = ledger.get(attempt)
                self.assertIs(after_rejection.state, GovernedWriteState.APPLIED)
                self.assertTrue(after_rejection.hold_retained)
                self.assertIsNone(after_rejection.outcome)


if __name__ == "__main__":
    unittest.main(verbosity=2)

