"""Synthetic reconciliation regression for immutable signed S12 evidence.

This exercises only the in-memory ledger with fixture signing keys. It is not
evidence for a durable database, a real writer boundary, or formal S12/G8.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

from business_ai_gateway.phase2.change.evidence import DispatchReceipt, seal_record_fixture
from business_ai_gateway.phase2.simulation.governed_write_v2 import (
    GovernedWriteState,
    SyntheticWriterResult,
)
from test_s12_governed_write_v2_e2e import (
    _WRITER_SEED,
    _Writer,
    _attempt,
    _completion,
    _no_invocation_guard,
    _outcome,
    _receipt,
    _system,
)


class ReconciliationEvidenceImmutabilityE2ETests(unittest.TestCase):
    def test_delayed_unknown_cannot_replace_a_newer_base_hold(self) -> None:
        """A stale callback cannot undo pre-write handback or steal a newer hold."""
        first_attempt = _attempt()
        coordinator, ledger = _system()
        guard = _no_invocation_guard(first_attempt)
        handed_back = coordinator.dispatch(
            first_attempt,
            _Writer(SyntheticWriterResult(
                _receipt(first_attempt, no_effect=True, no_effect_digest=guard.evidence_digest),
                None,
                False,
                guard,
            )),
        )
        self.assertIs(handed_back.state, GovernedWriteState.PRE_DISPATCH)
        self.assertFalse(handed_back.hold_retained)

        second_attempt = replace(
            first_attempt,
            change_id="88888888-8888-4888-8888-888888888888",
            claim_generation=2,
            dispatch_generation=2,
            dispatch_cas_id="99999999-9999-4999-8999-999999999999",
            call_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )
        ledger.begin(second_attempt)
        ledger.consume_dispatch(second_attempt)
        second_unknown = coordinator.recover_unresolved(second_attempt)
        self.assertIs(second_unknown.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertTrue(second_unknown.hold_retained)

        self.assertEqual(ledger.mark_unknown(first_attempt), handed_back)
        self.assertEqual(ledger.get(second_attempt), second_unknown)
        third_attempt = replace(
            second_attempt,
            change_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            claim_generation=3,
            dispatch_generation=3,
            dispatch_cas_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            call_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        )
        with self.assertRaisesRegex(ValueError, "BASE_CALL_OWNERSHIP_HOLD"):
            ledger.begin(third_attempt)

        # A delayed unknown callback after a recorded success preserves that
        # resolved state as well.
        applied_attempt = replace(
            _attempt(),
            change_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            dispatch_cas_id="ffffffff-ffff-4fff-8fff-ffffffffffff",
            call_id="77777777-7777-4777-8777-777777777777",
        )
        applied_coordinator, applied_ledger = _system()
        applied = applied_coordinator.dispatch(
            applied_attempt,
            _Writer(SyntheticWriterResult(
                _receipt(applied_attempt), _completion(applied_attempt), True,
            )),
        )
        self.assertIs(applied.state, GovernedWriteState.APPLIED)
        self.assertEqual(applied_ledger.mark_unknown(applied_attempt), applied)

    def test_conflicting_signed_receipt_cannot_replace_unknown_evidence_or_release_hold(self) -> None:
        """V2-S12-02/06/07: consumed call stays held through conflict and recovery."""
        attempt = _attempt()
        coordinator, ledger = _system()
        ledger.begin(attempt)
        ledger.consume_dispatch(attempt)
        unknown = coordinator.recover_unresolved(attempt)
        self.assertIs(unknown.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertTrue(unknown.hold_retained)

        original_receipt = _receipt(attempt)
        partial = coordinator.reconcile_writer_evidence(
            attempt, SyntheticWriterResult(original_receipt, None, True),
        )
        self.assertIs(partial.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertTrue(partial.hold_retained)
        self.assertEqual(partial.receipt, original_receipt)
        self.assertIsNone(partial.completion)
        self.assertEqual(ledger.get(attempt), partial)

        # A second, independently valid signature still cannot replace the
        # canonical receipt already attached to this consumed dispatch.
        conflicting_fields = original_receipt.to_dict()
        conflicting_fields["receipt_id"] = "77777777-7777-4777-8777-777777777777"
        conflicting_receipt = seal_record_fixture(
            DispatchReceipt, conflicting_fields, _WRITER_SEED,
        )
        before_conflict = ledger.get(attempt)
        with self.assertRaisesRegex(ValueError, "RECONCILIATION_EVIDENCE_CONFLICT"):
            coordinator.reconcile_writer_evidence(
                attempt, SyntheticWriterResult(conflicting_receipt, None, True),
            )
        after_conflict = ledger.get(attempt)
        self.assertEqual(after_conflict, before_conflict)
        self.assertEqual(after_conflict.receipt, original_receipt)
        self.assertTrue(after_conflict.hold_retained)
        self.assertEqual(after_conflict.invocation_count, 1)

        # An exact canonical reattachment is idempotent; matching completion
        # proof can then complete application and independent outcome evidence
        # can verify it and release the local synthetic hold.
        reattached = coordinator.reconcile_writer_evidence(
            attempt, SyntheticWriterResult(original_receipt, None, True),
        )
        self.assertEqual(reattached, before_conflict)
        applied = coordinator.reconcile_writer_evidence(
            attempt, SyntheticWriterResult(original_receipt, _completion(attempt), True),
        )
        self.assertIs(applied.state, GovernedWriteState.APPLIED)
        self.assertTrue(applied.hold_retained)
        self.assertEqual(applied.receipt, original_receipt)

        verified = coordinator.record_outcome(attempt, _outcome(attempt))
        self.assertIs(verified.state, GovernedWriteState.VERIFIED)
        self.assertFalse(verified.hold_retained)
        self.assertEqual(verified.invocation_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
