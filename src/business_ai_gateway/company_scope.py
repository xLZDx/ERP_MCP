from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

from .models import Company, Source

_PROPERTY_RE = re.compile(r"^[^\W\d]\w*$", re.UNICODE)


class CompanyScopeUnavailable(PermissionError):
    code = "COMPANY_SCOPE_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CompanyScopeMapping:
    profile_id: UUID
    entity_set: str
    company_property: str
    literal_kind: str
    profile_fingerprint: str


class CompanyScopeResolver:
    def __init__(self, db):
        self.db = db

    async def mapping(
        self,
        *,
        source: Source,
        company: Company,
        entity_set: str,
        metadata_fingerprint: str,
        drift_status: str,
    ) -> CompanyScopeMapping:
        if drift_status != "STABLE":
            raise CompanyScopeUnavailable("metadata drift must be acknowledged")
        row = await self.db.require_pool().fetchrow(
            """
            SELECT m.profile_id, m.entity_set, m.company_property, m.literal_kind,
                   p.profile_fingerprint
            FROM bag.company_scope_mappings m
            JOIN bag.semantic_profiles p ON p.profile_id=m.profile_id
            WHERE p.source_id=$1
              AND (p.company_id=$2 OR p.company_id IS NULL)
              AND p.status='VALIDATED'
              AND p.metadata_fingerprint=$3
              AND m.entity_set=$4
            ORDER BY (p.company_id=$2) DESC, p.profile_version DESC
            LIMIT 1
            """,
            source.id,
            company.id,
            metadata_fingerprint,
            entity_set,
        )
        if row is None:
            raise CompanyScopeUnavailable(
                "no validated company-scope mapping for entity set"
            )
        prop = row["company_property"]
        if not isinstance(prop, str) or not _PROPERTY_RE.fullmatch(prop):
            raise CompanyScopeUnavailable("invalid company property mapping")
        return CompanyScopeMapping(
            profile_id=row["profile_id"],
            entity_set=row["entity_set"],
            company_property=prop,
            literal_kind=row["literal_kind"],
            profile_fingerprint=row["profile_fingerprint"],
        )

    @staticmethod
    def filter_for(mapping: CompanyScopeMapping, company: Company) -> str:
        if mapping.literal_kind == "guid":
            try:
                value = UUID(company.external_ref)
            except ValueError as exc:
                raise CompanyScopeUnavailable(
                    "company external_ref is not a GUID required by mapping"
                ) from exc
            literal = f"guid'{value}'"
        elif mapping.literal_kind == "string":
            escaped = company.external_ref.replace("'", "''")
            literal = f"'{escaped}'"
        else:
            raise CompanyScopeUnavailable("unsupported company literal kind")
        return f"{mapping.company_property} eq {literal}"

    @staticmethod
    def combine(company_filter: str, caller_filter: str | None) -> str:
        return (
            f"({company_filter}) and ({caller_filter})"
            if caller_filter
            else company_filter
        )

    @staticmethod
    def verify_metadata_property(index, *, entity_set: str, property_name: str) -> None:
        entity = next((item for item in index.entities if item.name == entity_set), None)
        if entity is None or property_name not in entity.properties:
            raise CompanyScopeUnavailable(
                "company property is not present in current live metadata"
            )
