from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256

import pytest

from business_ai_gateway.phase2.aliases import (
    ActorKind,
    AliasResolver,
    AliasScope,
    Approver,
    Reference,
    SupplierEntity,
)
from business_ai_gateway.phase2.intake_entity_resolution import (
    EntityResolutionState,
    IntakeEntityResolution,
    confirm_ambiguous_entity,
    resolve_extracted_entity,
)
from business_ai_gateway.phase2.intake_extraction import (
    ExtractedValue,
    ExtractionState,
    SourceProvenance,
    UploadFormat,
)


NOW = datetime(2026, 11, 18, tzinfo=UTC)
SCOPE_A = AliasScope("tenant-1", "company-a")
SCOPE_B = AliasScope("tenant-1", "company-b")
HUMAN = Approver("reviewer-1", ActorKind.HUMAN)


def _resolver() -> AliasResolver:
    return AliasResolver(clock=lambda: NOW)


def _provenance(row: int = 1) -> SourceProvenance:
    return SourceProvenance(
        sha256(f"source-{row}".encode()).hexdigest(), UploadFormat.CSV, None, row, 1, "supplier",
    )


def _value(row: int = 1, text: str = "Moldretail Group") -> ExtractedValue:
    return ExtractedValue(text, _provenance(row), ExtractionState.REVIEW_REQUIRED)


def _ambiguous_resolver() -> AliasResolver:
    resolver = _resolver()
    for entity_id, scope in (("a-1", SCOPE_A), ("a-2", SCOPE_A), ("b-1", SCOPE_B)):
        result = resolver.add_entity(SupplierEntity(entity_id, scope, "Moldretail Group"))
        assert result.ok
    return resolver


def test_same_name_candidates_remain_company_scoped_and_review_only() -> None:
    resolver = _ambiguous_resolver()

    result_a = resolve_extracted_entity(resolver, SCOPE_A, _value())
    result_b = resolve_extracted_entity(resolver, SCOPE_B, _value(2))

    assert result_a.state is EntityResolutionState.AMBIGUOUS_REVIEW
    assert result_a.candidate_ids == ("a-1", "a-2")
    assert result_a.queue_item_id is not None
    assert result_b.state is EntityResolutionState.UNMATCHED_REVIEW
    assert result_b.suggestions == ("b-1",)
    assert result_a.provenance == _provenance()
    assert result_b.provenance == _provenance(2)
    assert not result_a.proposal_allowed and not result_b.proposal_allowed


def test_ambiguous_choice_preserves_only_queue_bound_source_provenance() -> None:
    resolver = _ambiguous_resolver()
    original = resolve_extracted_entity(resolver, SCOPE_A, _value())
    assert original.state is EntityResolutionState.AMBIGUOUS_REVIEW
    assert original.queue_item_id is not None

    forged = IntakeEntityResolution(
        original.state,
        original.code,
        original.scope,
        _provenance(9),
        candidate_ids=original.candidate_ids,
        suggestions=original.suggestions,
        queue_item_id=original.queue_item_id,
    )
    refused = confirm_ambiguous_entity(
        resolver, forged, SCOPE_A,
        chosen_entity_id="a-1", approver=HUMAN, reason="verified source row",
    )
    accepted = confirm_ambiguous_entity(
        resolver, original, SCOPE_A,
        chosen_entity_id="a-1", approver=HUMAN, reason="verified source row",
    )

    assert refused.state is EntityResolutionState.REFUSED
    assert refused.code == "INPUT_REFUSED"
    assert accepted.state is EntityResolutionState.HUMAN_CONFIRMED_REVIEW_REQUIRED
    assert accepted.provenance == _provenance()
    assert accepted.selected_entity_id == "a-1"
    assert accepted.proposal_allowed is False


def test_reused_stable_queue_registers_each_resolved_source_cell() -> None:
    resolver = _ambiguous_resolver()
    first = resolve_extracted_entity(resolver, SCOPE_A, _value(1))
    second = resolve_extracted_entity(resolver, SCOPE_A, _value(2))

    assert first.queue_item_id == second.queue_item_id
    for resolution, provenance in ((first, _provenance(1)), (second, _provenance(2))):
        result = confirm_ambiguous_entity(
            resolver, resolution, SCOPE_A,
            chosen_entity_id="a-2", approver=HUMAN, reason="same scoped ambiguity",
        )
        assert result.state is EntityResolutionState.HUMAN_CONFIRMED_REVIEW_REQUIRED
        assert result.provenance == provenance


