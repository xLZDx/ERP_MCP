"""Phase 2 OBSERVED-only per-object EDMX change classification.

Never accepts, validates, or publishes a semantic profile. Safe conservative
representation of what the Phase 2 structural-fingerprint pass observed.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .structural_hash import StructuralFingerprint


class ChangeKind(StrEnum):
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    REMOVED = "REMOVED"


@dataclass(frozen=True, slots=True)
class ObjectChange:
    qualified_name: str
    kind: ChangeKind
    previous_sha256: str | None
    observed_sha256: str | None


@dataclass(frozen=True, slots=True)
class ObservedDiff:
    canonicalizer_version: str
    previous_raw_sha256: str
    observed_raw_sha256: str
    previous_structural_sha256: str
    observed_structural_sha256: str
    changes: tuple[ObjectChange, ...]
    unattributed_structural_change: bool
    # Explicitly no automatic approval or semantic "VALIDATED" claim.
    trust_level: str = "OBSERVED_ONLY"

    @property
    def has_changes(self) -> bool:
        return self.previous_structural_sha256 != self.observed_structural_sha256


def diff_observed(before: StructuralFingerprint, after: StructuralFingerprint) -> ObservedDiff:
    """Compare two complete observed fingerprints without any source I/O.

    An unexplained structural change cannot be classified as non-impacting;
    consumers must regard it as potentially global. This function is not an
    acceptance decision and must never mutate the accepted model head.
    """
    if not isinstance(before, StructuralFingerprint) or not isinstance(after, StructuralFingerprint):
        raise TypeError("PHASE2_FINGERPRINT_REQUIRED")
    if before.canonicalizer_version != after.canonicalizer_version:
        raise ValueError("PHASE2_CANONICALIZER_VERSION_MISMATCH")
    for fingerprint in (before, after):
        object_names = [name for name, _ in fingerprint.objects]
        if len(object_names) != len(set(object_names)):
            raise ValueError("PHASE2_DUPLICATE_OBJECT_ID")
        if any(not isinstance(name, str) or not name for name in object_names):
            raise ValueError("PHASE2_INVALID_OBJECT_ID")

    a, b = before.object_hashes(), after.object_hashes()
    changes: list[ObjectChange] = []
    for name in sorted(a.keys() | b.keys()):
        old, new = a.get(name), b.get(name)
        if old == new:
            continue
        kind = ChangeKind.ADDED if old is None else (
            ChangeKind.REMOVED if new is None else ChangeKind.MODIFIED
        )
        changes.append(ObjectChange(name, kind, old, new))
    structural_changed = before.structural_sha256 != after.structural_sha256
    if not structural_changed and changes:
        raise ValueError("PHASE2_INCONSISTENT_FINGERPRINT")
    return ObservedDiff(
        canonicalizer_version=before.canonicalizer_version,
        previous_raw_sha256=before.raw_sha256,
        observed_raw_sha256=after.raw_sha256,
        previous_structural_sha256=before.structural_sha256,
        observed_structural_sha256=after.structural_sha256,
        changes=tuple(changes),
        unattributed_structural_change=structural_changed and not bool(changes),
    )
