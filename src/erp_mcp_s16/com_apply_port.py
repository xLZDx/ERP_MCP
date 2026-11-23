"""S16 TEST-only composition over the existing S14 COM draft executor and STA lane."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from business_ai_gateway.phase2.change.proposal import DraftPayload, payload_digest
from business_ai_gateway.phase2.change.types import ChangeKind

from erp_mcp_private_writer.com_draft_executor import (
    DraftDestinationSet,
    execute_create_draft,
)
from erp_mcp_private_writer.com_manifest import (
    ComOperationManifest,
    PayloadPropertyBinding,
    PreparedComManifest,
    com_values_from_approved_payload,
)
from erp_mcp_private_writer.windows_com_lane import WindowsComStaLane
from erp_mcp_s16.contracts import ApplyReceipt, ClaimToken, DomainReceipt


class S14ComDraftApplyPort:
    """Adapt S16's claimed CREATE_DRAFT to the existing, read-back-verifying S14 COM executor.

    This adapter accepts only the one TEST base whose fingerprint is also pinned by the
    ``windows_com_sta_lane`` connection. Bindings and destinations are explicit reviewed
    inputs; the adapter never discovers or invents a 1C metadata crosswalk.
    """

    def __init__(self, *, lane: WindowsComStaLane, expected_base_fingerprint: str,
                 bindings: tuple[PayloadPropertyBinding, ...],
                 destinations: DraftDestinationSet,
                 includes_vat_property: str,
                 document_date: Callable[[], datetime]) -> None:
        if (type(lane) is not WindowsComStaLane
                or type(expected_base_fingerprint) is not str
                or len(expected_base_fingerprint) != 64
                or any(char not in "0123456789abcdef" for char in expected_base_fingerprint)
                or type(bindings) is not tuple or not bindings
                or any(type(item) is not PayloadPropertyBinding for item in bindings)
                or type(destinations) is not DraftDestinationSet
                or bool(destinations.unverified_paths)
                or type(includes_vat_property) is not str or not includes_vat_property
                or dict(destinations.constants).get(includes_vat_property) is not True
                or not callable(document_date)):
            raise ValueError("S16_COM_APPLY_CONFIGURATION_INVALID")
        if (type(lane.target_fingerprint) is not str
                or not hmac.compare_digest(lane.target_fingerprint, expected_base_fingerprint)):
            raise ValueError("S16_COM_APPLY_TARGET_MISMATCH")
        self.lane = lane
        self._expected_base_fingerprint = expected_base_fingerprint
        self._bindings = bindings
        self._destinations = destinations
        self._document_date = document_date

    @property
    def expected_base_fingerprint(self) -> str:
        return self._expected_base_fingerprint

    def apply(self, receipt: DomainReceipt, claim: ClaimToken) -> ApplyReceipt:
        from erp_mcp_s16.contracts import ApprovalDecision

        if (type(receipt) is not DomainReceipt or type(claim) is not ClaimToken
                or type(receipt.proposal.payload) is not DraftPayload
                or receipt.proposal.kind is not ChangeKind.CREATE_DRAFT
                or receipt.scope.target_class != "TEST"
                or receipt.scope.base_fingerprint != self._expected_base_fingerprint
                or type(receipt.approval) is not ApprovalDecision
                or receipt.approval.decision != "APPROVE"
                or receipt.approval.scope != receipt.scope
                or claim.change_id != receipt.change_id
                or type(claim.claim_id) is not str or not claim.claim_id
                or claim.version != receipt.version
                or claim.approval_digest != receipt.approval.approval_digest):
            raise ValueError("S16_COM_APPLY_SCOPE_OR_CLAIM_INVALID")

        payload = receipt.proposal.payload
        approved_digest = payload_digest(payload, None)
        if approved_digest != receipt.proposal.payload_digest:
            raise ValueError("S16_COM_APPLY_PAYLOAD_DIGEST_INVALID")
        manifest = PreparedComManifest.from_approved_payload(
            ComOperationManifest("CREATE_DRAFT", "Write", "PLAIN", None, None),
            "SetValue",
            payload,
            self._bindings,
            approved_payload_digest=approved_digest,
            target_version=None,
        )
        # PreparedComManifest contains digest-only assignment evidence. Rebuild the
        # ephemeral COM values from the approved payload at the final writer boundary.
        values = com_values_from_approved_payload(
            payload, self._bindings, approved_payload_digest=approved_digest,
            target_version=None,
        )
        date_value = self._document_date()
        if type(date_value) is not datetime or date_value.tzinfo is not None:
            raise ValueError("S16_COM_APPLY_DATE_INVALID")
        expected_total = format(sum(
            (Decimal(line.amount) for line in payload.lines), Decimal(0),
        ), "f")

        def invoke(session: object) -> tuple[str, str, tuple[str, ...]]:
            connection = getattr(session, "connection", None)
            if connection is None:
                raise RuntimeError("COM_LANE_SESSION_INVALID")
            result = execute_create_draft(
                connection,
                values,
                self._destinations,
                change_id=str(receipt.change_id),
                manifest_sha256=manifest.property_manifest_sha256(),
                document_date=date_value,
                expected_total=expected_total,
            )
            return result.document_ref, result.document_total_text, result.unverified_paths

        result = asyncio.run(self.lane.invoke(invoke))
        if (type(result) is not tuple or len(result) != 3
                or type(result[0]) is not str or type(result[1]) is not str
                or type(result[2]) is not tuple
                or any(type(path) is not str for path in result[2])):
            raise RuntimeError("COM_EXECUTOR_RESULT_INVALID")
        correlation = hashlib.sha256(claim.claim_id.encode("utf-8")).hexdigest()
        status = "APPLIED" if not result[2] else "APPLIED_UNVERIFIED"
        return ApplyReceipt(receipt.change_id, status, correlation, result[0])


__all__ = ["S14ComDraftApplyPort"]
