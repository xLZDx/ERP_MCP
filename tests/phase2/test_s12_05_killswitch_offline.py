"""V2-S12-05 focused offline acceptance for the kill-switch evaluator.

All cases exercise pure decisions with synthetic contract values. They do not authenticate people, issue permits, or
invoke a writer/runtime.
"""
from __future__ import annotations

import unittest
from dataclasses import dataclass

from business_ai_gateway.phase2.change import (
    KILL_MATRIX,
    SWITCH_OFF,
    ChangeKind,
    KillDecision,
    KillMode,
    KillSubject,
    SwitchReading,
    effective_mode,
    evaluate_read,
    evaluate_reenable,
    evaluate_write_post,
    mode_rank,
)
from business_ai_gateway.phase2.simulation.principal_registry import LANE, OfflinePrincipalRegistry


MODES = (KillMode.STOP_ADMIT, KillMode.STOP_EFFECTS, KillMode.REVOKE)
READINGS = tuple(SwitchReading(available=True, mode=mode) for mode in MODES)
UNREADABLE = SwitchReading()


@dataclass(frozen=True, slots=True)
class SyntheticWitnessFixture:
    """Explicit TEST-lane identity fixture; not a principal-registry capability or authorization."""

    person_id: str
    lane: str = "TEST"
    synthetic: bool = True


