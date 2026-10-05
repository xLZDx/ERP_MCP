from __future__ import annotations

import json
from uuid import UUID

from .compatibility import OneCCapabilities
from .db import Database
from .models import Company, Source, company_from_record, source_from_record
from .principal import Principal


class AccessDenied(PermissionError):
    pass


class Registry:
    def __init__(self, db: Database, *, production: bool):
        self.db = db
        self.production = production

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
            source.validate_runtime(production=self.production)
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
        source.validate_runtime(production=self.production)
        return source

    async def list_allowed_companies(
        self, principal: Principal, source_id: str
    ) -> list[Company]:
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
                evidence_json=EXCLUDED.evidence_json,
                register_capabilities_json=EXCLUDED.register_capabilities_json
            RETURNING drift_status, previous_metadata_fingerprint,
                      drift_detected_at, drift_acknowledged_at
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
        return {
            "drift_status": row["drift_status"],
            "previous_metadata_fingerprint": row["previous_metadata_fingerprint"],
            "drift_detected_at": (
                row["drift_detected_at"].isoformat() if row["drift_detected_at"] else None
            ),
            "drift_acknowledged_at": (
                row["drift_acknowledged_at"].isoformat()
                if row["drift_acknowledged_at"]
                else None
            ),
        }
