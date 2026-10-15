"""Explicitly synthetic coordinator for the SQL ledger and the simulated 1C clone.

This module does not implement ``OneCWritePort`` and grants no authority to its input IDs. The SQL
ledger remains responsible for approval and dispatch checks; ``ReferenceWriter`` forwards canonical
bytes and validates the clone-produced receipt. Unknown outcomes are returned without retry.
"""
from __future__ import annotations

import asyncio
import hashlib
from typing import Protocol
from uuid import UUID

from ..change.proposal import DraftPayload, canonical_json, payload_to_dict
from ..change.types import ChangeKind
from ..change_ledger._common import Scope
from .clone_1c import encode_payload
from .reference_writer import ReferenceWriter, WriteOutcome, WriteStatus

__all__ = [
    "DispatchCallNotRecorded",
    "DispatchPayloadNotVerified",
    "ReceiptPersistenceUnknown",
    "SyntheticDispatchCoordinator",
]


class DispatchLedger(Protocol):
    """The narrow existing SQL operations needed by one synthetic dispatch."""

    async def require_dispatch_receipt(self, scope: Scope, change_id: UUID, generation: int) -> None: ...

    async def verify_dispatch_payload(self, scope: Scope, change_id: UUID, generation: int,
                                      payload_text: str | None) -> bool: ...

    async def record_call(self, scope: Scope, change_id: UUID, generation: int, call_id: UUID) -> bool: ...

    async def record_dispatch_receipt(self, scope: Scope, change_id: UUID, generation: int,
                                      key_id: str, received_payload_sha256: str, new_version: str,
                                      signature: str) -> UUID: ...


class DispatchCallNotRecorded(Exception):
    """The ledger did not accept the supplied call ID; no write was sent."""

    def __init__(self) -> None:
        super().__init__("DISPATCH_CALL_NOT_RECORDED")
        self.code = "DISPATCH_CALL_NOT_RECORDED"


class DispatchPayloadNotVerified(Exception):
    """The ledger returned false for its canonical approved-payload check; no write was sent."""

    def __init__(self) -> None:
        super().__init__("DISPATCH_PAYLOAD_NOT_VERIFIED")
        self.code = "DISPATCH_PAYLOAD_NOT_VERIFIED"


class ReceiptPersistenceUnknown(Exception):
    """Receipt SQL state is uncertain after the clone returned a verified success.

    ``outcome`` retains the clone-signed receipt for reconciliation. The clone write must not be
    retried because the SQL transaction may have committed even if its response was lost.
    """

    def __init__(self, outcome: WriteOutcome, *, interrupted: bool = False) -> None:
        super().__init__("RECEIPT_PERSISTENCE_UNKNOWN")
        self.code = "RECEIPT_PERSISTENCE_UNKNOWN"
        self.outcome = outcome
        self.interrupted = interrupted


class SyntheticDispatchCoordinator:
    """Run the existing SQL gates and one verified synthetic writer call, with no retry/completion."""

    def __init__(self, ledger: DispatchLedger, writer: ReferenceWriter) -> None:
        self._ledger = ledger
        self._writer = writer

    async def dispatch(self, scope: Scope, change_id: UUID, generation: int, call_id: UUID,
                       kind: ChangeKind, payload: DraftPayload | None, target_ref: str | None,
                       expected_version: str | None) -> WriteOutcome:
        """Gate, send exact canonical bytes once, then persist only a verified clone receipt.

        Pre-write ledger failures propagate before the writer call. Writer failures and unknown
        outcomes are returned unchanged. A receipt persistence exception after verified clone
        success raises ``ReceiptPersistenceUnknown`` with the result; callers must not retry because
        the SQL transaction may have committed before its response was lost.
        """
        payload_text = None if payload is None else canonical_json(payload_to_dict(payload))
        data = encode_payload(payload)
        await self._ledger.require_dispatch_receipt(scope, change_id, generation)
        if await self._ledger.verify_dispatch_payload(scope, change_id, generation, payload_text) is not True:
            raise DispatchPayloadNotVerified()
        if await self._ledger.record_call(scope, change_id, generation, call_id) is not True:
            raise DispatchCallNotRecorded()

        approved_sha256 = hashlib.sha256(data).hexdigest()
        outcome = self._writer.write(str(change_id), generation, kind, data, approved_sha256,
                                     target_ref, expected_version, dispatch_id=str(call_id))
        if outcome.status is not WriteStatus.APPLIED_VERIFIED:
            return outcome

        receipt = outcome.receipt
        if receipt is None:
            # Defensive invariant: ReferenceWriter must never report verified success without a receipt.
            return WriteOutcome(WriteStatus.RECEIPT_INVALID, "RECEIPT_MISSING", approved_sha256,
                                outcome.received_payload_sha256)
        try:
            await self._ledger.record_dispatch_receipt(
                scope, change_id, generation, str(receipt["key_id"]),
                str(receipt["received_payload_sha256"]), str(receipt["new_version"]),
                str(receipt["signature"]),
            )
        except asyncio.CancelledError:
            raise ReceiptPersistenceUnknown(outcome, interrupted=True) from None
        except Exception:
            raise ReceiptPersistenceUnknown(outcome) from None
        return outcome
