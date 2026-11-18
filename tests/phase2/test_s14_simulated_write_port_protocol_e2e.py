"""S14 local-only protocol consumer journey for the simulated writer.

All state, identities, permits and payloads are synthetic and in-memory. This
does not exercise a real 1C channel, CT14, production evidence, or gate approval.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from business_ai_gateway.phase2.change.proposal import (
    DraftPayload,
    Line,
    payload_digest,
    payload_to_dict,
)
from business_ai_gateway.phase2.change.types import ChangeKind
from business_ai_gateway.phase2.change.transitions import Event, classify_completion
from business_ai_gateway.phase2.change_ledger.write_port import (
    ApplyTicket,
    DispatchPermit,
    FailureEvidence,
    OneCWritePort,
)
from business_ai_gateway.phase2.simulation.clone_1c import LANE, SYNTHETIC_MARKER, SimulatedOneC
from business_ai_gateway.phase2.simulation.simulated_write_port import (
    SimulatedOneCWritePort,
    SyntheticOutcomeUnknown,
    SyntheticPermitAuthority,
    SyntheticPortRefusal,
    SyntheticPortResult,
)


_KEY = b"s14-test-only-key-material-at-least-32-bytes"
_TENANT = "TENANT-SIM-1"
_COMPANY = "COMPANY-SIM-1"
_ORG = "ORG-SIM-1"


def _typed_payload(organization: str = _ORG, *, document_number: str = "SIM-RECEIPT-001") -> DraftPayload:
    return DraftPayload(
        organization_ref=organization,
        counterparty_ref="COUNTERPARTY-SIM-1",
        contract_ref="CONTRACT-SIM-1",
        supplier_document_number=document_number,
        supplier_document_date="2026-10-17",
        currency="MDL",
        lines=(Line("ITEM-SIM-1", "1", "10", "VAT-20", "10", "2"),),
        comment="synthetic protocol journey",
    )


def _payload(organization: str = _ORG, *, document_number: str = "SIM-RECEIPT-001") -> dict[str, object]:
    return payload_to_dict(_typed_payload(organization, document_number=document_number))


class SimulatedWritePortProtocolE2ETests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clone = SimulatedOneC("SIM-CLONE-E2E")
        self.authority = SyntheticPermitAuthority(self.clone.label, _KEY)
        self.port: OneCWritePort = SimulatedOneCWritePort(
            self.clone,
            tenant_id=_TENANT,
            company_id=_COMPANY,
            organization=_ORG,
            permit_authority=self.authority,
        )

    def _ticket(
        self,
        kind: ChangeKind,
        *,
        target_ref: str | None = None,
        target_version: str | None = None,
        organization: str = _ORG,
        digest_payload: DraftPayload | None = None,
        attempt_id: str = "1",
        clone: SimulatedOneC | None = None,
    ) -> ApplyTicket:
        target_clone = self.clone if clone is None else clone
        if digest_payload is None and kind in (ChangeKind.CREATE_DRAFT, ChangeKind.UPDATE_DRAFT):
            digest_payload = _typed_payload()
        return ApplyTicket(
            change_id=f"CHANGE-{kind.value}-{attempt_id}",
            generation=1,
            call_id=f"CALL-{kind.value}-{attempt_id}",
            kind=kind.value,
            tenant_id=_TENANT,
            company_id=_COMPANY,
            organization=organization,
            base_fingerprint=target_clone.state_fingerprint(),
            target_ref=target_ref,
            target_version=target_version,
            digest_set_hash=payload_digest(digest_payload, target_version),
        )

    def _permit(
        self, ticket: ApplyTicket, authority: SyntheticPermitAuthority | None = None,
    ) -> DispatchPermit:
        target_authority = self.authority if authority is None else authority
        return target_authority.issue(
            ticket,
            datetime.now(timezone.utc) + timedelta(minutes=5),
            checkpoint_seq=1,
        )

    async def _protocol_consumer_create(self, port: OneCWritePort) -> SyntheticPortResult:
        ticket = self._ticket(ChangeKind.CREATE_DRAFT)
        permit = self._permit(ticket)
        await port.verify_ticket(ticket)
        await port.verify_permit(ticket, permit)
        identity = await port.authenticate_base(ticket)
        self.assertTrue(identity.startswith(f"TEST:{SYNTHETIC_MARKER}:"))
        return await port.create_draft(ticket, permit, _payload())

    async def test_protocol_consumer_runs_only_test_lane_create_post_unpost(self) -> None:
        created = await self._protocol_consumer_create(self.port)
        self.assertEqual(created["lane"], LANE)
        self.assertEqual(created["synthetic_marker"], SYNTHETIC_MARKER)
        self.assertEqual(created["outcome"], "APPLIED_TEST_ONLY")
        self.assertEqual(created["operation"], ChangeKind.CREATE_DRAFT.value)
        self.assertIs(type(created), SyntheticPortResult)

        # Production completion classification accepts only its closed evidence type.
        # A synthetic adapter result therefore cannot become T7 (success) or T8 (proven refusal).
        self.assertNotIsInstance(created, FailureEvidence)
        self.assertNotIn("signature", created)
        self.assertIs(classify_completion(created), Event.CALL_UNKNOWN)

        created_state = self.clone.read_state(created["target_ref"])
        self.assertEqual(created_state["status"], "DRAFT")
        self.assertEqual(created_state["payload"]["organization_ref"], _ORG)
        self.assertEqual(created_state["movements"], {})

        post_ticket = self._ticket(
            ChangeKind.POST,
            target_ref=created["target_ref"],
            target_version=created["new_version"],
        )
        posted = await self.port.post(post_ticket, self._permit(post_ticket))
        self.assertEqual(posted["outcome"], "APPLIED_TEST_ONLY")
        self.assertEqual(posted["operation"], ChangeKind.POST.value)
        posted_state = self.clone.read_state(posted["target_ref"])
        self.assertEqual(posted_state["status"], "POSTED")
        self.assertEqual(posted_state["movements"], {"НДСПредъявленный": 1, "Хозрасчетный": 1})

        unpost_ticket = self._ticket(
            ChangeKind.UNPOST,
            target_ref=posted["target_ref"],
            target_version=posted["new_version"],
        )
        unposted = await self.port.unpost(unpost_ticket, self._permit(unpost_ticket))
        self.assertEqual(unposted["outcome"], "APPLIED_TEST_ONLY")
        self.assertEqual(unposted["operation"], ChangeKind.UNPOST.value)
        unposted_state = self.clone.read_state(unposted["target_ref"])
        self.assertEqual(unposted_state["status"], "DRAFT")
        self.assertEqual(unposted_state["movements"], {})
        self.assertEqual(unposted["effects"]["movement_rows_removed"], 2)
        self.assertEqual(self.clone.write_count, 3)

    async def test_organization_binding_and_update_are_refused_before_write(self) -> None:
        other_org_payload = _typed_payload("ORG-OTHER")
        ticket = self._ticket(ChangeKind.CREATE_DRAFT, digest_payload=other_org_payload)
        permit = self._permit(ticket)
        before = self.clone.write_count
        with self.assertRaisesRegex(SyntheticPortRefusal, "CLONE_REFUSED:ORGANIZATION_MISMATCH"):
            await self.port.create_draft(ticket, permit, payload_to_dict(other_org_payload))
        self.assertEqual(self.clone.write_count, before)
        self.assertEqual(self.clone.target_refs(), ())

    async def test_valid_permit_rejects_payload_changed_after_ticket_creation(self) -> None:
        ticket = self._ticket(ChangeKind.CREATE_DRAFT)
        permit = self._permit(ticket)
        before = self.clone.write_count

        with self.assertRaisesRegex(SyntheticPortRefusal, "DIGEST_MISMATCH"):
            await self.port.create_draft(
                ticket,
                permit,
                _payload(document_number="SIM-RECEIPT-ALTERED"),
            )

        self.assertEqual(self.clone.write_count, before)
        self.assertEqual(self.clone.target_refs(), ())

        update_ticket = self._ticket(ChangeKind.UPDATE_DRAFT)
        update_permit = self._permit(update_ticket)
        with self.assertRaisesRegex(SyntheticPortRefusal, "OPERATION_NOT_ALLOWED"):
            await self.port.update_draft(update_ticket, update_permit, _payload())
        self.assertEqual(self.clone.write_count, before)
        self.assertEqual(self.clone.target_refs(), ())

    async def test_unknown_outcomes_are_test_only_and_never_authorize_retry(self) -> None:
        ticket = self._ticket(ChangeKind.CREATE_DRAFT, digest_payload=_typed_payload())
        permit = self._permit(ticket)

        self.clone.fail_next("timeout")
        with self.assertRaises(SyntheticOutcomeUnknown) as timeout:
            await self.port.create_draft(ticket, permit, _payload())
        self.assertFalse(timeout.exception.retry_permitted)
        self.assertEqual(timeout.exception.certainty, "UNKNOWN_AFTER_INVOCATION")
        self.assertEqual(self.clone.write_count, 0)
        self.assertEqual(len(self.clone.truth_log()), 1)  # test-only oracle; not exposed by the port

        # A separate adapter can still inspect the held TEST base, but its new
        # write is refused before another call identity is consumed.
        other_authority = SyntheticPermitAuthority(self.clone.label, _KEY)
        other_port = SimulatedOneCWritePort(
            self.clone,
            tenant_id=_TENANT,
            company_id=_COMPANY,
            organization=_ORG,
            permit_authority=other_authority,
        )
        next_ticket = self._ticket(
            ChangeKind.CREATE_DRAFT,
            digest_payload=_typed_payload(document_number="SIM-RECEIPT-002"),
            attempt_id="2",
        )
        next_permit = self._permit(next_ticket, other_authority)
        self.assertTrue((await other_port.authenticate_base(next_ticket)).startswith("TEST:"))
        with self.assertRaisesRegex(SyntheticPortRefusal, "BASE_WRITE_HELD"):
            await other_port.create_draft(next_ticket, next_permit, _payload(document_number="SIM-RECEIPT-002"))
        self.assertEqual(self.clone.write_count, 0)
        self.assertEqual(self.clone.target_refs(), ())

        # A separate base exercises the crash-after-write case because the first
        # base remains held after its timeout.
        crash_clone = SimulatedOneC("SIM-CLONE-E2E-CRASH")
        crash_authority = SyntheticPermitAuthority(crash_clone.label, _KEY)
        crash_port = SimulatedOneCWritePort(
            crash_clone,
            tenant_id=_TENANT,
            company_id=_COMPANY,
            organization=_ORG,
            permit_authority=crash_authority,
        )
        retry_ticket = self._ticket(
            ChangeKind.CREATE_DRAFT,
            digest_payload=_typed_payload(),
            attempt_id="1",
            clone=crash_clone,
        )
        retry_permit = self._permit(retry_ticket, crash_authority)
        crash_clone.fail_next("crash_after_write")
        with self.assertRaises(SyntheticOutcomeUnknown) as crash:
            await crash_port.create_draft(retry_ticket, retry_permit, _payload())
        self.assertFalse(crash.exception.retry_permitted)
        self.assertEqual(crash_clone.write_count, 1)
        self.assertEqual(len(crash_clone.truth_log()), 1)  # only test-side oracle sees the applied write
        target_ref = crash_clone.target_refs()[0]
        self.assertEqual(crash_clone.read_state(target_ref)["status"], "DRAFT")


if __name__ == "__main__":
    unittest.main()
