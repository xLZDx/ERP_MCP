"""Review-only view model for authenticated document intake previews."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .aliases import AliasScope
from .intake_entity_resolution import EntityResolutionState, IntakeEntityResolution
from .intake_extraction import (
    ExtractedValue,
    ExtractionResult,
    ExtractionState,
    SourceProvenance,
    UploadFormat,
)

__all__ = [
    "IntakeMateriality", "IntakeReviewCard", "IntakeReviewField", "IntakeReviewState",
    "build_intake_review",
]


class IntakeReviewState(StrEnum):
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    MANUAL_REVIEW_ONLY = "MANUAL_REVIEW_ONLY"
    REFUSED = "REFUSED"


class IntakeMateriality(StrEnum):
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass(frozen=True, slots=True)
class IntakeReviewField:
    value: str = field(repr=False)
    provenance: SourceProvenance = field(repr=False)
    materiality: IntakeMateriality = IntakeMateriality.UNCLASSIFIED
    review_required: bool = True
    entity_resolution: IntakeEntityResolution | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class IntakeReviewCard:
    state: IntakeReviewState
    code: str
    source_sha256: str | None
    source_format: UploadFormat
    fields: tuple[IntakeReviewField, ...] = ()
    unresolved_entity_count: int = 0

    @property
    def proposal_allowed(self) -> bool:
        return False

    @property
    def apply_allowed(self) -> bool:
        return False


def build_intake_review(
    result: object,
    *,
    scope: AliasScope,
    entity_resolutions: tuple[IntakeEntityResolution, ...] = (),
) -> IntakeReviewCard:
    """Build a display card without interpreting field meaning or granting authority."""
    if type(result) is not ExtractionResult or type(scope) is not AliasScope or not _valid_scope(scope):
        return _refused()
    if type(entity_resolutions) is not tuple or any(
        type(item) is not IntakeEntityResolution
        or type(item.state) is not EntityResolutionState
        or type(item.scope) is not AliasScope
        for item in entity_resolutions
    ):
        return _refused(_source_format(result))
    if result.state is ExtractionState.REFUSED:
        if type(result.source_format) is not UploadFormat:
            return _refused()
        return IntakeReviewCard(IntakeReviewState.REFUSED, "INTAKE_REFUSED", None,
                                result.source_format)
    if result.state is ExtractionState.BEST_EFFORT_REVIEW:
        if type(result.source_format) is not UploadFormat:
            return _refused()
        return IntakeReviewCard(IntakeReviewState.MANUAL_REVIEW_ONLY, result.code,
                                result.source_sha256, result.source_format)
    if (result.state is not ExtractionState.REVIEW_REQUIRED or type(result.values) is not tuple
            or type(result.source_sha256) is not str or len(result.source_sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in result.source_sha256)
            or type(result.source_format) is not UploadFormat):
        return _refused(_source_format(result))

    by_origin: dict[tuple[object, ...], IntakeEntityResolution] = {}
    for resolution in entity_resolutions:
        if (not _valid_scope(resolution.scope) or resolution.scope != scope
                or type(resolution.provenance) is not SourceProvenance
                or not _valid_provenance(resolution.provenance)):
            return _refused(result.source_format)
        origin = _origin(resolution.provenance)
        if origin in by_origin:
            return _refused(result.source_format)
        by_origin[origin] = resolution

    fields: list[IntakeReviewField] = []
    unresolved = 0
    for item in result.values:
        if (type(item) is not ExtractedValue or type(item.text) is not str
                or type(item.provenance) is not SourceProvenance
                or not _valid_provenance(item.provenance)
                or item.state is not ExtractionState.REVIEW_REQUIRED
                or item.provenance.source_sha256 != result.source_sha256
                or item.provenance.source_format is not result.source_format):
            return _refused(result.source_format)
        resolution = by_origin.get(_origin(item.provenance))
        if resolution is not None:
            if resolution.state.value in ("AMBIGUOUS_REVIEW", "UNMATCHED_REVIEW", "REFUSED"):
                unresolved += 1
        fields.append(IntakeReviewField(item.text, item.provenance, entity_resolution=resolution))

    # Reject entity evidence that points at a cell outside this extraction result.
    origins = {_origin(item.provenance) for item in result.values}
    if any(origin not in origins for origin in by_origin):
        return _refused(result.source_format)
    return IntakeReviewCard(IntakeReviewState.REVIEW_REQUIRED, "FIELDS_REQUIRE_REVIEW",
                            result.source_sha256, result.source_format, tuple(fields), unresolved)


def _origin(provenance: SourceProvenance) -> tuple[object, ...]:
    return (provenance.source_sha256, provenance.source_format, provenance.sheet_name,
            provenance.row_number, provenance.column_number)


def _valid_scope(scope: AliasScope) -> bool:
    try:
        return scope.key() is not None
    except Exception:  # noqa: BLE001 - malformed scope fails closed
        return False


def _valid_provenance(provenance: SourceProvenance) -> bool:
    return (
        type(provenance.source_sha256) is str and len(provenance.source_sha256) == 64
        and all(ch in "0123456789abcdef" for ch in provenance.source_sha256)
        and type(provenance.source_format) is UploadFormat
        and type(provenance.row_number) is int and provenance.row_number > 0
        and type(provenance.column_number) is int and provenance.column_number > 0
        and (provenance.sheet_name is None or type(provenance.sheet_name) is str)
        and (provenance.field_key is None or type(provenance.field_key) is str)
    )


def _refused(source_format: UploadFormat = UploadFormat.OTHER) -> IntakeReviewCard:
    return IntakeReviewCard(IntakeReviewState.REFUSED, "INTAKE_REFUSED", None, source_format)


def _source_format(result: ExtractionResult) -> UploadFormat:
    try:
        return result.source_format if type(result.source_format) is UploadFormat else UploadFormat.OTHER
    except Exception:  # noqa: BLE001 - malformed parser result fails closed
        return UploadFormat.OTHER