def test_conflicting_replay_does_not_confirm_a_second_entity() -> None:
    resolver = _ambiguous_resolver()
    resolution = resolve_extracted_entity(resolver, SCOPE_A, _value())
    first = confirm_ambiguous_entity(
        resolver, resolution, SCOPE_A,
        chosen_entity_id="a-1", approver=HUMAN, reason="first decision",
    )
    conflict = confirm_ambiguous_entity(
        resolver, resolution, SCOPE_A,
        chosen_entity_id="a-2", approver=HUMAN, reason="conflicting replay",
    )

    assert first.state is EntityResolutionState.HUMAN_CONFIRMED_REVIEW_REQUIRED
    assert conflict.state is EntityResolutionState.AMBIGUOUS_REVIEW
    assert conflict.code == "DECISION_CONFLICT"
    assert conflict.selected_entity_id is None
    assert conflict.proposal_allowed is False


def test_exact_namespaced_reference_still_requires_review() -> None:
    resolver = _resolver()
    entity = SupplierEntity(
        "a-1", SCOPE_A, "Moldretail Group", (Reference("erp_code", "MR-001"),),
    )
    assert resolver.add_entity(entity).ok

    result = resolve_extracted_entity(
        resolver, SCOPE_A, _value(), reference=Reference("erp_code", "MR-001"),
    )

    assert result.state is EntityResolutionState.MATCH_REVIEW_REQUIRED
    assert result.selected_entity_id == "a-1"
    assert result.proposal_allowed is False


@pytest.mark.parametrize(
    ("approver", "choice", "reason", "scope", "expected_state", "expected_code"),
    [
        (Approver("automation-1", ActorKind.AUTOMATION), "a-1", "reason", SCOPE_A,
         EntityResolutionState.AMBIGUOUS_REVIEW, "APPROVER_NOT_HUMAN"),
        (HUMAN, "outside-scope", "reason", SCOPE_A,
         EntityResolutionState.AMBIGUOUS_REVIEW, "CHOICE_NOT_CANDIDATE"),
        (HUMAN, "a-1", "", SCOPE_A,
         EntityResolutionState.AMBIGUOUS_REVIEW, "REASON_REQUIRED"),
        (HUMAN, "a-1", "reason", SCOPE_B,
         EntityResolutionState.REFUSED, "INPUT_REFUSED"),
    ],
)
def test_invalid_human_choice_fails_closed(
    approver: Approver,
    choice: str,
    reason: str,
    scope: AliasScope,
    expected_state: EntityResolutionState,
    expected_code: str,
) -> None:
    resolver = _ambiguous_resolver()
    resolution = resolve_extracted_entity(resolver, SCOPE_A, _value())

    result = confirm_ambiguous_entity(
        resolver, resolution, scope,
        chosen_entity_id=choice, approver=approver, reason=reason,
    )

    assert result.state is expected_state
    assert result.code == expected_code
    assert result.selected_entity_id is None
    assert result.proposal_allowed is False


def test_malformed_reference_and_incomplete_slotted_inputs_refuse_without_echo() -> None:
    resolver = _resolver()
    secret_text = "supplier-secret-marker"
    malformed_reference = resolve_extracted_entity(
        resolver, SCOPE_A, _value(text=secret_text), reference=object(),  # type: ignore[arg-type]
    )
    partial_value = object.__new__(ExtractedValue)
    object.__setattr__(partial_value, "text", secret_text)
    partial_provenance = object.__new__(SourceProvenance)
    object.__setattr__(partial_provenance, "source_sha256", _provenance().source_sha256)
    malformed_value = ExtractedValue(secret_text, partial_provenance)  # type: ignore[arg-type]
    partial_resolution = object.__new__(IntakeEntityResolution)
    object.__setattr__(partial_resolution, "scope", SCOPE_A)

    refused_value = resolve_extracted_entity(resolver, SCOPE_A, partial_value)
    refused_provenance = resolve_extracted_entity(resolver, SCOPE_A, malformed_value)
    refused_resolution = confirm_ambiguous_entity(
        resolver, partial_resolution, SCOPE_A,
        chosen_entity_id="a-1", approver=HUMAN, reason="reason",
    )

    assert malformed_reference.state is EntityResolutionState.REFUSED
    assert malformed_reference.code == "INPUT_REFUSED"
    assert secret_text not in malformed_reference.code
    assert refused_value.state is EntityResolutionState.REFUSED
    assert refused_provenance.state is EntityResolutionState.REFUSED
    assert refused_resolution.state is EntityResolutionState.REFUSED