class KillSwitchOfflineAcceptance(unittest.TestCase):
    def test_s05_01_exact_mode_order_and_precedence_matrix(self) -> None:
        self.assertEqual(tuple(mode_rank(mode) for mode in MODES), (1, 2, 3))
        self.assertEqual(mode_rank(None), 0)
        self.assertEqual(set(KILL_MATRIX), {(subject, mode) for subject in KillSubject for mode in MODES})

        expected = {
            KillSubject.PROPOSE_VALIDATE_APPROVE: (KillDecision.REFUSED,) * 3,
            KillSubject.CLAIM: (KillDecision.REFUSED,) * 3,
            KillSubject.CLAIMED_CHANGE: (
                KillDecision.RELEASE_T5X,
                KillDecision.RELEASE_T5X,
                KillDecision.RELEASE_T5X_VOID_APPROVAL,
            ),
            KillSubject.BEGIN_APPLY_ISSUE_PERMIT: (KillDecision.REFUSED,) * 3,
            KillSubject.APPLYING_NOT_PERMITTED: (KillDecision.T6R,) * 3,
            KillSubject.APPLYING_PERMITTED_UNDISPATCHED: (KillDecision.T6C_CANCEL_CAS,) * 3,
            KillSubject.APPLYING_DISPATCHED: (KillDecision.FOLLOW_CALL_NO_NEW_CALL,) * 3,
            KillSubject.APPROVED_UNCLAIMED: (
                KillDecision.KEPT,
                KillDecision.KEPT,
                KillDecision.VOIDED,
            ),
            KillSubject.OBSERVATION: (
                KillDecision.ALLOWED,
                KillDecision.ALLOWED,
                KillDecision.OBSERVATION_OPERATOR_GATED,
            ),
            KillSubject.OPERATOR_OPERATIONS: (KillDecision.ALLOWED,) * 3,
        }
        for subject, decisions in expected.items():
            with self.subTest(subject=subject):
                self.assertEqual(
                    tuple(KILL_MATRIX[(subject, mode)] for mode in MODES), decisions
                )

    def test_s05_02_to_06_write_post_evaluator_refuses_each_active_mode(self) -> None:
        frozen_kinds = (ChangeKind.CREATE_DRAFT, ChangeKind.POST, ChangeKind.UNPOST)
        for kind in frozen_kinds:
            with self.subTest(kind=kind, mode="OFF"):
                self.assertIs(evaluate_write_post(kind, SWITCH_OFF), KillDecision.PROCEED)
            for mode, reading in zip(MODES, READINGS, strict=True):
                with self.subTest(kind=kind, mode=mode):
                    self.assertIs(evaluate_write_post(kind, reading), KillDecision.REFUSED)

    def test_s05_12_historical_or_unknown_write_kind_is_refused(self) -> None:
        for kind in (ChangeKind.UPDATE_DRAFT, "POST", None, object()):
            with self.subTest(kind=kind):
                self.assertIs(evaluate_write_post(kind, SWITCH_OFF), KillDecision.REFUSED)

    def test_s05_07_read_observation_remains_available_per_precedence_matrix(self) -> None:
        expected = (
            KillDecision.ALLOWED,
            KillDecision.ALLOWED,
            KillDecision.OBSERVATION_OPERATOR_GATED,
        )
        for reading, decision in zip(READINGS, expected, strict=True):
            with self.subTest(reading=reading):
                self.assertIs(evaluate_read(reading), decision)
        self.assertIs(evaluate_read(SWITCH_OFF), KillDecision.PROCEED)
        # An unreadable switch is STOP_EFFECTS, which preserves only contract-permitted observations.
        self.assertIs(evaluate_read(UNREADABLE), KillDecision.ALLOWED)

    def test_s05_08_unreadable_or_malformed_switch_fails_closed(self) -> None:
        malformed = (
            None,
            "OFF",
            SwitchReading(available=True, mode="STOP_ADMIT"),
            SwitchReading(available=False, mode=KillMode.REVOKE),
            SwitchReading(available=1, mode=None),  # bool must be an actual bool, not an integer.
        )
        for reading in (UNREADABLE, *malformed):
            with self.subTest(reading=reading):
                self.assertIs(effective_mode(reading), KillMode.STOP_EFFECTS)
                self.assertIs(evaluate_write_post(ChangeKind.POST, reading), KillDecision.REFUSED)

    def test_s05_09_reenable_requires_successful_recovery_sweep_first(self) -> None:
        for reading in READINGS:
            with self.subTest(reading=reading):
                self.assertIs(evaluate_reenable(reading, False), KillDecision.REFUSED)
                self.assertIs(evaluate_reenable(reading, None), KillDecision.REFUSED)
                self.assertIs(evaluate_reenable(reading, True), KillDecision.ALLOWED)
        self.assertIs(evaluate_reenable(SWITCH_OFF, False), KillDecision.ALLOWED)
        self.assertIs(evaluate_reenable(UNREADABLE, True), KillDecision.REFUSED)
        self.assertIs(
            evaluate_reenable(SwitchReading(available=True, mode="REVOKE"), True),
            KillDecision.REFUSED,
        )

    def test_s05_10_requester_operator_and_recovery_witness_are_distinct_test_people(self) -> None:
        registry = OfflinePrincipalRegistry()
        requester = registry.register_principal(
            "TEST-REQUESTER-ACCOUNT", "person:test-requester-101", {"requester"}, lane=LANE
        )
        operator = registry.register_principal(
            "TEST-OPERATOR-ACCOUNT", "person:test-operator-001", {"approver"}, lane=LANE
        )
        # S12-03's registry contract only represents requester/approver capabilities. Keep the recovery witness as
        # an explicit local TEST fixture rather than inventing a registry capability or authorization.
        witness = SyntheticWitnessFixture("person:test-witness-002")
        people = (requester.person_id, operator.person_id, witness.person_id)
        fixtures = (requester, operator, witness)

        self.assertEqual(len(set(people)), 3)
        self.assertEqual(tuple(fixture.lane for fixture in fixtures), ("TEST",) * 3)
        self.assertEqual(tuple(fixture.synthetic for fixture in fixtures), (True,) * 3)

    def test_s05_11_evaluator_returns_a_model_decision_not_an_effect_receipt(self) -> None:
        for reading in (SWITCH_OFF, *READINGS, UNREADABLE):
            with self.subTest(reading=reading):
                result = evaluate_write_post(ChangeKind.CREATE_DRAFT, reading)
                reenable = evaluate_reenable(reading, True)
                # Exact enum return types carry a decision only; neither evaluator accepts/returns auth, permit, or
                # effect records.
                self.assertIs(type(result), KillDecision)
                self.assertIs(type(reenable), KillDecision)
                self.assertFalse(hasattr(result, "authorization"))
                self.assertFalse(hasattr(result, "permit"))
                self.assertFalse(hasattr(result, "effect"))


if __name__ == "__main__":
    unittest.main()
