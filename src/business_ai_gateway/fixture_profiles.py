"""Test-only reviewed synthetic fixture semantic profiles (code-level provider, no DB rows).

A fixture profile is never a bag.semantic_profiles row, never status VALIDATED, never satisfies
the ten-native-reports rule and is always labelled SYNTHETIC_FIXTURE / L1 / native NOT_RUN.
Hard-denied unless BAG_ENVIRONMENT == "test" (settings, constructor, every lookup), and only for
sources that are listed in the pinned file AND carry the synthetic-fixture tag.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID

from .semantic import SemanticProfileUnavailable, canonical_fingerprint

SYNTHETIC_PROFILE_KIND = "SYNTHETIC_FIXTURE"
SYNTHETIC_SOURCE_TAG = "synthetic-fixture"
SYNTHETIC_AUDIT_CODE = "SYNTHETIC_FIXTURE_PROFILE"
SYNTHETIC_WARNING = "SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE"
SYNTHETIC_FINGERPRINT_PREFIX = "synthetic-fixture:"
MACHINE_PROFILE_KIND = "VALIDATED_MACHINE_RECONCILED"
MACHINE_AUDIT_CODE = "MACHINE_RECONCILED_PROFILE"
MACHINE_WARNING = "MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT"


class SyntheticFixtureUnavailable(SemanticProfileUnavailable):
    code = "SEMANTIC_PROFILE_UNVALIDATED"


class SyntheticFixtureProfiles:
    def __init__(self, path: str | Path, expected_sha256: str, *, environment: str):
        if environment != "test":
            raise RuntimeError("SYNTHETIC_FIXTURE_PROFILES_FORBIDDEN_ENVIRONMENT")
        self.environment = environment
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise RuntimeError("SYNTHETIC_FIXTURE_PROFILES_HASH_MISMATCH")
        data = json.loads(raw)
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != 1
            or not isinstance(data.get("sources"), dict)
            or not data.get("review")
        ):
            raise RuntimeError("SYNTHETIC_FIXTURE_PROFILES_INVALID")
        self._sources: dict[str, dict[str, Any]] = data["sources"]
        self.fixture_id = str(data.get("fixture_id", ""))

    def _require_test(self) -> None:
        if self.environment != "test":
            raise SyntheticFixtureUnavailable("synthetic fixture profiles are test-only")

    def listed_sources(self) -> frozenset[str]:
        self._require_test()
        return frozenset(self._sources)

    def pinned_metadata_fingerprint(self, source_id: str) -> str:
        self._require_test()
        entry = self._sources.get(source_id)
        if not isinstance(entry, dict) or not isinstance(entry.get("metadata_fingerprint"), str):
            raise SyntheticFixtureUnavailable("source is not listed in the fixture profiles")
        return entry["metadata_fingerprint"]

    def lookup(self, source_id: str, company_id: UUID, concept: str) -> dict[str, Any]:
        self._require_test()
        entry = self._sources.get(source_id)
        if not isinstance(entry, dict):
            raise SyntheticFixtureUnavailable("source is not listed in the fixture profiles")
        mapping = (
            entry.get("companies", {}).get(str(company_id), {}).get("concepts", {}).get(concept)
        )
        if not isinstance(mapping, dict):
            raise SyntheticFixtureUnavailable("no fixture profile for this source/company/concept")
        return json.loads(json.dumps(mapping))

    def profile_fingerprint(
        self, source_id: str, company_id: UUID, concept: str, mapping: dict[str, Any]
    ) -> str:
        return SYNTHETIC_FINGERPRINT_PREFIX + canonical_fingerprint(
            {
                "fixture_id": self.fixture_id,
                "source_id": source_id,
                "company_id": str(company_id),
                "concept": concept,
                "mapping": mapping,
                "metadata_fingerprint": self.pinned_metadata_fingerprint(source_id),
            }
        )


def profile_provenance(profile: dict[str, Any], warnings: list[str] | None = None) -> dict[str, Any]:
    """Response provenance fields merged into every semantic tool result."""
    out = list(warnings or [])
    if profile.get("profile_kind") == SYNTHETIC_PROFILE_KIND:
        return {
            "profile_kind": SYNTHETIC_PROFILE_KIND,
            "evidence_level": "L1",
            "native_reconciliation": "NOT_RUN",
            "warnings": [*out, SYNTHETIC_WARNING],
        }
    if profile.get("profile_kind") == MACHINE_PROFILE_KIND:
        return {
            "profile_kind": MACHINE_PROFILE_KIND,
            "evidence_level": "PROFILE_VALIDATED_MACHINE",
            "native_reconciliation": "MACHINE_TWO_SOURCE",
            "warnings": [*out, MACHINE_WARNING],
        }
    if profile.get("profile_kind") != "VALIDATED_NATIVE":
        # Never label unknown provenance as native-validated evidence.
        raise ValueError("PROFILE_PROVENANCE_UNKNOWN")
    return {
        "profile_kind": "VALIDATED_NATIVE",
        "evidence_level": "PROFILE_VALIDATED",
        "native_reconciliation": "PROFILE_EVIDENCE_ON_FILE",
        "warnings": out,
    }
