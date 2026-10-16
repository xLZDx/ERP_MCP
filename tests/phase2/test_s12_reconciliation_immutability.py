"""S12 reconciliation immutability tests for local synthetic scope only.

Maps to S12 freeze acceptance for immutable signed evidence/reconciliation and
the S11 register stories V2-S12-01 (single dispatch), V2-S12-02 (bound writer
receipt), V2-S12-06 (unknown outcomes remain held), and V2-S12-07 (evidence
reconciliation). These in-memory tests do not establish formal S12 or G8.
"""
from __future__ import annotations

from dataclasses import replace
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "phase2"))

from business_ai_gateway.phase2.change.evidence import (  # noqa: E402
    CompletionProof,
    DispatchReceipt,
    seal_record_fixture,
)
from business_ai_gateway.phase2.simulation.governed_write_v2 import (  # noqa: E402
    GovernedWriteState,
    SyntheticWriterResult,
)
from test_s12_governed_write_v2_e2e import (  # noqa: E402
    _WRITER_SEED,
    _attempt,
    _completion,
    _receipt,
    _system,
)


def _signed_replacement(record_type: type, record: object, **updates: object) -> object:
    fields = dict(record.to_dict())  # type: ignore[attr-defined]
    fields.update(updates)
    fields["signature"] = ""
    return seal_record_fixture(record_type, fields, _WRITER_SEED)


