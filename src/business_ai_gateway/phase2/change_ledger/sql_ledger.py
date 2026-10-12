"""Thin asyncpg port over the ``change_ledger.*`` SQL functions (db/phase2/004_change_ledger.sql).

No ledger logic lives here: each method opens one transaction, optionally ``SET LOCAL ROLE`` for the
caller class, calls ``change_ledger.set_scope`` and then exactly one SQL function (the
``tests/phase2/_sql_ports.py`` convention). A rejected call becomes ``LedgerError(code)``.
``actors`` maps a caller class (requester/approver/operator/writer/worker/auditor) to the database
role to assume; a missing/None entry means the connection already is the authenticated principal
(matches ``tests/phase2/_sql_ports.py`` and ``ports.py``'s actor convention).

``ledger_head`` / ``record_checkpoint`` / ``issue_permit`` / ``attach_permit_signature`` together
satisfy ``checkpoint.LedgerPort`` so ``checkpoint.DispatchGate`` can run against a real database
without any change to ``checkpoint.py``.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from ._common import LedgerError, Scope, code_from_message

_IDENT = re.compile(r"[a-z][a-z0-9_]*")
_CLASSES = ("requester", "approver", "operator", "writer", "worker", "auditor")


def _j(value: Any) -> str | None:
    return None if value is None else json.dumps(value)


class SqlChangeLedger:
    """Implements ``checkpoint.LedgerPort``; a superset covers the rest of section 6."""

    def __init__(self, conn: asyncpg.Connection, actors: Mapping[str, str | None] | None = None):
        self.conn = conn
        self._actors = dict(actors or {})
        for cls, role in self._actors.items():
            if cls not in _CLASSES or (role is not None and not _IDENT.fullmatch(role)):
                raise ValueError("ACTOR_INVALID")

    async def _call(self, cls: str, scope: Scope, sql: str, *args: Any) -> Any:
        """Scalar/jsonb result path: used for every function whose SQL return type is a plain
        scalar (text/uuid/bigint/boolean/void) or ``jsonb`` (auto-decoded here, never by the caller)."""
        role = self._actors.get(cls)
        try:
            async with self.conn.transaction():
                if role:
                    await self.conn.execute(f'SET LOCAL ROLE "{role}"')
                await self.conn.execute("SELECT change_ledger.set_scope($1,$2)", scope.tenant_id,
                                        scope.company_id)
                value = await self.conn.fetchval(sql, scope.tenant_id, scope.company_id, *args)
        except asyncpg.PostgresError as e:
            raise LedgerError(code_from_message(str(e), e.sqlstate)) from None
        if isinstance(value, str) and value[:1] in "{[":
            return json.loads(value)
        return value

    async def _row(self, cls: str, scope: Scope, sql: str, *args: Any) -> dict | None:
        """Row result path: used for the two functions that return a ``change_ledger.claim_tokens``
        composite row (``claim``, ``begin_apply``) rather than a scalar/jsonb value."""
        role = self._actors.get(cls)
        try:
            async with self.conn.transaction():
                if role:
                    await self.conn.execute(f'SET LOCAL ROLE "{role}"')
                await self.conn.execute("SELECT change_ledger.set_scope($1,$2)", scope.tenant_id,
                                        scope.company_id)
                record = await self.conn.fetchrow(sql, scope.tenant_id, scope.company_id, *args)
        except asyncpg.PostgresError as e:
            raise LedgerError(code_from_message(str(e), e.sqlstate)) from None
        return None if record is None else dict(record)

    # ---- requester (T1/T2/T5/T5x/T6)
    async def propose(self, scope: Scope, change_id: UUID, kind: str, base_fingerprint: str,
                      organization_ref: str, requester: str, request_id: str,
                      payload_digest: str, target_ref: str | None, target_version: str | None,
                      parent_change_id: UUID | None, expires_at: datetime) -> UUID:
        return await self._call(
            "requester", scope,
            "SELECT change_ledger.propose($1,$2,$3::uuid,$4,$5,$6,$7,$8,$9,$10,$11,$12::uuid,"
            "$13::timestamptz)",
            change_id, kind, base_fingerprint, organization_ref, requester, request_id,
            payload_digest, target_ref, target_version, parent_change_id, expires_at)

    async def validate(self, scope: Scope, change_id: UUID, duplicate: bool,
                       budget_ok: bool) -> str:
        return await self._call("requester", scope,
                                "SELECT change_ledger.validate($1,$2,$3::uuid,$4,$5)",
                                change_id, duplicate, budget_ok)

    async def claim(self, scope: Scope, change_id: UUID, key_hash: str | None = None,
                    grant_id: UUID | None = None, amount: Any = None,
                    counts_create_update: bool = False, counts_post: bool = False) -> dict | None:
        return await self._row(
            "requester", scope,
            "SELECT * FROM change_ledger.claim($1,$2,$3::uuid,$4,$5::uuid,$6::numeric,$7,$8)",
            change_id, key_hash, grant_id, amount, counts_create_update, counts_post)

    async def release_claim(self, scope: Scope, token_id: UUID, cls: str = "requester") -> str:
        return await self._call(cls, scope, "SELECT change_ledger.release_claim($1,$2,$3::uuid)",
                                token_id)

    async def begin_apply(self, scope: Scope, token_id: UUID, call_id: UUID,
                          writer_host: str, onec_session: str,
                          cls: str = "requester") -> dict | None:
        return await self._row(
            cls, scope,
            "SELECT * FROM change_ledger.begin_apply($1,$2,$3::uuid,$4::uuid,$5,$6)",
            token_id, call_id, writer_host, onec_session)

    # ---- approver (T3/T4)
    async def approve(self, scope: Scope, change_id: UUID, nonce: str, digest: str) -> UUID:
        return await self._call("approver", scope,
                                "SELECT change_ledger.approve($1,$2,$3::uuid,$4,$5)",
                                change_id, nonce, digest)

    async def reject(self, scope: Scope, change_id: UUID, nonce: str) -> str:
        return await self._call("approver", scope,
                                "SELECT change_ledger.reject($1,$2,$3::uuid,$4)", change_id, nonce)

    # ---- writer (T6p/T7/T8/T9)
    async def issue_permit(self, scope: Scope, change_id: UUID, generation: int) -> dict:
        """Satisfies ``checkpoint.LedgerPort.issue_permit``."""
        return await self._call("writer", scope,
                                "SELECT change_ledger.issue_permit($1,$2,$3::uuid,$4::bigint)",
                                change_id, generation)

    async def complete(self, scope: Scope, change_id: UUID, generation: int, outcome: str,
                       evidence: dict, no_effect_proof: dict | None = None) -> str:
        return await self._call(
            "writer", scope,
            "SELECT change_ledger.complete($1,$2,$3::uuid,$4::bigint,$5,$6::jsonb,$7::jsonb)",
            change_id, generation, outcome, _j(evidence), _j(no_effect_proof))

    # ---- worker (recovery/verification)
    async def recover_sweep(self, scope: Scope) -> int:
        return await self._call("worker", scope, "SELECT change_ledger.recover_sweep($1,$2)")

    async def resolve_unknown(self, scope: Scope, change_id: UUID, observation: dict,
                              found: bool | None, attributed: bool = False) -> str:
        return await self._call(
            "worker", scope,
            "SELECT change_ledger.resolve_unknown($1,$2,$3::uuid,$4::jsonb,$5,$6)",
            change_id, _j(observation), found, attributed)

    async def verify(self, scope: Scope, change_id: UUID, evidence: dict, passed: bool) -> str:
        return await self._call("worker", scope,
                                "SELECT change_ledger.verify($1,$2,$3::uuid,$4::jsonb,$5)",
                                change_id, _j(evidence), passed)

    async def witness_cosign(self, scope: Scope, change_id: UUID, completion_proof: dict,
                             cls: str = "operator") -> UUID:
        return await self._call(cls, scope,
                                "SELECT change_ledger.witness_cosign($1,$2,$3::uuid,$4::jsonb)",
                                change_id, _j(completion_proof))

    async def record_checkpoint(self, scope: Scope, seq: int, head_hash: str, sink_kind: str,
                                sink_id: str, key_id: str, signature: str, signed_at: datetime,
                                read_back: bool, cls: str = "writer") -> int:
        """Satisfies ``checkpoint.LedgerPort.record_checkpoint``."""
        return await self._call(
            cls, scope,
            "SELECT change_ledger.record_checkpoint($1,$2,$3::bigint,$4,$5,$6,$7,$8,"
            "$9::timestamptz,$10)",
            seq, head_hash, sink_kind, sink_id, key_id, signature, signed_at, read_back)

    async def attach_permit_signature(self, scope: Scope, change_id: UUID, generation: int,
                                      key_id: str, signature: str, cls: str = "writer") -> None:
        """Satisfies ``checkpoint.LedgerPort.attach_permit_signature``."""
        await self._call(
            cls, scope,
            "SELECT change_ledger.attach_permit_signature($1,$2,$3::uuid,$4::bigint,$5,$6)",
            change_id, generation, key_id, signature)

    async def ledger_head(self, scope: Scope, cls: str = "worker") -> dict:
        """Satisfies ``checkpoint.LedgerPort.ledger_head``."""
        return await self._call(cls, scope, "SELECT change_ledger.ledger_head($1,$2)")

    # ---- operator (T16/release_hold/kill_switch/budget_admin)
    async def operator_resolve(self, scope: Scope, change_id: UUID, cosign_id: UUID,
                               present: bool, attributed: bool) -> str:
        return await self._call(
            "operator", scope,
            "SELECT change_ledger.operator_resolve($1,$2,$3::uuid,$4::uuid,$5,$6)",
            change_id, cosign_id, present, attributed)

    async def release_hold(self, scope: Scope, hold_id: UUID, release_evidence: dict) -> datetime:
        return await self._call("operator", scope,
                                "SELECT change_ledger.release_hold($1,$2,$3::uuid,$4::jsonb)",
                                hold_id, _j(release_evidence))

    async def kill_switch(self, scope: Scope, mode: str) -> str:
        return await self._call("operator", scope, "SELECT change_ledger.kill_switch($1,$2,$3)",
                                mode)

    async def budget_admin(self, scope: Scope, grant_id: UUID | None, currency: str,
                           amount_limit: Any, count_limit: int, post_count_limit: int,
                           window_start: datetime, window_end: datetime) -> UUID:
        return await self._call(
            "operator", scope,
            "SELECT change_ledger.budget_admin($1,$2,$3::uuid,$4,$5::numeric,$6::integer,"
            "$7::integer,$8::timestamptz,$9::timestamptz)",
            grant_id, currency, amount_limit, count_limit, post_count_limit, window_start,
            window_end)

    # ---- internal-only budget operations (never exposed to a human caller class; exercised in
    # tests under the owning role directly, mirroring how 001-003 test internal helpers)
    async def budget_reserve(self, scope: Scope, change_id: UUID, grant_id: UUID,
                             amount: Any, cls: str = "worker") -> UUID:
        return await self._call(cls, scope,
                                "SELECT change_ledger.budget_reserve($1,$2,$3::uuid,$4::uuid,"
                                "$5::numeric)", change_id, grant_id, amount)

    async def budget_consume(self, scope: Scope, change_id: UUID, cls: str = "worker") -> None:
        await self._call(cls, scope, "SELECT change_ledger.budget_consume($1,$2,$3::uuid)",
                         change_id)

    async def budget_release(self, scope: Scope, change_id: UUID, cls: str = "worker") -> None:
        await self._call(cls, scope, "SELECT change_ledger.budget_release($1,$2,$3::uuid)",
                         change_id)
