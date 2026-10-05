from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from .db import Database
from .principal import Principal


def query_fingerprint(query: dict[str, Any] | None) -> str | None:
    if not query:
        return None
    payload = json.dumps(query, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class Audit:
    def __init__(self, db: Database, *, include_query: bool):
        self.db = db
        self.include_query = include_query

    async def write(
        self,
        *,
        principal: Principal,
        tool: str,
        source_id: str | None,
        outcome: str,
        started_at: float,
        query: dict[str, Any] | None = None,
        returned_items: int | None = None,
        detail_code: str | None = None,
    ):
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        await self.db.require_pool().execute(
            """
            INSERT INTO bag.audit_events(
                event_id, principal_subject, client_id, tool_name, source_id,
                outcome, query_fingerprint, query_json, returned_items,
                duration_ms, detail_code
            )
            VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11)
            """,
            uuid.uuid4(),
            principal.subject,
            principal.client_id,
            tool,
            source_id,
            outcome,
            query_fingerprint(query),
            json.dumps(query, ensure_ascii=False, default=str)
            if self.include_query and query
            else None,
            returned_items,
            elapsed_ms,
            detail_code,
        )
