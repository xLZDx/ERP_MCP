"""Focused acceptance tests for V2-S12-04's offline synthetic grant budget policy."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Barrier
import unittest

from business_ai_gateway.phase2.simulation.grant_policy import (
    EffectOutcome,
    GrantOperation,
    GrantPolicyError,
    OfflineGrantPolicyEngine,
    PolicyRequest,
    ReservationState,
    StandingGrant,
)


NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
COMPANY = "TEST-COMPANY"
GRANT = "TEST-GRANT"


def make_grant(**changes: object) -> StandingGrant:
    values: dict[str, object] = {
        "grant_id": GRANT,
        "company_id": COMPANY,
        "currency": "EUR",
        "amount_limit": Decimal("1000"),
        "create_update_limit": 20,
        "post_unpost_limit": 20,
        "valid_from": NOW - timedelta(days=1),
        "valid_to": NOW + timedelta(days=1),
        "allowed_operations": frozenset(GrantOperation),
    }
    values.update(changes)
    return StandingGrant(**values)  # type: ignore[arg-type]


def make_request(
    request_id: str,
    operation: GrantOperation,
    *,
    document_id: str = "TEST-DOCUMENT",
    amount: str = "100",
    company_id: str = COMPANY,
    currency: str = "EUR",
    grant_id: str = GRANT,
) -> PolicyRequest:
    return PolicyRequest(
        request_id=request_id,
        grant_id=grant_id,
        company_id=company_id,
        currency=currency,
        operation=operation,
        document_id=document_id,
        gross_amount=Decimal(amount),
        lane="TEST",
        synthetic=True,
    )


class GrantPolicyOfflineAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = OfflineGrantPolicyEngine()
        self.grant = make_grant()
        self.policy.register_grant(self.grant, lane="TEST")

    def reserve(self, request: PolicyRequest, *, now: datetime = NOW):
        return self.policy.reserve(request, now=now, lane="TEST")

    def consume(self, request: PolicyRequest, *, now: datetime = NOW):
        reservation = self.reserve(request, now=now)
        return self.policy.settle(request.request_id, outcome=EffectOutcome.EXISTS, lane="TEST")

    def assert_policy_error(self, code: str, call) -> None:
        with self.assertRaises(GrantPolicyError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_ct13_operation_impacts_and_projection_counters(self) -> None:
        cases = (
            (GrantOperation.CREATE_DRAFT, "100", Decimal("100"), 1, 0),
            (GrantOperation.CONTRACT_UPDATE, "100", Decimal("0"), 1, 0),
            (GrantOperation.POST, "100", Decimal("100"), 0, 1),
            (GrantOperation.UNPOST, "100", Decimal("0"), 0, 1),
            (GrantOperation.REPOST, "100", Decimal("0"), 0, 1),
            (GrantOperation.CORRECTION, "100", Decimal("100"), 1, 0),
        )
        for index, (operation, amount, expected_amount, create_count, post_count) in enumerate(cases):
            with self.subTest(operation=operation):
                policy = OfflineGrantPolicyEngine()
                policy.register_grant(self.grant, lane="TEST")
                request = make_request(f"impact-{index}", operation, document_id=f"doc-{index}", amount=amount)
                reservation = policy.reserve(request, now=NOW, lane="TEST")
                usage = policy.usage(GRANT, lane="TEST")
                self.assertEqual(reservation.amount, expected_amount)
                self.assertEqual(usage.create_update_reserved, create_count)
                self.assertEqual(usage.post_unpost_reserved, post_count)

    def test_post_of_new_grant_created_draft_consumes_only_unreserved_delta(self) -> None:
        draft = make_request("new-draft", GrantOperation.CREATE_DRAFT, amount="100", document_id="new-doc")
        self.consume(draft)
        self.assertEqual(self.policy.amount_consumed(GRANT, "new-doc", lane="TEST"), Decimal("100"))

        post = make_request("post-new-draft", GrantOperation.POST, amount="100", document_id="new-doc")
        self.assertEqual(self.reserve(post).amount, Decimal("0"))

    def test_post_of_preexisting_draft_reserves_the_full_gross_amount(self) -> None:
        post = make_request("post-preexisting", GrantOperation.POST, amount="175", document_id="old-doc")
        self.assertEqual(self.reserve(post).amount, Decimal("175"))

    def test_correction_reserves_positive_delta_and_decrease_never_refunds(self) -> None:
        initial = make_request("create-correction-doc", GrantOperation.CREATE_DRAFT,
                               amount="100", document_id="correction-doc")
        self.consume(initial)

        increase = make_request("increase", GrantOperation.CORRECTION,
                                amount="135", document_id="correction-doc")
        self.assertEqual(self.reserve(increase).amount, Decimal("35"))
        self.policy.settle("increase", outcome=EffectOutcome.EXISTS, lane="TEST")
        self.assertEqual(self.policy.amount_consumed(GRANT, "correction-doc", lane="TEST"), Decimal("135"))

        decrease = make_request("decrease", GrantOperation.CORRECTION,
                                amount="90", document_id="correction-doc")
        self.assertEqual(self.reserve(decrease).amount, Decimal("0"))
        self.policy.settle("decrease", outcome=EffectOutcome.EXISTS, lane="TEST")
        self.assertEqual(self.policy.amount_consumed(GRANT, "correction-doc", lane="TEST"), Decimal("135"))

    def test_contract_update_unpost_and_repost_reserve_zero_amount_but_count(self) -> None:
        operations = (GrantOperation.CONTRACT_UPDATE, GrantOperation.UNPOST, GrantOperation.REPOST)
        for index, operation in enumerate(operations):
            request = make_request(f"zero-{index}", operation, document_id=f"zero-doc-{index}")
            self.assertEqual(self.reserve(request).amount, Decimal("0"))
        usage = self.policy.usage(GRANT, lane="TEST")
        self.assertEqual(usage.amount_reserved, Decimal("0"))
        self.assertEqual(usage.create_update_reserved, 1)
        self.assertEqual(usage.post_unpost_reserved, 2)

    def test_amount_create_update_and_post_unpost_limits_are_independent(self) -> None:
        policy = OfflineGrantPolicyEngine()
        policy.register_grant(make_grant(amount_limit=Decimal("1000"), create_update_limit=1,
                                         post_unpost_limit=2), lane="TEST")
        policy.reserve(make_request("one-create", GrantOperation.CREATE_DRAFT), now=NOW, lane="TEST")
        policy.reserve(make_request("one-post", GrantOperation.POST, document_id="doc-post"),
                       now=NOW, lane="TEST")
        self.assertEqual(policy.usage(GRANT, lane="TEST").remaining_create_update, 0)
        self.assertEqual(policy.usage(GRANT, lane="TEST").remaining_post_unpost, 1)
        with self.assertRaises(GrantPolicyError) as caught:
            policy.reserve(make_request("second-create", GrantOperation.CREATE_DRAFT, document_id="doc-2"),
                           now=NOW, lane="TEST")
        self.assertEqual(caught.exception.code, "BUDGET_EXCEEDED")
        policy.reserve(make_request("second-post", GrantOperation.POST, document_id="doc-post-2"),
                       now=NOW, lane="TEST")

    def test_amount_limit_includes_reserved_and_consumed_amount(self) -> None:
        policy = OfflineGrantPolicyEngine()
        policy.register_grant(make_grant(amount_limit=Decimal("100")), lane="TEST")
        policy.reserve(make_request("reserve-80", GrantOperation.CREATE_DRAFT, amount="80"),
                       now=NOW, lane="TEST")
        with self.assertRaises(GrantPolicyError) as caught:
            policy.reserve(make_request("reserve-21", GrantOperation.CREATE_DRAFT,
                                        amount="21", document_id="doc-2"), now=NOW, lane="TEST")
        self.assertEqual(caught.exception.code, "BUDGET_EXCEEDED")

    def test_grant_window_is_half_open_at_both_boundaries(self) -> None:
        start = NOW
        end = NOW + timedelta(hours=1)
        policy = OfflineGrantPolicyEngine()
        policy.register_grant(make_grant(valid_from=start, valid_to=end), lane="TEST")
        policy.reserve(make_request("at-start", GrantOperation.CREATE_DRAFT), now=start, lane="TEST")

        self.assert_policy_error(
            "GRANT_EXPIRED",
            lambda: policy.reserve(make_request("at-end", GrantOperation.CREATE_DRAFT, document_id="doc-end"),
                                   now=end, lane="TEST"),
        )
        self.assert_policy_error(
            "GRANT_EXPIRED",
            lambda: policy.reserve(make_request("before-start", GrantOperation.CREATE_DRAFT, document_id="doc-before"),
                                   now=start - timedelta(microseconds=1), lane="TEST"),
        )

    def test_missing_revoked_expired_and_unauthorized_grants_fail_closed(self) -> None:
        self.assert_policy_error(
            "GRANT_NOT_FOUND",
            lambda: self.reserve(make_request("missing", GrantOperation.CREATE_DRAFT, grant_id="MISSING")),
        )

        revoked = OfflineGrantPolicyEngine()
        revoked.register_grant(make_grant(revoked=True), lane="TEST")
        self.assert_policy_error(
            "GRANT_REVOKED",
            lambda: revoked.reserve(make_request("revoked", GrantOperation.CREATE_DRAFT), now=NOW, lane="TEST"),
        )

        not_yet_valid = OfflineGrantPolicyEngine()
        not_yet_valid.register_grant(make_grant(valid_from=NOW + timedelta(seconds=1)), lane="TEST")
        self.assert_policy_error(
            "GRANT_EXPIRED",
            lambda: not_yet_valid.reserve(make_request("not-yet-valid", GrantOperation.CREATE_DRAFT),
                                          now=NOW, lane="TEST"),
        )

        update = replace(self.grant, allowed_operations=frozenset({GrantOperation.POST}))
        self.policy.update_grant(update, lane="TEST")
        self.assert_policy_error(
            "NOT_ENTITLED",
            lambda: self.reserve(make_request("not-entitled", GrantOperation.CREATE_DRAFT)),
        )

    def test_company_and_currency_scope_are_revalidated_at_dequeue(self) -> None:
        for request, revised in (
            (make_request("company-mismatch", GrantOperation.CREATE_DRAFT, company_id="OTHER-COMPANY"), self.grant),
            (make_request("currency-mismatch", GrantOperation.CREATE_DRAFT, currency="USD"), self.grant),
        ):
            with self.subTest(request=request.request_id):
                self.assert_policy_error("SCOPE_MISMATCH", lambda: self.reserve(request))

        request = make_request("scope-revised", GrantOperation.CREATE_DRAFT)
        self.reserve(request)
        self.policy.update_grant(replace(self.grant, company_id="OTHER-COMPANY"), lane="TEST")
        self.assert_policy_error(
            "SCOPE_MISMATCH",
            lambda: self.policy.revalidate_at_dequeue(request, now=NOW, lane="TEST"),
        )

    def test_revocation_and_expiry_between_reservation_and_dequeue_are_rechecked(self) -> None:
        for replacement, expected in (
            (replace(self.grant, revoked=True), "GRANT_REVOKED"),
            (replace(self.grant, valid_to=NOW), "GRANT_EXPIRED"),
        ):
            with self.subTest(expected=expected):
                policy = OfflineGrantPolicyEngine()
                policy.register_grant(self.grant, lane="TEST")
                request = make_request(f"dequeue-{expected}", GrantOperation.CREATE_DRAFT)
                policy.reserve(request, now=NOW, lane="TEST")
                policy.update_grant(replacement, lane="TEST")
                with self.assertRaises(GrantPolicyError) as caught:
                    policy.revalidate_at_dequeue(request, now=NOW, lane="TEST")
                self.assertEqual(caught.exception.code, expected)

    def test_reduced_remaining_budget_is_detected_at_dequeue(self) -> None:
        request = make_request("lowered-budget", GrantOperation.CREATE_DRAFT, amount="100")
        self.reserve(request)
        self.policy.update_grant(replace(self.grant, amount_limit=Decimal("99")), lane="TEST")
        self.assert_policy_error(
            "BUDGET_CHANGED",
            lambda: self.policy.revalidate_at_dequeue(request, now=NOW, lane="TEST"),
        )

    def test_dequeue_rejects_changed_request_payload_and_retains_reservation(self) -> None:
        original = make_request("dequeue-identity", GrantOperation.CREATE_DRAFT, amount="100")
        changed_payloads = (
            replace(original, company_id="OTHER-COMPANY"),
            replace(original, currency="USD"),
            replace(original, operation=GrantOperation.POST),
            replace(original, document_id="OTHER-DOCUMENT"),
            replace(original, gross_amount=Decimal("101")),
        )
        for changed in changed_payloads:
            with self.subTest(changed=changed):
                policy = OfflineGrantPolicyEngine()
                policy.register_grant(self.grant, lane="TEST")
                reserved = policy.reserve(original, now=NOW, lane="TEST")

                with self.assertRaises(GrantPolicyError) as caught:
                    policy.revalidate_at_dequeue(changed, now=NOW, lane="TEST")

                self.assertEqual(caught.exception.code, "DEQUEUE_IDENTITY_MISMATCH")
                still_reserved = policy.reservation(original.request_id, lane="TEST")
                self.assertEqual(still_reserved.state, ReservationState.RESERVED)
                self.assertIs(still_reserved, reserved)
                self.assertEqual(still_reserved.request, original)

    def test_unknown_outcome_keeps_reservation_until_independently_resolved_e6(self) -> None:
        """E6 is synthetic-only: uncertain effects hold both amount and operation quota."""
        request = make_request("unknown-effect", GrantOperation.CREATE_DRAFT, amount="100")
        self.reserve(request)
        unknown = self.policy.settle(request.request_id, outcome=EffectOutcome.UNKNOWN, lane="TEST")
        self.assertEqual(unknown.state, ReservationState.UNKNOWN)
        usage = self.policy.usage(GRANT, lane="TEST")
        self.assertEqual(usage.amount_reserved, Decimal("100"))
        self.assertEqual(usage.create_update_reserved, 1)
        self.assert_policy_error(
            "OUTCOME_UNRESOLVED",
            lambda: self.policy.resolve_unknown(request.request_id, outcome=EffectOutcome.UNKNOWN,
                                                independently_proven=False, lane="TEST"),
        )
        self.assertEqual(self.policy.reservation(request.request_id, lane="TEST").state,
                         ReservationState.UNKNOWN)

    def test_proven_absence_releases_reservation_and_idempotent_resolution_e24(self) -> None:
        """E24 is synthetic-only: only independent proof of absence releases held budget."""
        request = make_request("absent-effect", GrantOperation.CREATE_DRAFT, amount="100")
        self.reserve(request)
        self.policy.settle(request.request_id, outcome=EffectOutcome.UNKNOWN, lane="TEST")
        released = self.policy.resolve_unknown(request.request_id, outcome=EffectOutcome.PROVEN_ABSENT,
                                               independently_proven=True, lane="TEST")
        self.assertEqual(released.state, ReservationState.RELEASED)
        self.assertEqual(self.policy.usage(GRANT, lane="TEST").amount_reserved, Decimal("0"))
        self.assertEqual(self.policy.usage(GRANT, lane="TEST").create_update_reserved, 0)
        self.assertIs(self.policy.resolve_unknown(request.request_id, outcome=EffectOutcome.PROVEN_ABSENT,
                                                  independently_proven=True, lane="TEST"), released)
        self.assertIs(self.reserve(request), released)

        retry = make_request("absent-effect-retry", GrantOperation.CREATE_DRAFT,
                             amount="100", document_id=request.document_id)
        admitted = self.reserve(retry)
        self.assertEqual(admitted.state, ReservationState.RESERVED)
        self.assertEqual(admitted.amount, Decimal("100"))

    def test_success_consumes_once_and_conflicting_replay_is_rejected(self) -> None:
        request = make_request("replay", GrantOperation.CREATE_DRAFT, amount="50")
        first = self.reserve(request)
        self.assertIs(self.reserve(request), first)
        self.policy.settle(request.request_id, outcome=EffectOutcome.EXISTS, lane="TEST")
        self.assertEqual(self.policy.amount_consumed(GRANT, request.document_id, lane="TEST"), Decimal("50"))
        self.assertEqual(self.policy.usage(GRANT, lane="TEST").amount_consumed, Decimal("50"))

        conflict = make_request("replay", GrantOperation.CREATE_DRAFT, amount="51")
        self.assert_policy_error("IDEMPOTENCY_CONFLICT", lambda: self.reserve(conflict))
        self.assertEqual(self.policy.amount_consumed(GRANT, request.document_id, lane="TEST"), Decimal("50"))

    def test_distinct_active_reservations_for_same_document_are_rejected(self) -> None:
        policy = OfflineGrantPolicyEngine()
        policy.register_grant(make_grant(amount_limit=Decimal("10000")), lane="TEST")
        first = make_request("same-doc-first", GrantOperation.CREATE_DRAFT,
                             document_id="same-doc", amount="50")
        duplicate = make_request("same-doc-second", GrantOperation.CREATE_DRAFT,
                                 document_id="same-doc", amount="50")
        reserved = policy.reserve(first, now=NOW, lane="TEST")

        # The amount cap would allow both independently; identity of the document blocks the race.
        self.assert_policy_error(
            "DOCUMENT_RESERVATION_PENDING",
            lambda: policy.reserve(duplicate, now=NOW, lane="TEST"),
        )
        self.assertEqual(policy.reservation(first.request_id, lane="TEST"), reserved)
        self.assert_policy_error(
            "RESERVATION_NOT_FOUND",
            lambda: policy.reservation(duplicate.request_id, lane="TEST"),
        )

        policy.settle(first.request_id, outcome=EffectOutcome.UNKNOWN, lane="TEST")
        settled = policy.resolve_unknown(first.request_id, outcome=EffectOutcome.EXISTS,
                                         independently_proven=True, lane="TEST")
        self.assertEqual(settled.state, ReservationState.CONSUMED)
        self.assertIs(policy.reserve(first, now=NOW, lane="TEST"), settled)
        self.assertEqual(policy.amount_consumed(GRANT, "same-doc", lane="TEST"), Decimal("50"))
        usage = policy.usage(GRANT, lane="TEST")
        self.assertEqual(usage.amount_consumed, Decimal("50"))
        self.assertEqual(usage.create_update_consumed, 1)

        duplicate_create = make_request("same-doc-third-create", GrantOperation.CREATE_DRAFT,
                                        document_id="same-doc", amount="50")
        self.assert_policy_error(
            "DOCUMENT_ALREADY_EXISTS",
            lambda: policy.reserve(duplicate_create, now=NOW, lane="TEST"),
        )
        self.assert_policy_error(
            "RESERVATION_NOT_FOUND",
            lambda: policy.reservation(duplicate_create.request_id, lane="TEST"),
        )
        self.assertEqual(policy.amount_consumed(GRANT, "same-doc", lane="TEST"), Decimal("50"))
        self.assertEqual(policy.usage(GRANT, lane="TEST").create_update_consumed, 1)

        correction = make_request("same-doc-correction", GrantOperation.CORRECTION,
                                  document_id="same-doc", amount="70")
        correction_reservation = policy.reserve(correction, now=NOW, lane="TEST")
        self.assertEqual(correction_reservation.amount, Decimal("20"))
        policy.settle(correction.request_id, outcome=EffectOutcome.EXISTS, lane="TEST")
        self.assertEqual(policy.amount_consumed(GRANT, "same-doc", lane="TEST"), Decimal("70"))
        self.assertEqual(policy.usage(GRANT, lane="TEST").create_update_consumed, 2)

        later_post = make_request("same-doc-post", GrantOperation.POST,
                                  document_id="same-doc", amount="70")
        post_reservation = policy.reserve(later_post, now=NOW, lane="TEST")
        self.assertEqual(post_reservation.amount, Decimal("0"))
        self.assertEqual(policy.reservation(later_post.request_id, lane="TEST").state,
                         ReservationState.RESERVED)
        policy.settle(later_post.request_id, outcome=EffectOutcome.EXISTS, lane="TEST")

        self.assertEqual(policy.amount_consumed(GRANT, "same-doc", lane="TEST"), Decimal("70"))
        usage = policy.usage(GRANT, lane="TEST")
        self.assertEqual(usage.amount_consumed, Decimal("70"))
        self.assertEqual(usage.create_update_consumed, 2)
        self.assertEqual(usage.post_unpost_consumed, 1)

    def test_amount_consumed_for_unknown_grant_fails_closed(self) -> None:
        self.assert_policy_error(
            "GRANT_NOT_FOUND",
            lambda: self.policy.amount_consumed("UNKNOWN-GRANT", "TEST-DOCUMENT", lane="TEST"),
        )

    def test_same_grant_registration_is_ambiguous_and_does_not_replace_original(self) -> None:
        self.assert_policy_error("GRANT_AMBIGUOUS", lambda: self.policy.register_grant(self.grant, lane="TEST"))
        request = make_request("original-remains", GrantOperation.CREATE_DRAFT)
        self.assertEqual(self.reserve(request).grant_id, GRANT)

    def test_parallel_reservations_cannot_overdraw_amount_or_count_e38(self) -> None:
        """E38 is synthetic-only and races two eligible reservations against one shared cap."""
        policy = OfflineGrantPolicyEngine()
        policy.register_grant(make_grant(amount_limit=Decimal("10"), create_update_limit=1), lane="TEST")
        barrier = Barrier(2)

        def attempt(request_id: str):
            request = make_request(request_id, GrantOperation.CREATE_DRAFT,
                                   document_id=request_id, amount="8")
            barrier.wait()
            try:
                return policy.reserve(request, now=NOW, lane="TEST")
            except GrantPolicyError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, ("parallel-a", "parallel-b")))

        successes = [item for item in outcomes if not isinstance(item, str)]
        refusals = [item for item in outcomes if isinstance(item, str)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(refusals, ["BUDGET_EXCEEDED"])
        usage = policy.usage(GRANT, lane="TEST")
        self.assertEqual(usage.amount_reserved, Decimal("8"))
        self.assertEqual(usage.create_update_reserved, 1)

    def test_non_test_lane_and_non_synthetic_grants_are_refused(self) -> None:
        self.assert_policy_error(
            "TEST_LANE_REQUIRED",
            lambda: self.policy.reserve(make_request("wrong-lane", GrantOperation.CREATE_DRAFT),
                                        now=NOW, lane="PRODUCTION"),
        )
        with self.assertRaisesRegex(ValueError, "GRANT_INVALID"):
            replace(self.grant, synthetic=False)


if __name__ == "__main__":
    unittest.main()
