from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from .compatibility import OneCCapabilities
from .db import Database
from .models import Company, Source, company_from_record, source_from_record
from .principal import Principal
from .semantic import (
    ACCOUNT_TURNOVERS_CONCEPT,
    ACCOUNTING_POSTING_ROWS_CONCEPT,
    BANK_BALANCE_CONCEPT,
    CASH_MOVEMENTS_CONCEPT,
    INVENTORY_BALANCE_CONCEPT,
    INVENTORY_MOVEMENTS_CONCEPT,
    PAYABLE_BALANCE_CONCEPT,
    RECEIVABLE_BALANCE_CONCEPT,
    SemanticMappingUnconfirmed,
    SemanticProfileStale,
    SemanticProfileUnavailable,
    canonical_fingerprint,
    require_profile_capabilities,
    require_usable_semantic_profile,
    validate_account_turnovers_mapping,
    validate_accounting_posting_rows_mapping,
    validate_bank_balance_mapping,
    validate_cash_movements_mapping,
    validate_document_mapping,
    validate_inventory_balance_mapping,
    validate_inventory_movements_mapping,
    validate_settlement_balance_mapping,
)


class AccessDenied(PermissionError):
    pass


class Registry:
    def __init__(
        self,
        db: Database,
        *,
        production: bool,
        allowed_source_hosts: tuple[str, ...] = (),
    ):
        self.db = db
        self.production = production
        self.allowed_source_hosts = allowed_source_hosts

    async def list_allowed(self, principal: Principal) -> list[Source]:
        rows = await self.db.require_pool().fetch(
            """
            SELECT DISTINCT s.*
            FROM bag.sources s
            JOIN bag.access_grants g
              ON (g.source_id = s.source_id OR g.all_sources = TRUE)
            WHERE s.enabled = TRUE
              AND g.effect = 'allow'
              AND g.revoked_at IS NULL
              AND (g.expires_at IS NULL OR g.expires_at > now())
              AND (
                    (g.principal_kind = 'subject' AND g.principal_id = $1)
                 OR (g.principal_kind = 'group' AND g.principal_id = ANY($2::text[]))
              )
              AND NOT EXISTS (
                  SELECT 1 FROM bag.access_grants denied
                  WHERE denied.effect = 'deny'
                    AND denied.revoked_at IS NULL
                    AND (denied.expires_at IS NULL OR denied.expires_at > now())
                    AND (denied.source_id = s.source_id OR denied.all_sources = TRUE)
                    AND (
                          (denied.principal_kind = 'subject' AND denied.principal_id = $1)
                       OR (denied.principal_kind = 'group' AND denied.principal_id = ANY($2::text[]))
                    )
              )
            ORDER BY s.source_id
            """,
            principal.subject,
            list(principal.groups),
        )
        result = [source_from_record(row) for row in rows]
        for source in result:
            source.validate_runtime(
                production=self.production, allowed_source_hosts=self.allowed_source_hosts
            )
        return result

    async def require_source(self, principal: Principal, source_id: str) -> Source:
        row = await self.db.require_pool().fetchrow(
            """
            SELECT DISTINCT s.*
            FROM bag.sources s
            JOIN bag.access_grants g
              ON (g.source_id = s.source_id OR g.all_sources = TRUE)
            WHERE s.source_id = $1
              AND s.enabled = TRUE
              AND g.effect = 'allow'
              AND g.company_id IS NULL
              AND g.revoked_at IS NULL
              AND (g.expires_at IS NULL OR g.expires_at > now())
              AND (
                    (g.principal_kind = 'subject' AND g.principal_id = $2)
                 OR (g.principal_kind = 'group' AND g.principal_id = ANY($3::text[]))
              )
              AND NOT EXISTS (
                  SELECT 1 FROM bag.access_grants denied
                  WHERE denied.effect = 'deny'
                    AND denied.revoked_at IS NULL
                    AND (denied.expires_at IS NULL OR denied.expires_at > now())
                    AND (denied.source_id = s.source_id OR denied.all_sources = TRUE)
                    AND (
                          (denied.principal_kind = 'subject' AND denied.principal_id = $2)
                       OR (denied.principal_kind = 'group' AND denied.principal_id = ANY($3::text[]))
                    )
              )
            """,
            source_id,
            principal.subject,
            list(principal.groups),
        )
        if row is None:
            raise AccessDenied(f"no access to source {source_id!r}")
        source = source_from_record(row)
        source.validate_runtime(
            production=self.production, allowed_source_hosts=self.allowed_source_hosts
        )
        return source

    async def list_allowed_companies(self, principal: Principal, source_id: str) -> list[Company]:
        """List only enabled companies covered by an active source/company grant."""
        rows = await self.db.require_pool().fetch(
            """
            SELECT DISTINCT c.*
            FROM bag.companies c
            JOIN bag.sources s ON s.source_id = c.source_id
            JOIN bag.access_grants g
              ON (g.source_id = c.source_id OR g.all_sources = TRUE)
             AND (g.company_id IS NULL OR g.company_id = c.company_id)
            WHERE c.source_id = $1
              AND c.enabled = TRUE
              AND s.enabled = TRUE
              -- Source-wide grants and global grants both include all companies.
              AND g.effect = 'allow'
              AND g.revoked_at IS NULL
              AND (g.expires_at IS NULL OR g.expires_at > now())
              AND (
                    (g.principal_kind = 'subject' AND g.principal_id = $2)
                 OR (g.principal_kind = 'group' AND g.principal_id = ANY($3::text[]))
              )
              AND NOT EXISTS (
                  SELECT 1 FROM bag.access_grants denied
                  WHERE denied.effect = 'deny'
                    AND denied.revoked_at IS NULL
                    AND (denied.expires_at IS NULL OR denied.expires_at > now())
                    AND (denied.source_id = c.source_id OR denied.all_sources = TRUE)
                    AND (denied.company_id IS NULL OR denied.company_id = c.company_id)
                    AND (
                          (denied.principal_kind = 'subject' AND denied.principal_id = $2)
                       OR (denied.principal_kind = 'group' AND denied.principal_id = ANY($3::text[]))
                    )
              )
            ORDER BY c.display_name, c.company_id
            """,
            source_id,
            principal.subject,
            list(principal.groups),
        )
        return [company_from_record(row) for row in rows]

    async def require_company(
        self, principal: Principal, source_id: str, company_id: UUID
    ) -> Company:
        """Resolve an enabled company only when a source-wide or matching company grant exists."""
        row = await self.db.require_pool().fetchrow(
            """
            SELECT DISTINCT c.*
            FROM bag.companies c
            JOIN bag.sources s ON s.source_id = c.source_id
            JOIN bag.access_grants g
              ON (g.source_id = c.source_id OR g.all_sources = TRUE)
             AND (g.company_id IS NULL OR g.company_id = c.company_id)
            WHERE c.source_id = $1
              AND c.company_id = $2
              AND c.enabled = TRUE
              AND s.enabled = TRUE
              -- Source-wide grants and global grants both include all companies.
              AND g.effect = 'allow'
              AND g.revoked_at IS NULL
              AND (g.expires_at IS NULL OR g.expires_at > now())
              AND (
                    (g.principal_kind = 'subject' AND g.principal_id = $3)
                 OR (g.principal_kind = 'group' AND g.principal_id = ANY($4::text[]))
              )
              AND NOT EXISTS (
                  SELECT 1 FROM bag.access_grants denied
                  WHERE denied.effect = 'deny'
                    AND denied.revoked_at IS NULL
                    AND (denied.expires_at IS NULL OR denied.expires_at > now())
                    AND (denied.source_id = c.source_id OR denied.all_sources = TRUE)
                    AND (denied.company_id IS NULL OR denied.company_id = c.company_id)
                    AND (
                          (denied.principal_kind = 'subject' AND denied.principal_id = $3)
                       OR (denied.principal_kind = 'group' AND denied.principal_id = ANY($4::text[]))
                    )
              )
            """,
            source_id,
            company_id,
            principal.subject,
            list(principal.groups),
        )
        if row is None:
            raise AccessDenied("no access to company")
        return company_from_record(row)

    async def require_source_for_company(
        self, principal: Principal, source_id: str, company_id: UUID
    ) -> Source:
        """Resolve a source using only a source-wide or exact-company grant."""
        row = await self.db.require_pool().fetchrow(
            """
            SELECT DISTINCT s.*
            FROM bag.sources s
            JOIN bag.companies c ON c.source_id=s.source_id
            JOIN bag.access_grants g
              ON (g.source_id=s.source_id OR g.all_sources=TRUE)
             AND (g.company_id IS NULL OR g.company_id=c.company_id)
            WHERE s.source_id=$1 AND c.company_id=$2
              AND s.enabled=TRUE AND c.enabled=TRUE
              AND g.effect='allow' AND g.revoked_at IS NULL
              AND (g.expires_at IS NULL OR g.expires_at>now())
              AND (
                    (g.principal_kind='subject' AND g.principal_id=$3)
                 OR (g.principal_kind='group' AND g.principal_id=ANY($4::text[]))
              )
              AND NOT EXISTS (
                SELECT 1 FROM bag.access_grants denied
                WHERE denied.effect='deny' AND denied.revoked_at IS NULL
                  AND (denied.expires_at IS NULL OR denied.expires_at>now())
                  AND (denied.source_id=s.source_id OR denied.all_sources=TRUE)
                  AND (denied.company_id IS NULL OR denied.company_id=c.company_id)
                  AND (
                        (denied.principal_kind='subject' AND denied.principal_id=$3)
                     OR (denied.principal_kind='group' AND denied.principal_id=ANY($4::text[]))
                  )
              )
            """,
            source_id,
            company_id,
            principal.subject,
            list(principal.groups),
        )
        if row is None:
            raise AccessDenied("no access to source/company scope")
        source = source_from_record(row)
        source.validate_runtime(
            production=self.production, allowed_source_hosts=self.allowed_source_hosts
        )
        return source

    async def require_semantic_mapping(
        self, source_id: str, company_id: UUID, concept: str
    ) -> dict:
        """Load only an exact-company validated and explicitly confirmed mapping."""
        row = await self.db.require_pool().fetchrow(
            """
            SELECT p.source_id, p.company_id, p.status AS profile_status,
                   p.metadata_fingerprint, p.capability_fingerprint,
                   p.profile_fingerprint,
                   p.validation_evidence_json, m.mapping_json, m.mapping_status,
                   m.confidence, c.metadata_fingerprint AS current_metadata_fingerprint,
                   c.register_capabilities_json, c.drift_status
            FROM bag.semantic_profiles p
            JOIN bag.semantic_mappings m ON m.profile_id=p.profile_id
            JOIN bag.source_capabilities c ON c.source_id=p.source_id
            WHERE p.source_id=$1 AND p.company_id=$2
              AND p.status='VALIDATED'
              AND m.canonical_concept=$3
            ORDER BY p.profile_version DESC
            LIMIT 1
            """,
            source_id,
            company_id,
            concept,
        )
        if row is None:
            raise SemanticProfileUnavailable(
                f"no validated {concept} profile exists for this exact source/company"
            )
        if (
            row["drift_status"] != "STABLE"
            or row["metadata_fingerprint"] != row["current_metadata_fingerprint"]
        ):
            raise SemanticProfileStale(
                "account-turnover profile is stale or source drift is unacknowledged"
            )
        capability_profile = row["register_capabilities_json"]
        if isinstance(capability_profile, str):
            capability_profile = json.loads(capability_profile)
        if canonical_fingerprint(capability_profile) != row["capability_fingerprint"]:
            raise SemanticProfileStale("account-turnover capability evidence changed")
        if row["mapping_status"] != "CONFIRMED" or row["confidence"] != "HIGH":
            raise SemanticMappingUnconfirmed(
                "account-turnover mapping has not been operator-confirmed"
            )
        mapping = row["mapping_json"]
        if isinstance(mapping, str):
            mapping = json.loads(mapping)
        required = mapping.get("required_register_capabilities", [])
        if concept == ACCOUNT_TURNOVERS_CONCEPT:
            entity_set, method = validate_account_turnovers_mapping(mapping)
            if required != [{"entity_set": entity_set, "method": method}]:
                raise SemanticMappingUnconfirmed(
                    "mapping capability dependency is missing or mismatched"
                )
        elif concept in {"sales", "purchases"}:
            validate_document_mapping(concept, mapping)
            if required:
                raise SemanticMappingUnconfirmed(
                    "document-list mapping must not declare register capabilities"
                )
        elif concept == INVENTORY_BALANCE_CONCEPT:
            entity_set, method = validate_inventory_balance_mapping(mapping)
            if required != [{"entity_set": entity_set, "method": method}]:
                raise SemanticMappingUnconfirmed(
                    "inventory mapping capability dependency is missing or mismatched"
                )
        elif concept == INVENTORY_MOVEMENTS_CONCEPT:
            validate_inventory_movements_mapping(mapping)
            if required:
                raise SemanticMappingUnconfirmed(
                    "inventory movement record-set mapping cannot claim virtual-table methods"
                )
        elif concept == ACCOUNTING_POSTING_ROWS_CONCEPT:
            validate_accounting_posting_rows_mapping(mapping)
            if required:
                raise SemanticMappingUnconfirmed(
                    "accounting posting record-set mapping cannot claim virtual-table methods"
                )
        elif concept == CASH_MOVEMENTS_CONCEPT:
            validate_cash_movements_mapping(mapping)
            if required:
                raise SemanticMappingUnconfirmed(
                    "cash movement record-set mapping cannot claim virtual-table methods"
                )
        elif concept == BANK_BALANCE_CONCEPT:
            entity_set, method = validate_bank_balance_mapping(mapping)
            if required != [{"entity_set": entity_set, "method": method}]:
                raise SemanticMappingUnconfirmed(
                    "bank mapping capability dependency is missing or mismatched"
                )
        elif concept in {RECEIVABLE_BALANCE_CONCEPT, PAYABLE_BALANCE_CONCEPT}:
            entity_set, method = validate_settlement_balance_mapping(concept, mapping)
            if required != [{"entity_set": entity_set, "method": method}]:
                raise SemanticMappingUnconfirmed(
                    "settlement mapping capability dependency is missing or mismatched"
                )
        else:
            raise SemanticMappingUnconfirmed(f"semantic concept is not runtime-enabled: {concept}")
        validation_evidence = row["validation_evidence_json"]
        if isinstance(validation_evidence, str):
            validation_evidence = json.loads(validation_evidence)
        require_usable_semantic_profile(
            {
                "source_id": row["source_id"],
                "company_id": row["company_id"],
                "status": row["profile_status"],
                "metadata_fingerprint": row["metadata_fingerprint"],
                "validation_evidence": validation_evidence,
            },
            source_id=source_id,
            company_id=company_id,
            metadata_fingerprint=row["current_metadata_fingerprint"],
            drift_status=row["drift_status"],
        )
        require_profile_capabilities(
            required,
            capability_profile,
            source_id=source_id,
            metadata_fingerprint=row["current_metadata_fingerprint"],
        )
        return {
            "source_id": row["source_id"],
            "company_id": row["company_id"],
            "metadata_fingerprint": row["metadata_fingerprint"],
            "profile_fingerprint": row["profile_fingerprint"],
            "mapping": mapping,
            "register_capabilities": capability_profile,
        }

    async def require_account_turnovers_mapping(self, source_id: str, company_id: UUID) -> dict:
        return await self.require_semantic_mapping(source_id, company_id, ACCOUNT_TURNOVERS_CONCEPT)

    async def save_capabilities(self, capabilities: OneCCapabilities):
        row = await self.db.require_pool().fetchrow(
            """
            INSERT INTO bag.source_capabilities(
                source_id, discovered_at, metadata_fingerprint, platform_version,
                compatibility_status, adapter_profile, metadata_supported,
                json_supported, atom_supported, expand_supported,
                entity_set_count, evidence_json, register_capabilities_json, drift_status
            )
            VALUES(
                $1, now(), $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12::jsonb, 'STABLE'
            )
            ON CONFLICT(source_id) DO UPDATE SET
                discovered_at=EXCLUDED.discovered_at,
                previous_metadata_fingerprint=CASE
                    WHEN bag.source_capabilities.metadata_fingerprint
                         IS DISTINCT FROM EXCLUDED.metadata_fingerprint
                    THEN bag.source_capabilities.metadata_fingerprint
                    ELSE bag.source_capabilities.previous_metadata_fingerprint
                END,
                drift_status=CASE
                    WHEN bag.source_capabilities.metadata_fingerprint
                         IS DISTINCT FROM EXCLUDED.metadata_fingerprint THEN 'DRIFTED'
                    WHEN bag.source_capabilities.drift_status = 'DRIFTED' THEN 'DRIFTED'
                    ELSE 'STABLE'
                END,
                drift_detected_at=CASE
                    WHEN bag.source_capabilities.metadata_fingerprint
                         IS DISTINCT FROM EXCLUDED.metadata_fingerprint THEN now()
                    ELSE bag.source_capabilities.drift_detected_at
                END,
                drift_acknowledged_at=CASE
                    WHEN bag.source_capabilities.metadata_fingerprint
                         IS DISTINCT FROM EXCLUDED.metadata_fingerprint THEN NULL
                    ELSE bag.source_capabilities.drift_acknowledged_at
                END,
                metadata_fingerprint=EXCLUDED.metadata_fingerprint,
                platform_version=EXCLUDED.platform_version,
                compatibility_status=EXCLUDED.compatibility_status,
                adapter_profile=EXCLUDED.adapter_profile,
                metadata_supported=EXCLUDED.metadata_supported,
                json_supported=EXCLUDED.json_supported,
                atom_supported=EXCLUDED.atom_supported,
                expand_supported=EXCLUDED.expand_supported,
                entity_set_count=EXCLUDED.entity_set_count,
                evidence_json=EXCLUDED.evidence_json || jsonb_build_object(
                    'semantic_capabilities',
                    COALESCE(
                        bag.source_capabilities.evidence_json->'semantic_capabilities',
                        '{}'::jsonb
                    )
                ),
                register_capabilities_json=EXCLUDED.register_capabilities_json
            RETURNING drift_status, previous_metadata_fingerprint,
                      drift_detected_at, drift_acknowledged_at, evidence_json
            """,
            capabilities.source_id,
            capabilities.metadata_fingerprint,
            capabilities.platform_version,
            capabilities.compatibility_status.value,
            capabilities.adapter_profile.value,
            capabilities.metadata_supported,
            capabilities.json_supported,
            capabilities.atom_supported,
            capabilities.expand_supported,
            capabilities.entity_set_count,
            json.dumps(capabilities.evidence, ensure_ascii=False),
            json.dumps(capabilities.register_capabilities, ensure_ascii=False),
        )
        evidence = row["evidence_json"]
        if isinstance(evidence, str):
            evidence = json.loads(evidence)
        return {
            "drift_status": row["drift_status"],
            "previous_metadata_fingerprint": row["previous_metadata_fingerprint"],
            "drift_detected_at": (
                row["drift_detected_at"].isoformat() if row["drift_detected_at"] else None
            ),
            "drift_acknowledged_at": (
                row["drift_acknowledged_at"].isoformat() if row["drift_acknowledged_at"] else None
            ),
            "source_capability_evidence": evidence.get("semantic_capabilities", {}),
        }

    async def record_semantic_capability_evidence(
        self,
        *,
        source_id: str,
        concept: str,
        entity_set: str,
        metadata_fingerprint: str,
        reason: str,
        expected_properties: list[str] | None = None,
        missing_properties: list[str] | None = None,
    ) -> dict:
        """Persist source-specific negative evidence without mutating sidecar register evidence."""
        if reason not in {"ENTITY_SET_ABSENT", "PROPERTY_ABSENT", "PROPERTIES_UNCONFIRMED"}:
            raise ValueError("unsupported capability evidence reason")
        evidence_key = canonical_fingerprint(
            {
                "source_id": source_id,
                "concept": concept,
                "entity_set": entity_set,
                "expected_properties": sorted(set(expected_properties or [])),
            }
        )
        item = {
            "source_id": source_id,
            "concept": concept,
            "entity_set": entity_set,
            "metadata_fingerprint": metadata_fingerprint,
            "checked_at": datetime.now(UTC).isoformat(),
            "status": "UNSUPPORTED",
            "reason": reason,
            "expected_properties": sorted(set(expected_properties or [])),
            "missing_properties": sorted(set(missing_properties or [])),
        }
        row = await self.db.require_pool().fetchrow(
            """
            UPDATE bag.source_capabilities
            SET evidence_json=jsonb_set(
                COALESCE(evidence_json, '{}'::jsonb),
                '{semantic_capabilities}',
                COALESCE(evidence_json->'semantic_capabilities', '{}'::jsonb)
                  || jsonb_build_object($2::text, $3::jsonb),
                true
            )
            WHERE source_id=$1 AND metadata_fingerprint=$4 AND drift_status='STABLE'
            RETURNING evidence_json
            """,
            source_id,
            evidence_key,
            json.dumps(item, ensure_ascii=False),
            metadata_fingerprint,
        )
        if row is None:
            raise SemanticProfileStale(
                "cannot persist capability evidence for stale/unacknowledged source metadata"
            )
        evidence = row["evidence_json"]
        if isinstance(evidence, str):
            evidence = json.loads(evidence)
        return evidence.get("semantic_capabilities", {})
