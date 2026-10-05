from __future__ import annotations

import json

from .compatibility import OneCCapabilities
from .db import Database
from .models import Source, source_from_record
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
              AND g.revoked_at IS NULL
              AND (g.expires_at IS NULL OR g.expires_at > now())
              AND (
                    (g.principal_kind = 'subject' AND g.principal_id = $1)
                 OR (g.principal_kind = 'group' AND g.principal_id = ANY($2::text[]))
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
              AND g.revoked_at IS NULL
              AND (g.expires_at IS NULL OR g.expires_at > now())
              AND (
                    (g.principal_kind = 'subject' AND g.principal_id = $2)
                 OR (g.principal_kind = 'group' AND g.principal_id = ANY($3::text[]))
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

    async def save_capabilities(self, capabilities: OneCCapabilities):
        await self.db.require_pool().execute(
            """
            INSERT INTO bag.source_capabilities(
                source_id, discovered_at, metadata_fingerprint, platform_version,
                compatibility_status, adapter_profile, metadata_supported,
                json_supported, atom_supported, expand_supported,
                entity_set_count, evidence_json
            )
            VALUES(
                $1, now(), $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb
            )
            ON CONFLICT(source_id) DO UPDATE SET
                discovered_at=EXCLUDED.discovered_at,
                metadata_fingerprint=EXCLUDED.metadata_fingerprint,
                platform_version=EXCLUDED.platform_version,
                compatibility_status=EXCLUDED.compatibility_status,
                adapter_profile=EXCLUDED.adapter_profile,
                metadata_supported=EXCLUDED.metadata_supported,
                json_supported=EXCLUDED.json_supported,
                atom_supported=EXCLUDED.atom_supported,
                expand_supported=EXCLUDED.expand_supported,
                entity_set_count=EXCLUDED.entity_set_count,
                evidence_json=EXCLUDED.evidence_json
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
        )
