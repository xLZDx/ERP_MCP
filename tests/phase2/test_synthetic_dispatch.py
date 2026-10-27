"""Functional contract tests for the synthetic dispatch coordinator (S14-R03)."""
from __future__ import annotations

import asyncio
import hashlib
import unittest
from uuid import UUID

from business_ai_gateway.phase2.change.proposal import DraftPayload, Line, canonical_json, payload_to_dict
from business_ai_gateway.phase2.change.types import ChangeKind
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.simulation.clone_1c import encode_payload
from business_ai_gateway.phase2.simulation.reference_writer import WriteOutcome, WriteStatus
from business_ai_gateway.phase2.simulation.synthetic_dispatch import (
    DispatchCallNotRecorded,
    DispatchPayloadNotVerified,
    ReceiptPersistenceCancelled,
    ReceiptPersistenceUnknown,
    SyntheticDispatchCoordinator,
)


SCOPE = Scope("tenant-a", "company-a")
CHANGE_ID = UUID("8ebc1df0-6a54-4d30-989d-59b2bef44390")
CALL_ID = UUID("142cc2dc-7a2b-43ac-96cd-89a82f45f321")
GENERATION = 3


def _payload() -> DraftPayload:
    return DraftPayload(
        organization_ref="org-a",
        counterparty_ref="supplier-a",
        contract_ref="contract-a",
        supplier_document_number="INV-42",
        supplier_document_date="2026-10-15",
        currency="EUR",
        lines=(Line("item-a", "2", "10.5", "VAT20", "21", "3.5"),),
        comment="synthetic dispatch",
    )


class FakeLedger:
    def __init__(self, *, require_error: Exception | None = None, verify: bool = True,
                 record_call: bool = True, receipt_error: Exception | None = None) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.require_error = require_error
        self.verify = verify
        self.record_call_result = record_call
        self.receipt_error = receipt_error
        self.receipts: list[tuple[object, ...]] = []

    async def require_dispatch_receipt(self, scope, change_id, generation) -> None:
        self.calls.append(("require", scope, change_id, generation))
        if self.require_error is not None:
            raise self.require_error

    async def verify_dispatch_payload(self, scope, change_id, generation, payload_text) -> bool:
        self.calls.append(("verify", scope, change_id, generation, payload_text))
        return self.verify

    async def record_call(self, scope, change_id, generation, call_id) -> bool:
        self.calls.append(("record_call", scope, change_id, generation, call_id))
        return self.record_call_result

    async def record_dispatch_receipt(self, scope, change_id, generation, key_id,
                                      received_payload_sha256, new_version, signature) -> UUID:
        receipt = (scope, change_id, generation, key_id, received_payload_sha256, new_version, signature)
        self.calls.append(("record_receipt", *receipt))
        self.receipts.append(receipt)
        if self.receipt_error is not None:
            raise self.receipt_error
        return UUID("9e9fd01c-6843-4fd6-92a9-33052469ca5b")


class FakeWriter:
    def __init__(self, outcome: WriteOutcome) -> None:
        self.outcome = outcome
        self.calls: list[tuple[object, ...]] = []

    def write(self, *args, **kwargs) -> WriteOutcome:
        self.calls.append((*args, kwargs))
        return self.outcome


def _success_outcome(data: bytes) -> WriteOutcome:
    digest = hashlib.sha256(data).hexdigest()
    receipt = {
        "key_id": "clone-key-7",
        "received_payload_sha256": digest,
        "new_version": "V8",
        "signature": "signed-by-clone",
    }
    return WriteOutcome(WriteStatus.APPLIED_VERIFIED, "OK", digest, digest, "V8", receipt)


class SyntheticDispatchCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_gates_run_in_order_and_writer_receives_exact_canonical_payload(self) -> None:
        payload = _payload()
        expected_text = canonical_json(payload_to_dict(payload))
        expected_bytes = encode_payload(payload)
        expected_digest = hashlib.sha256(expected_bytes).hexdigest()
        ledger = FakeLedger()
        outcome = _success_outcome(expected_bytes)
        writer = FakeWriter(outcome)

        result = await SyntheticDispatchCoordinator(ledger, writer).dispatch(
            SCOPE, CHANGE_ID, GENERATION, CALL_ID, ChangeKind.CREATE_DRAFT, payload,
            "document-a", "V7",
        )

        self.assertIs(result, outcome)
        self.assertEqual([call[0] for call in ledger.calls],
                         ["require", "verify", "record_call", "record_receipt"])
        self.assertEqual(ledger.calls[1][-1], expected_text)
        self.assertEqual(len(writer.calls), 1)
        args, kwargs = writer.calls[0][:-1], writer.calls[0][-1]
        self.assertEqual(args, (str(CHANGE_ID), GENERATION, ChangeKind.CREATE_DRAFT, expected_bytes,
                               expected_digest, "document-a", "V7"))
        self.assertEqual(kwargs, {"dispatch_id": str(CALL_ID)})
        self.assertEqual(ledger.receipts, [(SCOPE, CHANGE_ID, GENERATION, "clone-key-7",
                                            expected_digest, "V8", "signed-by-clone")])

    async def test_require_refusal_propagates_without_verify_or_write(self) -> None:
        failure = RuntimeError("receipt gate refused")
        ledger = FakeLedger(require_error=failure)
        writer = FakeWriter(_success_outcome(b"{}"))

        with self.assertRaisesRegex(RuntimeError, "receipt gate refused") as raised:
            await SyntheticDispatchCoordinator(ledger, writer).dispatch(
                SCOPE, CHANGE_ID, GENERATION, CALL_ID, ChangeKind.POST, None, "document-a", "V7")

        self.assertIs(raised.exception, failure)
        self.assertEqual([call[0] for call in ledger.calls], ["require"])
        self.assertEqual(writer.calls, [])
        self.assertEqual(ledger.receipts, [])

    async def test_payload_verification_refusal_fails_closed_before_call_or_write(self) -> None:
        ledger = FakeLedger(verify=False)
        writer = FakeWriter(_success_outcome(b"{}"))

        with self.assertRaises(DispatchPayloadNotVerified):
            await SyntheticDispatchCoordinator(ledger, writer).dispatch(
                SCOPE, CHANGE_ID, GENERATION, CALL_ID, ChangeKind.POST, None, "document-a", "V7")

        self.assertEqual([call[0] for call in ledger.calls], ["require", "verify"])
        self.assertEqual(writer.calls, [])
        self.assertEqual(ledger.receipts, [])

    async def test_call_record_refusal_fails_closed_before_write(self) -> None:
        ledger = FakeLedger(record_call=False)
        writer = FakeWriter(_success_outcome(b"{}"))

        with self.assertRaises(DispatchCallNotRecorded):
            await SyntheticDispatchCoordinator(ledger, writer).dispatch(
                SCOPE, CHANGE_ID, GENERATION, CALL_ID, ChangeKind.POST, None, "document-a", "V7")

        self.assertEqual([call[0] for call in ledger.calls], ["require", "verify", "record_call"])
        self.assertEqual(writer.calls, [])
        self.assertEqual(ledger.receipts, [])

    async def test_non_success_and_unknown_outcomes_are_returned_without_receipt_or_retry(self) -> None:
        statuses = (
            WriteStatus.REJECTED,
            WriteStatus.TAMPER_DETECTED,
            WriteStatus.RECEIPT_INVALID,
            WriteStatus.UNKNOWN_TIMEOUT,
            WriteStatus.UNKNOWN_CRASH,
        )
        for status in statuses:
            with self.subTest(status=status):
                data = b"{}"
                outcome = WriteOutcome(status, status.value, hashlib.sha256(data).hexdigest())
                ledger = FakeLedger()
                writer = FakeWriter(outcome)

                result = await SyntheticDispatchCoordinator(ledger, writer).dispatch(
                    SCOPE, CHANGE_ID, GENERATION, CALL_ID, ChangeKind.POST, None, "document-a", "V7")

                self.assertIs(result, outcome)
                self.assertEqual(len(writer.calls), 1, "unknown/non-success must not trigger a retry")
                self.assertEqual(ledger.receipts, [])
                self.assertNotIn("record_receipt", [call[0] for call in ledger.calls])

    async def test_receipt_persistence_error_preserves_verified_outcome_without_retry(self) -> None:
        payload = _payload()
        data = encode_payload(payload)
        outcome = _success_outcome(data)
        ledger = FakeLedger(receipt_error=RuntimeError("connection lost after commit attempt"))
        writer = FakeWriter(outcome)

        with self.assertRaises(ReceiptPersistenceUnknown) as raised:
            await SyntheticDispatchCoordinator(ledger, writer).dispatch(
                SCOPE, CHANGE_ID, GENERATION, CALL_ID, ChangeKind.CREATE_DRAFT, payload,
                "document-a", "V7",
            )

        self.assertIs(raised.exception.outcome, outcome)
        self.assertIs(raised.exception.outcome.receipt, outcome.receipt)
        self.assertEqual(raised.exception.outcome.status, WriteStatus.APPLIED_VERIFIED)
        self.assertEqual(len(writer.calls), 1, "uncertain receipt persistence must not trigger a retry")
        self.assertEqual([call[0] for call in ledger.calls],
                         ["require", "verify", "record_call", "record_receipt"])
        self.assertEqual(len(ledger.receipts), 1)

    async def test_cancellation_during_receipt_persistence_preserves_verified_outcome(self) -> None:
        payload = _payload()
        outcome = _success_outcome(encode_payload(payload))
        entered_persistence = asyncio.Event()

        class PausedReceiptLedger(FakeLedger):
            async def record_dispatch_receipt(self, scope, change_id, generation, key_id,
                                              received_payload_sha256, new_version, signature) -> UUID:
                receipt = (scope, change_id, generation, key_id, received_payload_sha256,
                           new_version, signature)
                self.calls.append(("record_receipt", *receipt))
                self.receipts.append(receipt)
                entered_persistence.set()
                await asyncio.Event().wait()
                raise AssertionError("unreachable")

        ledger = PausedReceiptLedger()
        writer = FakeWriter(outcome)

        task = asyncio.create_task(SyntheticDispatchCoordinator(ledger, writer).dispatch(
            SCOPE, CHANGE_ID, GENERATION, CALL_ID, ChangeKind.CREATE_DRAFT, payload,
            "document-a", "V7",
        ))
        await asyncio.wait_for(entered_persistence.wait(), timeout=5)
        task.cancel()
        with self.assertRaises(ReceiptPersistenceCancelled) as raised:
            await task

        self.assertIsInstance(raised.exception, asyncio.CancelledError)
        self.assertEqual(raised.exception.code, "RECEIPT_PERSISTENCE_UNKNOWN")
        self.assertIs(raised.exception.outcome, outcome)
        self.assertIs(raised.exception.outcome.receipt, outcome.receipt)
        self.assertEqual(len(writer.calls), 1, "interruption must not trigger a clone retry")
        self.assertEqual(len(ledger.receipts), 1)
        self.assertTrue(task.cancelled())


if __name__ == "__main__":
    unittest.main()
