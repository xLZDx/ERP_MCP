"""Company-scoped, review-only entity resolution for extracted intake values.

This adapter reuses the existing AliasResolver. It preserves source-cell
provenance, never treats a display-name suggestion as a match, and never
authorizes or emits a change proposal. Ambiguous choices are recorded only
through the resolver's explicit HUMAN decision path. Unmatched values remain
unmatched until a separately curated in-scope mapping exists.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .aliases import AliasOutcome, AliasResolver, AliasScope, Approver, Reference, ResolveQuery
from .intake_extraction import (
    ExtractedValue,
    ExtractionState,
    SourceProvenance,
    UploadFormat,
)

__all__ = [
    "EntityResolutionState", "IntakeEntityResolution", "confirm_ambiguous_entity",
    "resolve_extracted_entity",
]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)


class EntityResolutionState(StrEnum):
    MATCH_REVIEW_REQUIRED = "MATCH_REVIEW_REQUIRED"
    AMBIGUOUS_REVIEW = "AMBIGUOUS_REVIEW"
    UNMATCHED_REVIEW = "UNMATCHED_REVIEW"
    HUMAN_CONFIRMED_REVIEW_REQUIRED = "HUMAN_CONFIRMED_REVIEW_REQUIRED"
    REFUSED = "REFUSED"


@dataclass(frozen=True, slots=True)
class IntakeEntityResolution:
    """Non-authoritative match evidence tied to its company and source cell."""

    state: EntityResolutionState
    code: str
    scope: AliasScope | None
    provenance: SourceProvenance | None
    candidate_ids: tuple[str, ...] = ()
    suggestions: tuple[str, ...] = ()
    queue_item_id: str | None = None
    selected_entity_id: str | None = None

    @property
    def confirmation_required(self) -> bool:
        return self.state in (EntityResolutionState.AMBIGUOUS_REVIEW,
                              EntityResolutionState.UNMATCHED_REVIEW)

    @property
    def proposal_allowed(self) -> bool:
        """Entity resolution is review evidence only; proposal authorization is elsewhere."""
        return False


def resolve_extracted_entity(
    resolver: AliasResolver,
    scope: AliasScope,
    extracted: ExtractedValue,
    *,
    reference: Reference | None = None,
) -> IntakeEntityResolution:
    """Resolve one extracted display value strictly inside the selected company scope."""
    if (type(resolver) is not AliasResolver or not _valid_scope(scope)
            or type(extracted) is not ExtractedValue
            or type(extracted.provenance) is not SourceProvenance
            or not _valid_provenance(extracted.provenance)
            or type(extracted.text) is not str
            or type(extracted.state) is not ExtractionState
            or extracted.state not in (ExtractionState.REVIEW_REQUIRED, ExtractionState.BEST_EFFORT_REVIEW)):
        return _refused()
    try:
        result = resolver.resolve(scope, ResolveQuery(reference=reference, name=extracted.text))
    except Exception:  # noqa: BLE001 - malformed or failing resolver fails closed
        return _refused(scope, extracted.provenance)

    if result.outcome is AliasOutcome.RESOLVED and result.entity_id is not None:
        return IntakeEntityResolution(
            EntityResolutionState.MATCH_REVIEW_REQUIRED, "EXACT_REFERENCE_MATCH_REVIEW",
            scope, extracted.provenance, candidate_ids=(result.entity_id,),
            selected_entity_id=result.entity_id,
        )
    if result.outcome is AliasOutcome.AMBIGUOUS:
        return IntakeEntityResolution(
            EntityResolutionState.AMBIGUOUS_REVIEW, "AMBIGUOUS_CANDIDATES_REVIEW",
            scope, extracted.provenance, candidate_ids=result.candidate_ids,
            suggestions=result.suggestions, queue_item_id=result.queue_item_id,
        )
    if result.outcome is AliasOutcome.NOT_FOUND:
        return IntakeEntityResolution(
            EntityResolutionState.UNMATCHED_REVIEW, "MANUAL_MAPPING_REQUIRED",
            scope, extracted.provenance, suggestions=result.suggestions,
        )
    return _refused(scope, extracted.provenance)


def confirm_ambiguous_entity(
    resolver: AliasResolver,
    resolution: IntakeEntityResolution,
    scope: AliasScope,
    *,
    chosen_entity_id: str,
    approver: Approver,
    reason: str,
) -> IntakeEntityResolution:
    """Record an explicit HUMAN choice for the exact scoped ambiguity queue item.

    A successful choice stays review-required and does not create a proposal.
    Unmatched values cannot use this path; they need an explicit in-scope mapping
    before they can become a candidate.
    """
    if (type(resolver) is not AliasResolver or type(resolution) is not IntakeEntityResolution
            or resolution.state is not EntityResolutionState.AMBIGUOUS_REVIEW
            or not _valid_scope(scope) or not _valid_scope(resolution.scope)
            or resolution.scope != scope
            or type(resolution.queue_item_id) is not str
            or not _valid_provenance(resolution.provenance)):
        return _refused(_safe_scope(scope), _safe_provenance(resolution))
    try:
        decision = resolver.resolve_ambiguity(
            scope, resolution.queue_item_id, chosen_entity_id, approver, reason,
        )
    except Exception:  # noqa: BLE001 - confirmation failures do not authorize a proposal
        return _refused(scope, resolution.provenance)
    if decision.outcome is not AliasOutcome.DECIDED or decision.decision is None:
        return IntakeEntityResolution(
            EntityResolutionState.AMBIGUOUS_REVIEW, decision.code or "HUMAN_DECISION_REQUIRED",
            scope, resolution.provenance, candidate_ids=resolution.candidate_ids,
            suggestions=resolution.suggestions, queue_item_id=resolution.queue_item_id,
        )
    return IntakeEntityResolution(
        EntityResolutionState.HUMAN_CONFIRMED_REVIEW_REQUIRED,
        "HUMAN_CHOICE_RECORDED_REVIEW_REQUIRED", scope, resolution.provenance,
        candidate_ids=resolution.candidate_ids,
        selected_entity_id=decision.decision.chosen_entity_id,
    )


def _refused(
    scope: AliasScope | None = None,
    provenance: SourceProvenance | None = None,
) -> IntakeEntityResolution:
    return IntakeEntityResolution(EntityResolutionState.REFUSED, "INPUT_REFUSED", scope, provenance)


def _valid_scope(scope: object) -> bool:
    if type(scope) is not AliasScope:
        return False
    try:
        return scope.key() is not None
    except Exception:  # noqa: BLE001 - forged or malformed scope fails closed
        return False


def _valid_provenance(provenance: object) -> bool:
    if type(provenance) is not SourceProvenance:
        return False
    try:
        return (
            type(provenance.source_sha256) is str
            and _SHA256.fullmatch(provenance.source_sha256) is not None
            and type(provenance.source_format) is UploadFormat
            and type(provenance.row_number) is int and provenance.row_number > 0
            and type(provenance.column_number) is int and provenance.column_number > 0
            and (provenance.sheet_name is None or type(provenance.sheet_name) is str)
            and (provenance.field_key is None or type(provenance.field_key) is str)
        )
    except Exception:  # noqa: BLE001 - forged or malformed provenance fails closed
        return False


def _safe_scope(scope: object) -> AliasScope | None:
    return scope if _valid_scope(scope) else None  # type: ignore[return-value]


def _safe_provenance(resolution: IntakeEntityResolution) -> SourceProvenance | None:
    provenance = resolution.provenance
    return provenance if _valid_provenance(provenance) else None  # type: ignore[return-value]
