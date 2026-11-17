"""Focused offline acceptance tests for the S12-03 synthetic principal registry."""
from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from business_ai_gateway.phase2.simulation.principal_registry import (
    LANE,
    ApprovalRecord,
    OfflinePrincipalRegistry,
    PrincipalRegistryError,
)


class PrincipalRegistryOfflineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = OfflinePrincipalRegistry()
        self.registry.register_principal(
            "TEST-REQUESTER-ACCOUNT", "TEST-PERSON-REQUESTER", {"requester"}, lane=LANE
        )
        self.registry.register_principal(
            "TEST-APPROVER-ACCOUNT", "TEST-PERSON-APPROVER", {"approver"}, lane=LANE
        )
        self.approval = self.registry.record_approval(
            change_id="TEST-CHANGE-001",
            approval_digest="a" * 64,
            requester_account_id="TEST-REQUESTER-ACCOUNT",
            approver_account_id="TEST-APPROVER-ACCOUNT",
            lane=LANE,
        )

    def test_distinct_test_persons_create_bound_immutable_approval_and_effect(self) -> None:
        approval_before = self.registry.approvals(lane=LANE)
        permit = self.registry.dequeue(
            approval_id=self.approval.approval_id,
            change_id="TEST-CHANGE-001",
            approval_digest="a" * 64,
            lane=LANE,
        )

        effect = self.registry.apply_simulated(permit, lane=LANE)

        self.assertIsInstance(self.approval, ApprovalRecord)
        self.assertEqual(self.approval.requester_person_id, "TEST-PERSON-REQUESTER")
        self.assertEqual(self.approval.approver_person_id, "TEST-PERSON-APPROVER")
        self.assertEqual(self.approval.change_id, "TEST-CHANGE-001")
        self.assertEqual(self.approval.approval_digest, "a" * 64)
        self.assertEqual(self.approval.lane, "TEST")
        self.assertTrue(self.approval.synthetic)
        with self.assertRaises(FrozenInstanceError):
            self.approval.approval_digest = "b" * 64  # type: ignore[misc]
        self.assertEqual(self.registry.approvals(lane=LANE), approval_before)
        self.assertEqual(self.registry.effects(lane=LANE), (effect,))
        self.assertEqual(effect.lane, "TEST")
        self.assertTrue(effect.synthetic)

    def test_two_accounts_for_same_person_cannot_approve_and_leave_ledger_unchanged(self) -> None:
        self.registry.register_principal(
            "TEST-APPROVER-ALIAS", "TEST-PERSON-REQUESTER", {"approver"}, lane=LANE
        )
        approvals_before = self.registry.approvals(lane=LANE)

        with self.assertRaisesRegex(PrincipalRegistryError, "APPROVER_NOT_INDEPENDENT"):
            self.registry.record_approval(
                change_id="TEST-CHANGE-ALIAS",
                approval_digest="b" * 64,
                requester_account_id="TEST-REQUESTER-ACCOUNT",
                approver_account_id="TEST-APPROVER-ALIAS",
                lane=LANE,
            )

        self.assertEqual(self.registry.approvals(lane=LANE), approvals_before)
        self.assertEqual(self.registry.effects(lane=LANE), ())

    def test_same_account_cannot_self_approve(self) -> None:
        self.registry.register_principal(
            "TEST-BOTH-ROLE-ACCOUNT",
            "TEST-PERSON-SELF",
            {"requester", "approver"},
            lane=LANE,
        )
        before = self.registry.approvals(lane=LANE)

        with self.assertRaisesRegex(PrincipalRegistryError, "APPROVER_NOT_INDEPENDENT"):
            self.registry.record_approval(
                change_id="TEST-CHANGE-SELF",
                approval_digest="c" * 64,
                requester_account_id="TEST-BOTH-ROLE-ACCOUNT",
                approver_account_id="TEST-BOTH-ROLE-ACCOUNT",
                lane=LANE,
            )

        self.assertEqual(self.registry.approvals(lane=LANE), before)
        self.assertEqual(self.registry.effects(lane=LANE), ())

    def test_change_or_digest_mismatch_refuses_without_mutating_approval_or_effects(self) -> None:
        before = self.registry.approvals(lane=LANE)
        for change_id, digest in (("TEST-CHANGE-OTHER", "a" * 64),
                                  ("TEST-CHANGE-001", "b" * 64)):
            with self.subTest(change_id=change_id, digest=digest):
                with self.assertRaisesRegex(PrincipalRegistryError, "APPROVAL_BINDING_MISMATCH"):
                    self.registry.dequeue(
                        approval_id=self.approval.approval_id,
                        change_id=change_id,
                        approval_digest=digest,
                        lane=LANE,
                    )
                self.assertEqual(self.registry.approvals(lane=LANE), before)
                self.assertEqual(self.registry.effects(lane=LANE), ())

    def test_revoked_principal_is_rechecked_at_dequeue(self) -> None:
        self.registry.register_principal(
            "TEST-APPROVER-ACCOUNT", "TEST-PERSON-APPROVER", {"approver"}, active=False, lane=LANE
        )
        approvals_before = self.registry.approvals(lane=LANE)

        with self.assertRaisesRegex(PrincipalRegistryError, "PRINCIPAL_INACTIVE"):
            self.registry.dequeue(
                approval_id=self.approval.approval_id,
                change_id="TEST-CHANGE-001",
                approval_digest="a" * 64,
                lane=LANE,
            )

        self.assertEqual(self.registry.approvals(lane=LANE), approvals_before)
        self.assertEqual(self.registry.effects(lane=LANE), ())

    def test_epoch_change_after_dequeue_refuses_before_simulated_effect(self) -> None:
        permit = self.registry.dequeue(
            approval_id=self.approval.approval_id,
            change_id="TEST-CHANGE-001",
            approval_digest="a" * 64,
            lane=LANE,
        )
        approvals_before = self.registry.approvals(lane=LANE)
        self.registry.register_principal(
            "TEST-APPROVER-ACCOUNT",
            "TEST-PERSON-APPROVER",
            {"approver", "requester"},
            lane=LANE,
        )

        with self.assertRaisesRegex(PrincipalRegistryError, "PRINCIPAL_EPOCH_CHANGED"):
            self.registry.apply_simulated(permit, lane=LANE)

        self.assertEqual(self.registry.approvals(lane=LANE), approvals_before)
        self.assertEqual(self.registry.effects(lane=LANE), ())

    def test_revocation_after_dequeue_refuses_before_simulated_effect(self) -> None:
        permit = self.registry.dequeue(
            approval_id=self.approval.approval_id,
            change_id="TEST-CHANGE-001",
            approval_digest="a" * 64,
            lane=LANE,
        )
        approvals_before = self.registry.approvals(lane=LANE)
        self.registry.register_principal(
            "TEST-APPROVER-ACCOUNT", "TEST-PERSON-APPROVER", {"approver"}, active=False, lane=LANE
        )

        with self.assertRaisesRegex(PrincipalRegistryError, "PRINCIPAL_INACTIVE"):
            self.registry.apply_simulated(permit, lane=LANE)

        self.assertEqual(self.registry.approvals(lane=LANE), approvals_before)
        self.assertEqual(self.registry.effects(lane=LANE), ())

    def test_missing_or_unsupported_lane_fails_closed(self) -> None:
        approvals_before = self.registry.approvals(lane=LANE)

        with self.assertRaisesRegex(PrincipalRegistryError, "TEST_LANE_REQUIRED"):
            self.registry.record_approval(
                change_id="TEST-CHANGE-NO-LANE",
                approval_digest="d" * 64,
                requester_account_id="TEST-REQUESTER-ACCOUNT",
                approver_account_id="TEST-APPROVER-ACCOUNT",
                lane="PRODUCTION",
            )
        with self.assertRaises(TypeError):
            self.registry.record_approval(  # type: ignore[call-arg]
                change_id="TEST-CHANGE-NO-LANE",
                approval_digest="d" * 64,
                requester_account_id="TEST-REQUESTER-ACCOUNT",
                approver_account_id="TEST-APPROVER-ACCOUNT",
            )
        with self.assertRaisesRegex(PrincipalRegistryError, "TEST_LANE_REQUIRED"):
            self.registry.apply_simulated(
                self.registry.dequeue(
                    approval_id=self.approval.approval_id,
                    change_id="TEST-CHANGE-001",
                    approval_digest="a" * 64,
                    lane=LANE,
                ),
                lane="",
            )

        self.assertEqual(self.registry.approvals(lane=LANE), approvals_before)
        self.assertEqual(self.registry.effects(lane=LANE), ())


if __name__ == "__main__":
    unittest.main()
