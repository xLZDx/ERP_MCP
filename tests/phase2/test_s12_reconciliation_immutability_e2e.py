"""Synthetic reconciliation regression for immutable signed S12 evidence.

This exercises only the in-memory ledger with fixture signing keys. It is not
evidence for a durable database, a real writer boundary, or formal S12/G8.
"""
from __future__ import annotations

import unittest

from business_ai_gateway.phase2.change.evidence import DispatchReceipt, seal_record_fixture
from business_ai_gateway.phase2.simulation.governed_write_v2 import (
    GovernedWriteState,
    SyntheticWriterResult,
)
from test_s12_governed_write_v2_e2e import (
    _WRITER_SEED,
    _attempt,
    _completion,
    _outcome,
    _receipt,
    _system,
)


class ReconciliationEvidenceImmutabilityE2ETests(unittest.TestCase):
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