class ReconciliationImmutabilityTests(unittest.TestCase):
    def _unknown(self, *, receipt=None):
        attempt = _attempt()
        coordinator, ledger = _system()
        ledger.begin(attempt)
        ledger.consume_dispatch(attempt)
        coordinator.recover_unresolved(attempt)
        if receipt is not None:
            retained = coordinator.reconcile_writer_evidence(
                attempt, SyntheticWriterResult(receipt, None, True),
            )
            self.assertIs(retained.state, GovernedWriteState.APPLY_UNKNOWN)
        return attempt, coordinator, ledger

    def _assert_original_held(self, attempt, coordinator, ledger, original):
        after = ledger.get(attempt)
        self.assertEqual(after.state, original.state)
        self.assertIs(after.receipt, original.receipt)
        self.assertIs(after.completion, original.completion)
        self.assertEqual(after.outcome, original.outcome)
        self.assertTrue(after.hold_retained)
        next_attempt = replace(
            attempt,
            change_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            claim_generation=2,
            dispatch_generation=2,
            dispatch_cas_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            call_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        )
        with self.assertRaisesRegex(ValueError, "BASE_CALL_OWNERSHIP_HOLD"):
            ledger.begin(next_attempt)
        return after

    def test_conflicting_valid_receipt_with_new_identity_preserves_original_and_hold(self) -> None:
        """V2-S12-02/06/07: a second valid receipt ID cannot replace retained evidence."""
        original_receipt = _receipt(_attempt())
        attempt, coordinator, ledger = self._unknown(receipt=original_receipt)
        original = ledger.get(attempt)
        conflicting = _signed_replacement(
            DispatchReceipt, original_receipt,
            receipt_id="77777777-7777-4777-8777-777777777777",
        )

        with self.assertRaisesRegex(ValueError, "RECONCILIATION_EVIDENCE_CONFLICT"):
            coordinator.reconcile_writer_evidence(
                attempt, SyntheticWriterResult(conflicting, None, True),
            )

        self._assert_original_held(attempt, coordinator, ledger, original)

    def test_same_receipt_identity_with_changed_canonical_content_conflicts(self) -> None:
        """V2-S12-02/07: identity equality cannot make changed signed content idempotent."""
        original_receipt = _receipt(_attempt())
        attempt, coordinator, ledger = self._unknown(receipt=original_receipt)
        original = ledger.get(attempt)
        changed = _signed_replacement(
            DispatchReceipt, original_receipt, mapping_version="mapping-v2",
        )
        self.assertEqual(changed.receipt_id, original_receipt.receipt_id)

        with self.assertRaisesRegex(ValueError, "RECONCILIATION_EVIDENCE_CONFLICT"):
            coordinator.reconcile_writer_evidence(
                attempt, SyntheticWriterResult(changed, None, True),
            )

        self._assert_original_held(attempt, coordinator, ledger, original)

    def test_invalid_signature_replacement_is_rejected_without_mutation(self) -> None:
        """V2-S12-02/07: invalid signed replacement cannot displace a valid receipt."""
        original_receipt = _receipt(_attempt())
        attempt, coordinator, ledger = self._unknown(receipt=original_receipt)
        original = ledger.get(attempt)
        invalid_fields = original_receipt.to_dict()
        invalid_fields["signature"] = "00" * 64
        invalid = DispatchReceipt.from_mapping(invalid_fields)

        with self.assertRaisesRegex(ValueError, "WRITER_RECEIPT_SIGNATURE_INVALID"):
            coordinator.reconcile_writer_evidence(
                attempt, SyntheticWriterResult(invalid, None, True),
            )

        self._assert_original_held(attempt, coordinator, ledger, original)

    def test_conflicting_completion_proof_identity_or_content_preserves_original(self) -> None:
        """V2-S12-02/07: completion proof ID and full canonical content are immutable."""
        attempt, coordinator, ledger = self._unknown()
        retained_receipt = _receipt(attempt)
        retained_proof = _completion(attempt)
        attached = coordinator.reconcile_writer_evidence(
            attempt, SyntheticWriterResult(retained_receipt, retained_proof, False),
        )
        self.assertIs(attached.state, GovernedWriteState.APPLY_UNKNOWN)
        original = ledger.get(attempt)

        conflicting = _signed_replacement(
            CompletionProof, retained_proof,
            completion_proof_id="88888888-8888-4888-8888-888888888888",
        )
        with self.assertRaisesRegex(ValueError, "RECONCILIATION_EVIDENCE_CONFLICT"):
            coordinator.reconcile_writer_evidence(
                attempt, SyntheticWriterResult(None, conflicting, False),
            )
        self._assert_original_held(attempt, coordinator, ledger, original)

        changed_content = _signed_replacement(
            CompletionProof, retained_proof, evidence_ref="changed-evidence-ref",
        )
        with self.assertRaisesRegex(ValueError, "RECONCILIATION_EVIDENCE_CONFLICT"):
            coordinator.reconcile_writer_evidence(
                attempt, SyntheticWriterResult(None, changed_content, False),
            )
        self._assert_original_held(attempt, coordinator, ledger, original)

    def test_exact_canonical_reattachment_is_idempotent(self) -> None:
        """V2-S12-02/07: exact receipt and proof repeats preserve stored objects."""
        attempt, coordinator, ledger = self._unknown()
        receipt = _receipt(attempt)
        proof = _completion(attempt)
        first = coordinator.reconcile_writer_evidence(
            attempt, SyntheticWriterResult(receipt, proof, False),
        )
        self.assertIs(first.state, GovernedWriteState.APPLY_UNKNOWN)
        stored = ledger.get(attempt)

        reconstructed_receipt = DispatchReceipt.from_mapping(receipt.to_dict())
        reconstructed_proof = CompletionProof.from_mapping(proof.to_dict())
        self.assertIsNot(reconstructed_receipt, receipt)
        self.assertIsNot(reconstructed_proof, proof)
        self.assertEqual(reconstructed_receipt.to_dict(), receipt.to_dict())
        self.assertEqual(reconstructed_proof.to_dict(), proof.to_dict())

        repeated = coordinator.reconcile_writer_evidence(
            attempt,
            SyntheticWriterResult(reconstructed_receipt, reconstructed_proof, False),
        )

        self.assertIs(repeated.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertIs(repeated.receipt, stored.receipt)
        self.assertIs(repeated.completion, stored.completion)
        self.assertIsNot(repeated.receipt, reconstructed_receipt)
        self.assertIsNot(repeated.completion, reconstructed_proof)
        self.assertEqual(repeated, stored)
        self.assertTrue(repeated.hold_retained)

    def test_valid_partial_receipt_is_retained_while_result_stays_unknown(self) -> None:
        """V2-S12-02/06/07: receipt persists even while missing proof keeps state unknown."""
        attempt, coordinator, ledger = self._unknown()
        receipt = _receipt(attempt)

        result = coordinator.reconcile_writer_evidence(
            attempt, SyntheticWriterResult(receipt, None, True),
        )

        self.assertIs(result.state, GovernedWriteState.APPLY_UNKNOWN)
        self.assertIs(result.receipt, receipt)
        self.assertIsNone(result.completion)
        self.assertTrue(result.hold_retained)
        self.assertEqual(result.invocation_count, 1)
        self.assertEqual(ledger.get(attempt), result)

    def test_proof_only_exact_repeat_remains_bound_to_stored_receipt(self) -> None:
        """V2-S12-02/07: proof-only repeats validate against and retain the stored receipt."""
        attempt, coordinator, ledger = self._unknown()
        receipt = _receipt(attempt)
        partial = coordinator.reconcile_writer_evidence(
            attempt, SyntheticWriterResult(receipt, None, True),
        )
        self.assertIs(partial.state, GovernedWriteState.APPLY_UNKNOWN)
        proof = _completion(attempt)

        first = coordinator.reconcile_writer_evidence(
            attempt, SyntheticWriterResult(None, proof, False),
        )
        self.assertIs(first.state, GovernedWriteState.APPLY_UNKNOWN)
        stored = ledger.get(attempt)
        self.assertIs(stored.receipt, receipt)
        self.assertIs(stored.completion, proof)

        repeated = coordinator.reconcile_writer_evidence(
            attempt, SyntheticWriterResult(None, proof, False),
        )

        self.assertEqual(repeated, stored)
        self.assertIs(repeated.receipt, receipt)
        self.assertIs(repeated.completion, proof)
        self.assertTrue(repeated.hold_retained)


if __name__ == "__main__":
    unittest.main()
