from __future__ import annotations

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
