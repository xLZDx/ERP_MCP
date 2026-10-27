"""Functional coverage for GPT-PM-approved local S14 simulation story.

Story/gate mapping: S14-SIM-LOCAL, PM decision
b5f382b5-86b4-4bc1-9e62-52dc762aad23, acceptance AC-01..AC-16.
These tests exercise only the opt-in TEST clone adapter. They do not prove formal
S14, CT14, R-01, production authorization, or real 1C behavior.
"""
from __future__ import annotations

import asyncio
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Barrier

from business_ai_gateway.phase2.change.proposal import DraftPayload, Line, payload_digest, payload_to_dict
from business_ai_gateway.phase2.change.types import ChangeKind
from business_ai_gateway.phase2.change_ledger.write_port import (
    ApplyTicket,
    DispatchPermit,
    FailureEvidence,
    NotWired,
    NonOperationalWritePort,
)
from business_ai_gateway.phase2.simulation.clone_1c import (
    LANE,
    SYNTHETIC_MARKER,
    SimulatedOneC,
    encode_payload,
)
from business_ai_gateway.phase2.simulation.simulated_write_port import (
    SimulatedOneCWritePort,
    SyntheticOutcomeUnknown,
    SyntheticPermitAuthority,
    SyntheticPortRefusal,
    SyntheticPortResult,
)


TENANT = "SIM-TENANT-A"
COMPANY = "SIM-COMPANY-A"
ORGANIZATION = "SIM-ORG-A"
OTHER_ORGANIZATION = "SIM-ORG-B"
SIMULATOR = "SIM-CLONE-S14"
TEST_KEY = b"s14-simulated-port-test-key-00001"


def _payload(*, organization: str = ORGANIZATION, supplier_number: str = "SIM-INV-100") -> DraftPayload:
    return DraftPayload(
        organization_ref=organization,
        counterparty_ref="SIM-SUP-1",
        contract_ref="SIM-CON-1",
        supplier_document_number=supplier_number,
        supplier_document_date="2026-10-17",
        currency="TST",
        lines=(Line("SIM-ITEM-1", "1", "10", "VAT0", "10", "0"),),
        comment="S14 local simulated adapter functional test",
    )


class SimulatedOneCWritePortFunctionalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.clone = SimulatedOneC(SIMULATOR)
        self.authority = SyntheticPermitAuthority(SIMULATOR, TEST_KEY)
        self.port = self._port(self.clone, self.authority)

    @staticmethod
    def _port(
        clone: SimulatedOneC,
        authority: SyntheticPermitAuthority,
        *,
        tenant: str = TENANT,
        company: str = COMPANY,
    ) -> SimulatedOneCWritePort:
        return SimulatedOneCWritePort(
            clone,
            tenant_id=tenant,
            company_id=company,
            organization=ORGANIZATION,
            permit_authority=authority,
        )

    def _ticket(
        self,
        kind: ChangeKind | str,
        *,
        target_ref: str | None = None,
        target_version: str | None = None,
        organization: str = ORGANIZATION,
        base_fingerprint: str | None = None,
        call_id: str = "SIM-CALL-1",
        generation: int = 1,
        tenant: str = TENANT,
        company: str = COMPANY,
        payload: DraftPayload | None = None,
        digest_set_hash: str | None = None,
    ) -> ApplyTicket:
        if digest_set_hash is None:
            digest_payload = payload if payload is not None else (
                _payload() if kind is ChangeKind.CREATE_DRAFT else None
            )
            digest_set_hash = payload_digest(digest_payload, target_version)
        return ApplyTicket(
            change_id="SIM-CHANGE-1",
            generation=generation,
            call_id=call_id,
            kind=kind.value if isinstance(kind, ChangeKind) else kind,
            tenant_id=tenant,
            company_id=company,
            organization=organization,
            base_fingerprint=base_fingerprint or self.clone.state_fingerprint(),
            target_ref=target_ref,
            target_version=target_version,
            digest_set_hash=digest_set_hash,
        )

    def _permit(self, ticket: ApplyTicket, *, expires_at: datetime | None = None) -> DispatchPermit:
        return self.authority.issue(
            ticket,
            expires_at or datetime.now(timezone.utc) + timedelta(minutes=5),
            checkpoint_seq=1,
        )

    async def _create(self, *, payload: DraftPayload | None = None, call_id: str = "SIM-CREATE-1"):
        body = payload or _payload()
        ticket = self._ticket(ChangeKind.CREATE_DRAFT, call_id=call_id, payload=body)
        permit = self._permit(ticket)
        return await self.port.create_draft(ticket, permit, payload_to_dict(body))

    async def test_allowlisted_create_post_unpost_return_only_test_results(self) -> None:
        created = await self._create()
        self.assertIs(type(created), SyntheticPortResult)
        self.assertEqual(created["lane"], LANE)
        self.assertEqual(created["synthetic_marker"], SYNTHETIC_MARKER)
        self.assertEqual(created["outcome"], "APPLIED_TEST_ONLY")
        self.assertEqual(created["operation"], ChangeKind.CREATE_DRAFT.value)
        self.assertEqual(created["new_version"], "V1")
        self.assertEqual(self.clone.read_state(created["target_ref"])["synthetic_marker"], SYNTHETIC_MARKER)
        self.assertNotIsInstance(created, FailureEvidence)
        self.assertEqual(
            set(created),
            {"lane", "synthetic_marker", "outcome", "operation", "target_ref", "new_version",
             "received_payload_sha256", "effects"},
        )
        self.assertNotIn("signature", created)
        self.assertNotIn("receipt", created)
        self.assertEqual(self.clone.read_state(created["target_ref"])["status"], "DRAFT")

        post_ticket = self._ticket(
            ChangeKind.POST,
            target_ref=created["target_ref"],
            target_version=created["new_version"],
            call_id="SIM-POST-1",
        )
        posted = await self.port.post(post_ticket, self._permit(post_ticket))
        self.assertEqual(posted["operation"], ChangeKind.POST.value)
        self.assertEqual(posted["new_version"], "V2")
        self.assertEqual(self.clone.read_state(created["target_ref"])["status"], "POSTED")

        unpost_ticket = self._ticket(
            ChangeKind.UNPOST,
            target_ref=created["target_ref"],
            target_version=posted["new_version"],
            call_id="SIM-UNPOST-1",
        )
        unposted = await self.port.unpost(unpost_ticket, self._permit(unpost_ticket))
        self.assertEqual(unposted["operation"], ChangeKind.UNPOST.value)
        self.assertEqual(unposted["new_version"], "V3")
        self.assertEqual(self.clone.read_state(created["target_ref"])["status"], "DRAFT")

    async def test_update_draft_and_unknown_operations_refuse_before_clone_entry(self) -> None:
        ticket = self._ticket(
            ChangeKind.UPDATE_DRAFT,
            target_ref="SIM-DOC-000001",
            target_version="V1",
        )
        permit = self._permit(ticket)
        before = self.clone.state_fingerprint()
        log_before = self.clone.truth_log()
        with self.assertRaises(SyntheticPortRefusal) as update_error:
            await self.port.update_draft(ticket, permit, object())  # type: ignore[arg-type]
        self.assertEqual(update_error.exception.code, "OPERATION_NOT_ALLOWED")
        self.assertEqual(self.clone.write_count, 0)
        self.assertEqual(self.clone.state_fingerprint(), before)
        self.assertEqual(self.clone.truth_log(), log_before)

        unsupported = self._ticket("DELETE", call_id="SIM-DELETE-1")
        with self.assertRaises(SyntheticPortRefusal) as unsupported_error:
            await self.port.verify_ticket(unsupported)
        self.assertEqual(unsupported_error.exception.code, "OPERATION_NOT_ALLOWED")
        self.assertEqual(self.clone.write_count, 0)
        self.assertEqual(self.clone.truth_log(), log_before)

    async def test_ticket_scope_fingerprint_shape_and_target_mismatches_fail_closed(self) -> None:
        valid = self._ticket(ChangeKind.CREATE_DRAFT)
        variants = (
            (replace(valid, tenant_id="SIM-TENANT-OTHER"), "SCOPE_MISMATCH"),
            (replace(valid, company_id="SIM-COMPANY-OTHER"), "SCOPE_MISMATCH"),
            (replace(valid, organization="SIM-ORG-OTHER"), "SCOPE_MISMATCH"),
            (replace(valid, base_fingerprint="0" * 64), "BASE_FINGERPRINT_MISMATCH"),
            (replace(valid, generation=True), "TICKET_INVALID"),
            (replace(valid, digest_set_hash="not-a-digest"), "TICKET_INVALID"),
            (replace(valid, base_fingerprint="not-a-digest"), "TICKET_INVALID"),
        )
        before = self.clone.state_fingerprint()
        for ticket, expected_code in variants:
            with self.subTest(ticket=ticket):
                with self.assertRaises(SyntheticPortRefusal) as raised:
                    await self.port.verify_ticket(ticket)
                self.assertEqual(raised.exception.code, expected_code)
                self.assertEqual(self.clone.state_fingerprint(), before)
                self.assertEqual(self.clone.write_count, 0)
                self.assertEqual(self.clone.truth_log(), ())

        bad_target = self._ticket(
            ChangeKind.POST,
            target_ref="SIM-DOC-000001",
            target_version="V01",
        )
        with self.assertRaises(SyntheticPortRefusal) as raised:
            await self.port.verify_ticket(bad_target)
        self.assertEqual(raised.exception.code, "TARGET_VERSION_INVALID")
        self.assertEqual(self.clone.write_count, 0)

        same_identity_other_clone = SimulatedOneC(SIMULATOR)
        same_identity_other_clone.apply(
            ChangeKind.CREATE_DRAFT,
            encode_payload(_payload()),
            None,
            None,
        )
        other_port = self._port(same_identity_other_clone, self.authority)
        with self.assertRaises(SyntheticPortRefusal) as fingerprint_error:
            await other_port.verify_ticket(valid)
        self.assertEqual(fingerprint_error.exception.code, "BASE_FINGERPRINT_MISMATCH")
        self.assertEqual(same_identity_other_clone.write_count, 1)

    async def test_permit_binding_expiry_and_malformed_values_are_rejected(self) -> None:
        ticket = self._ticket(ChangeKind.CREATE_DRAFT)
        permit = self._permit(ticket)
        mutations = (
            replace(permit, permit_id="SIM-PERMIT:OTHER"),
            replace(permit, permit_digest="0" * 64),
            replace(permit, change_id="SIM-CHANGE-OTHER"),
            replace(permit, generation=permit.generation + 1),
            replace(permit, call_id="SIM-CALL-OTHER"),
            replace(permit, expires_at=permit.expires_at + timedelta(hours=1)),
            replace(permit, checkpoint_seq=permit.checkpoint_seq + 1),
            replace(permit, signer_key_id="SIM-TEST:OTHER"),
            replace(permit, signature="0" * 64),
            replace(permit, lifecycle_epoch=1),
        )
        for candidate in mutations:
            with self.subTest(permit=candidate):
                with self.assertRaises(SyntheticPortRefusal):
                    await self.port.verify_permit(ticket, candidate)
                self.assertEqual(self.clone.write_count, 0)
                self.assertEqual(self.clone.truth_log(), ())

        repair_ticket = replace(ticket, repair_authorization_id="SIM-REPAIR-1")
        repair_permit = self._permit(repair_ticket)
        with self.assertRaises(SyntheticPortRefusal):
            await self.port.verify_permit(
                repair_ticket,
                replace(repair_permit, repair_authorization_id="SIM-REPAIR-OTHER"),
            )
        self.assertEqual(self.clone.write_count, 0)

        expired = self._permit(ticket, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        with self.assertRaises(SyntheticPortRefusal) as raised:
            await self.port.verify_permit(ticket, expired)
        self.assertEqual(raised.exception.code, "SYNTHETIC_PERMIT_INVALID_OR_EXPIRED")

        malformed = replace(permit, signature="bad")
        with self.assertRaises(SyntheticPortRefusal):
            await self.port.verify_permit(ticket, malformed)
        self.assertEqual(self.clone.write_count, 0)

    async def test_wrong_payload_organization_refuses_before_any_clone_mutation(self) -> None:
        wrong_scope_payload = _payload(organization=OTHER_ORGANIZATION)
        ticket = self._ticket(
            ChangeKind.CREATE_DRAFT,
            call_id="SIM-WRONG-ORG",
            payload=wrong_scope_payload,
        )
        permit = self._permit(ticket)
        before = self.clone.state_fingerprint()
        with self.assertRaises(SyntheticPortRefusal) as raised:
            await self.port.create_draft(ticket, permit, payload_to_dict(wrong_scope_payload))
        self.assertEqual(raised.exception.code, "CLONE_REFUSED:ORGANIZATION_MISMATCH")
        self.assertEqual(self.clone.state_fingerprint(), before)
        self.assertEqual(self.clone.write_count, 0)
        self.assertEqual(self.clone.truth_log(), ())

    async def test_post_rejects_document_from_another_organization_without_write(self) -> None:
        other_doc = self.clone.apply(
            ChangeKind.CREATE_DRAFT,
            encode_payload(_payload(organization=OTHER_ORGANIZATION)),
            None,
            None,
        )
        before_state = self.clone.state_fingerprint()
        writes_before = self.clone.write_count
        log_before = self.clone.truth_log()
        ticket = self._ticket(
            ChangeKind.POST,
            target_ref=other_doc.target_ref,
            target_version=other_doc.new_version,
        )
        with self.assertRaises(SyntheticPortRefusal) as raised:
            await self.port.post(ticket, self._permit(ticket))
        self.assertEqual(raised.exception.code, "CLONE_REFUSED:ORGANIZATION_MISMATCH")
        self.assertEqual(self.clone.state_fingerprint(), before_state)
        self.assertEqual(self.clone.write_count, writes_before)
        self.assertEqual(self.clone.truth_log(), log_before)

    async def test_malformed_payload_and_wrong_ticket_operation_do_not_write(self) -> None:
        ticket = self._ticket(ChangeKind.CREATE_DRAFT)
        permit = self._permit(ticket)
        for payload in ({"unexpected": "field"}, ["not", "an", "object"], None):
            with self.subTest(payload=payload):
                with self.assertRaises(SyntheticPortRefusal):
                    await self.port.create_draft(ticket, permit, payload)  # type: ignore[arg-type]
                self.assertEqual(self.clone.write_count, 0)
                self.assertEqual(self.clone.truth_log(), ())

        existing = await self._create(call_id="SIM-WRONG-OP-SEED")
        wrong_operation = self._ticket(
            ChangeKind.POST,
            target_ref=existing["target_ref"],
            target_version=existing["new_version"],
            call_id="SIM-WRONG-OP",
        )
        with self.assertRaises(SyntheticPortRefusal) as raised:
            await self.port.create_draft(wrong_operation, self._permit(wrong_operation), payload_to_dict(_payload()))
        self.assertEqual(raised.exception.code, "OPERATION_MISMATCH")
        self.assertEqual(self.clone.write_count, 1)
        self.assertEqual(len(self.clone.truth_log()), 1)

    async def test_valid_permit_with_altered_payload_refuses_without_mutation(self) -> None:
        approved_payload = _payload(supplier_number="SIM-APPROVED-PAYLOAD")
        altered_payload = _payload(supplier_number="SIM-ALTERED-PAYLOAD")
        ticket = self._ticket(
            ChangeKind.CREATE_DRAFT,
            call_id="SIM-PAYLOAD-DIGEST",
            payload=approved_payload,
        )
        permit = self._permit(ticket)
        before = self.clone.state_fingerprint()
        with self.assertRaises(SyntheticPortRefusal) as refusal:
            await self.port.create_draft(ticket, permit, payload_to_dict(altered_payload))
        self.assertEqual(refusal.exception.code, "DIGEST_MISMATCH")
        self.assertEqual(self.clone.state_fingerprint(), before)
        self.assertEqual(self.clone.write_count, 0)
        self.assertEqual(self.clone.truth_log(), ())

    async def test_stale_version_is_refused_and_concurrent_calls_are_serialized(self) -> None:
        created = await self._create(call_id="SIM-RACE-CREATE")
        target_ref = created["target_ref"]
        stale_ticket = self._ticket(
            ChangeKind.POST,
            target_ref=target_ref,
            target_version="V99",
            call_id="SIM-STALE-POST",
        )
        with self.assertRaises(SyntheticPortRefusal) as stale_error:
            await self.port.post(stale_ticket, self._permit(stale_ticket))
        self.assertEqual(stale_error.exception.code, "CLONE_REFUSED:STALE_VERSION")
        self.assertEqual(self.clone.read_state(target_ref)["version"], "V1")
        writes_after_stale = self.clone.write_count

        concurrent_ticket = self._ticket(
            ChangeKind.POST,
            target_ref=target_ref,
            target_version="V1",
            call_id="SIM-CONCURRENT-POST",
        )
        concurrent_permit = self._permit(concurrent_ticket)
        barrier = Barrier(2)
        original_apply = self.clone.apply_for_simulation

        def synchronized_apply(*args, **kwargs):
            barrier.wait(timeout=5)
            return original_apply(*args, **kwargs)

        self.clone.apply_for_simulation = synchronized_apply  # type: ignore[method-assign]

        ports = (
            self.port,
            self._port(self.clone, SyntheticPermitAuthority(SIMULATOR, TEST_KEY)),
        )

        def invoke(index):
            return asyncio.run(ports[index].post(concurrent_ticket, concurrent_permit))

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda index: _capture(lambda: invoke(index)), range(2)))

        self.clone.apply_for_simulation = original_apply  # type: ignore[method-assign]
        successes = [outcome for outcome in outcomes if isinstance(outcome, SyntheticPortResult)]
        refusals = [outcome for outcome in outcomes if isinstance(outcome, SyntheticPortRefusal)]
        self.assertEqual(len(successes), 1, outcomes)
        self.assertEqual(len(refusals), 1, outcomes)
        self.assertEqual(self.clone.read_state(target_ref)["version"], "V2")
        self.assertEqual(self.clone.write_count, writes_after_stale + 1)

    async def test_duplicate_call_or_supplier_document_never_causes_second_effect(self) -> None:
        first_payload = _payload(supplier_number="SIM-INV-DUPLICATE")
        first_ticket = self._ticket(
            ChangeKind.CREATE_DRAFT,
            call_id="SIM-DUP-FIRST",
            payload=first_payload,
        )
        first_permit = self._permit(first_ticket)
        first = await self.port.create_draft(first_ticket, first_permit, payload_to_dict(first_payload))
        before_repeat = self.clone.write_count
        with self.assertRaises(SyntheticPortRefusal):
            await self.port.create_draft(first_ticket, first_permit, payload_to_dict(first_payload))
        self.assertEqual(self.clone.write_count, before_repeat)
        self.assertEqual(len(self.clone.target_refs()), 1)
        self.assertEqual(first["target_ref"], self.clone.target_refs()[0])

        second_payload = _payload(supplier_number="SIM-INV-DUPLICATE")
        second_ticket = self._ticket(
            ChangeKind.CREATE_DRAFT,
            call_id="SIM-DUP-SECOND",
            payload=second_payload,
        )
        before_duplicate = self.clone.write_count
        with self.assertRaises(SyntheticPortRefusal) as duplicate_error:
            await self.port.create_draft(second_ticket, self._permit(second_ticket), payload_to_dict(second_payload))
        self.assertEqual(duplicate_error.exception.code, "CLONE_REFUSED:DUPLICATE")
        self.assertEqual(self.clone.write_count, before_duplicate)
        self.assertEqual(len(self.clone.target_refs()), 1)

    async def test_refusal_is_not_signed_no_effect_evidence_and_is_distinct_from_unknown(self) -> None:
        ticket = self._ticket(ChangeKind.CREATE_DRAFT)
        permit = self._permit(ticket)
        self.clone.fail_next("reject")
        with self.assertRaises(SyntheticPortRefusal) as refusal:
            await self.port.create_draft(ticket, permit, payload_to_dict(_payload()))
        self.assertEqual(refusal.exception.certainty, "SIMULATION_REFUSAL_ONLY")
        self.assertEqual(refusal.exception.lane, "TEST")
        self.assertFalse(hasattr(refusal.exception, "signature"))
        self.assertFalse(hasattr(refusal.exception, "no_effect_proof"))
        self.assertNotIsInstance(refusal.exception, FailureEvidence)
        self.assertNotIn("T8", str(refusal.exception))
        self.assertNotIn("T9", str(refusal.exception))
        self.assertEqual(self.clone.write_count, 0)

        unknown_clone = SimulatedOneC(SIMULATOR + "-UNKNOWN")
        unknown_authority = SyntheticPermitAuthority(SIMULATOR + "-UNKNOWN", TEST_KEY)
        unknown_port = self._port(unknown_clone, unknown_authority)
        unknown_ticket = ApplyTicket(
            "SIM-CHANGE-UNKNOWN", 1, "SIM-CALL-UNKNOWN", ChangeKind.CREATE_DRAFT.value,
            TENANT, COMPANY, ORGANIZATION, unknown_clone.state_fingerprint(), None, None,
            payload_digest(_payload(), None),
        )
        unknown_clone.fail_next("crash_after_write")
        with self.assertRaises(SyntheticOutcomeUnknown) as unknown:
            await unknown_port.create_draft(
                unknown_ticket,
                unknown_authority.issue(unknown_ticket, datetime.now(timezone.utc) + timedelta(minutes=5)),
                payload_to_dict(_payload()),
            )
        self.assertEqual(unknown.exception.certainty, "UNKNOWN_AFTER_INVOCATION")
        self.assertFalse(unknown.exception.retry_permitted)
        self.assertEqual(unknown_clone.write_count, 1)
        self.assertEqual(len(unknown_clone.target_refs()), 1)

    async def test_timeout_and_crashes_are_unknown_without_adapter_retry(self) -> None:
        for index, mode, expected_writes in (
            (1, "timeout", 0),
            (2, "crash_before_write", 0),
            (3, "crash_after_write", 1),
        ):
            with self.subTest(mode=mode):
                clone = SimulatedOneC(f"SIM-FAILURE-{index}")
                authority = SyntheticPermitAuthority(clone.label, TEST_KEY)
                port = self._port(clone, authority)
                ticket = ApplyTicket(
                    f"SIM-CHANGE-{index}", 1, f"SIM-CALL-{index}", ChangeKind.CREATE_DRAFT.value,
                    TENANT, COMPANY, ORGANIZATION, clone.state_fingerprint(), None, None,
                    payload_digest(_payload(supplier_number=f"SIM-FAIL-{index}"), None),
                )
                clone.fail_next(mode)
                with self.assertRaises(SyntheticOutcomeUnknown) as raised:
                    await port.create_draft(
                        ticket,
                        authority.issue(ticket, datetime.now(timezone.utc) + timedelta(minutes=5)),
                        payload_to_dict(_payload(supplier_number=f"SIM-FAIL-{index}")),
                    )
                self.assertEqual(raised.exception.certainty, "UNKNOWN_AFTER_INVOCATION")
                self.assertFalse(raised.exception.retry_permitted)
                self.assertEqual(clone.write_count, expected_writes)
                self.assertEqual(len(clone.truth_log()), 1)
                self.assertEqual(len(clone.target_refs()), expected_writes)

    async def test_port_exposes_no_clone_oracle_and_base_authentication_is_synthetic(self) -> None:
        ticket = self._ticket(ChangeKind.CREATE_DRAFT)
        auth = await self.port.authenticate_base(ticket)
        self.assertEqual(auth, f"TEST:{SYNTHETIC_MARKER}:{SIMULATOR}:{ticket.base_fingerprint}")
        for public_oracle in ("truth_log", "read_state", "write_count", "target_refs"):
            self.assertFalse(hasattr(self.port, public_oracle), public_oracle)

        result = await self.port.create_draft(ticket, self._permit(ticket), payload_to_dict(_payload()))
        public_values = repr(dict(result))
        self.assertNotIn("truth_log", public_values)
        self.assertNotIn("signature", public_values)
        self.assertNotIn("receipt", public_values)
        self.assertNotIn("payload", result)
        self.assertNotIn("status", result)

    async def test_simulator_configuration_rejects_wrong_identity_and_non_test_key(self) -> None:
        with self.assertRaises(ValueError):
            SyntheticPermitAuthority(SIMULATOR, b"short")
        wrong_authority = SyntheticPermitAuthority("SIM-OTHER-CLONE", TEST_KEY)
        with self.assertRaises(ValueError):
            self._port(self.clone, wrong_authority)
        with self.assertRaisesRegex(ValueError, "SIMULATION_SCOPE_ALREADY_BOUND"):
            self._port(
                self.clone,
                self.authority,
                tenant="SIM-TENANT-OTHER",
            )
        with self.assertRaisesRegex(ValueError, "SIMULATION_SCOPE_ALREADY_BOUND"):
            self._port(
                self.clone,
                self.authority,
                company="SIM-COMPANY-OTHER",
            )
        with self.assertRaises(ValueError):
            SimulatedOneCWritePort(
                object(), tenant_id=TENANT, company_id=COMPANY, organization=ORGANIZATION,
                permit_authority=self.authority,
            )  # type: ignore[arg-type]

        # The production skeleton remains unwired and is not replaced by this local adapter.
        with self.assertRaises(NotWired):
            await NonOperationalWritePort().verify_ticket(self._ticket(ChangeKind.CREATE_DRAFT))

    async def test_cross_adapter_call_id_replay_and_conflict_cannot_mutate_twice(self) -> None:
        second_port = self._port(
            self.clone,
            SyntheticPermitAuthority(SIMULATOR, TEST_KEY),
        )
        first_payload = _payload(supplier_number="SIM-CALL-ID-ORIGINAL")
        first_ticket = self._ticket(
            ChangeKind.CREATE_DRAFT,
            call_id="SIM-CROSS-ADAPTER-CALL",
            payload=first_payload,
        )
        first_permit = self._permit(first_ticket)

        # The first synthetic call is refused before write but consumes the call identity.
        # A second adapter cannot replay it or reuse the same call ID for changed content.
        self.clone.fail_next("reject")
        with self.assertRaises(SyntheticPortRefusal) as first_refusal:
            await self.port.create_draft(first_ticket, first_permit, payload_to_dict(first_payload))
        self.assertEqual(first_refusal.exception.code, "CLONE_REFUSED:REJECTED")
        self.assertEqual(self.clone.write_count, 0)
        state_after_first_call = self.clone.state_fingerprint()

        with self.assertRaises(SyntheticPortRefusal) as replay:
            await second_port.create_draft(first_ticket, first_permit, payload_to_dict(first_payload))
        self.assertEqual(replay.exception.code, "CLONE_REFUSED:CALL_REPLAYED")
        self.assertEqual(self.clone.write_count, 0)
        self.assertEqual(self.clone.state_fingerprint(), state_after_first_call)

        changed_payload = _payload(supplier_number="SIM-CALL-ID-CONFLICT")
        conflicting_ticket = replace(
            first_ticket,
            digest_set_hash=payload_digest(changed_payload, None),
        )
        conflicting_permit = self._permit(conflicting_ticket)
        with self.assertRaises(SyntheticPortRefusal) as conflict:
            await second_port.create_draft(
                conflicting_ticket,
                conflicting_permit,
                payload_to_dict(changed_payload),
            )
        self.assertEqual(conflict.exception.code, "CLONE_REFUSED:CALL_ID_CONFLICT")
        self.assertEqual(self.clone.write_count, 0)
        self.assertEqual(self.clone.state_fingerprint(), state_after_first_call)
        self.assertEqual(len(self.clone.target_refs()), 0)

    async def test_permit_expiring_after_preflight_is_rechecked_before_call_id_reservation(self) -> None:
        payload = _payload(supplier_number="SIM-EXPIRING-PERMIT")
        ticket = self._ticket(
            ChangeKind.CREATE_DRAFT,
            call_id="SIM-PERMIT-EXPIRES-BEFORE-ADMISSION",
            payload=payload,
        )
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=1)
        permit = self._permit(ticket, expires_at=expires_at)
        preflight_results: list[tuple[bool, datetime]] = []
        original_verify = self.authority.verify
        original_apply = self.clone.apply_for_simulation

        def record_preflight(candidate_ticket, candidate_permit, now):
            verified = original_verify(candidate_ticket, candidate_permit, now)
            preflight_results.append((verified, now))
            return verified

        def expire_before_admission(*args, **kwargs):
            remaining = (expires_at - datetime.now(timezone.utc)).total_seconds()
            time.sleep(max(0.01, remaining + 0.05))
            return original_apply(*args, **kwargs)

        self.authority.verify = record_preflight  # type: ignore[method-assign]
        self.clone.apply_for_simulation = expire_before_admission  # type: ignore[method-assign]
        before = self.clone.state_fingerprint()
        try:
            with self.assertRaises(SyntheticPortRefusal) as raised:
                await self.port.create_draft(ticket, permit, payload_to_dict(payload))
        finally:
            self.authority.verify = original_verify  # type: ignore[method-assign]
            self.clone.apply_for_simulation = original_apply  # type: ignore[method-assign]

        self.assertEqual(len(preflight_results), 1)
        self.assertTrue(preflight_results[0][0], "permit must pass the adapter preflight")
        self.assertLess(preflight_results[0][1], expires_at)
        self.assertEqual(raised.exception.code, "CLONE_REFUSED:PERMIT_EXPIRED")
        self.assertEqual(self.clone.state_fingerprint(), before)
        self.assertEqual(self.clone.write_count, 0)
        self.assertEqual(self.clone.truth_log(), ())

        # Expiry rejection precedes call-ID reservation; the same identity remains usable
        # with a newly issued, currently valid synthetic permit.
        fresh_permit = self._permit(ticket)
        result = await self.port.create_draft(ticket, fresh_permit, payload_to_dict(payload))
        self.assertEqual(result["outcome"], "APPLIED_TEST_ONLY")
        self.assertEqual(self.clone.write_count, 1)
        self.assertEqual(len(self.clone.target_refs()), 1)


def _capture(call):
    try:
        return call()
    except Exception as exc:
        return exc


if __name__ == "__main__":
    unittest.main()
