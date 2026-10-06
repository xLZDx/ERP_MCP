from __future__ import annotations

import hashlib
import json
import time
import uuid
from contextvars import ContextVar
from typing import Any

from .db import Database
from .principal import Principal

_request_correlation_id: ContextVar[uuid.UUID | None] = ContextVar(
    "audit_request_correlation_id", default=None
)


def begin_request_correlation_id():
    value = _request_correlation_id.get() or uuid.uuid4()
    return _request_correlation_id.set(value), value


def end_request_correlation_id(token) -> None:
    _request_correlation_id.reset(token)


def current_request_correlation_id() -> uuid.UUID | None:
    return _request_correlation_id.get()


class AuditCorrelationMiddleware:
    """Give every inbound MCP message one isolated audit correlation ID."""

    async def __call__(self, ctx, call_next):
        token, _ = begin_request_correlation_id()
        try:
            return await call_next(ctx)
        finally:
            end_request_correlation_id(token)


def query_fingerprint(query: dict[str, Any] | None) -> str | None:
    if not query:
        return None
    payload = json.dumps(query, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class Audit:
    def __init__(self, db: Database, *, include_query: bool, metrics: Any | None = None):
        self.db = db
        self.include_query = include_query
        self.metrics = metrics

    async def write(
        self,
        *,
        principal: Principal,
        tool: str,
        source_id: str | None,
        outcome: str,
        started_at: float,
        query: dict[str, Any] | None = None,
        request_id: uuid.UUID | None = None,
        company_id: uuid.UUID | None = None,
        adapter_kind: str | None = None,
        adapter_version: str | None = None,
        upstream_sha: str | None = None,
        policy_version: str | None = None,
        metadata_fingerprint: str | None = None,
        profile_fingerprint: str | None = None,
        returned_items: int | None = None,
        response_bytes: int | None = None,
        truncated: bool = False,
        detail_code: str | None = None,
    ):
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        if self.metrics is not None:
            self.metrics.record_operation(tool, outcome)
        from .observability import trace_span

        async with trace_span("audit.append", tool=tool, outcome=outcome):
            await self.db.require_pool().execute(
            """
            INSERT INTO bag.audit_events(
                event_id, principal_subject, client_id, tool_name, source_id,
                outcome, query_fingerprint, query_json, returned_items,
                duration_ms, detail_code, request_id, company_id, adapter_kind,
                adapter_version, upstream_sha, policy_version, metadata_fingerprint,
                profile_fingerprint, response_bytes, truncated
            )
            VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12,$13,$14,$15,
                   $16,$17,$18,$19,$20,$21)
            """,
            uuid.uuid4(),
            principal.subject,
            principal.client_id,
            tool,
            source_id,
            outcome,
            query_fingerprint(query),
            # Never persist raw filters: accounting queries may contain sensitive data.
            None,
            returned_items,
            elapsed_ms,
            detail_code,
            request_id or _request_correlation_id.get() or uuid.uuid4(),
            company_id,
            adapter_kind,
            adapter_version,
            upstream_sha,
            policy_version,
            metadata_fingerprint,
            profile_fingerprint,
            response_bytes,
            truncated,
            )
