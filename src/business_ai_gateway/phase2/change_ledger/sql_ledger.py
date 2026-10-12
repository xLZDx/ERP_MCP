"""Thin asyncpg port over the chg.* SQL functions (db/phase2/004_change_ledger.sql).

No ledger logic lives here: each method opens one transaction, optionally ``SET LOCAL ROLE`` for the
caller class, calls ``chg.set_scope`` and then exactly one SQL function. SQL refusals become
``LedgerError(code)``. ``actors`` maps a caller class to the database role to assume (tests use a
superuser connection); a missing/None entry means the connection already is the authenticated principal.
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
_CLASSES = ("requester", "approver", "operator", "writer", "worker", "auditor", "owner")


def _j(value: Any) -> str | None:
    return None if value is None else json.dumps(value)


class SqlChangeLedger:
    def __init__(self, conn: asyncpg.Connection, actors: Mapping[str, str | None] | None = None):
        self.conn = conn
        self._actors = dict(actors or {})
        for cls, role in self._actors.items():
            if cls not in _CLASSES or (role is not None and not _IDENT.fullmatch(role)):
                raise ValueError("ACTOR_INVALID")

    async def _call(self, cls: str, scope: Scope, sql: str, *args: Any) -> Any:
        role = self._actors.get(cls)
        try:
            async with self.conn.transaction():
                if role:
                    await self.conn.execute(f'SET LOCAL ROLE "{role}"')
                await self.conn.fetchval("SELECT chg.set_scope($1,$2)", scope.tenant_id,
                                         scope.company_id)
                value = await self.conn.fetchval(sql, scope.tenant_id, scope.company_id, *args)
        except asyncpg.PostgresError as e:
            raise LedgerError(code_from_message(str(e), e.sqlstate)) from None
        if isinstance(value, str) and value[:1] in "{[":
            return json.loads(value)
        return value

    # ---- requester
    async def propose(self, scope: Scope, request_id: str, kind: str, organization: str,
                      base_fingerprint: str, payload: dict, payload_digest: str,
                      expires_at: datetime, *, parent_change_id: UUID | None = None,
                      repair_for: UUID | None = None, target_ref: str | None = None,
                      target_version: str | None = None, business_key_hash: str | None = None,
                      business_state_digest: str | None = None,
                      dependency_keys: list[str] | None = None, reason: str | None = None,
                      change_id: UUID | None = None) -> dict:
        return await self._call(
            "requester", scope,
            "SELECT chg.propose($1,$2,$3,$4,$5,$6,$7::uuid,$8::uuid,$9,$10,$11::jsonb,$12,$13,$14,"
            "$15::text[],$16::timestamptz,$17,$18::uuid)",
            request_id, kind, organization, base_fingerprint, parent_change_id, repair_for,
            target_ref, target_version, json.dumps(payload), payload_digest, business_key_hash,
            business_state_digest, dependency_keys or [], expires_at, reason, change_id)

    async def validate(self, scope: Scope, change_id: UUID, preview_digest: str,
                       allowed_effects: list, rule_table_version: str, shape_qualified: bool,
                       key_collision: bool) -> dict:
        return await self._call("requester", scope,
                                "SELECT chg.validate($1,$2,$3::uuid,$4,$5::jsonb,$6,$7,$8)",
                                change_id, preview_digest, json.dumps(allowed_effects),
                                rule_table_version, shape_qualified, key_collision)

    async def claim(self, scope: Scope, change_id: UUID) -> dict:
        return await self._call("requester", scope, "SELECT chg.claim($1,$2,$3::uuid)", change_id)

    async def release_claim(self, scope: Scope, change_id: UUID, cls: str = "requester") -> dict:
        return await self._call(cls, scope, "SELECT chg.release_claim($1,$2,$3::uuid)", change_id)

    async def begin_apply(self, scope: Scope, token: str, call_id: UUID, writer_process: str,
                          host: str, session: str, observed_fingerprint: str,
                          observed_version: str | None, observed_state_digest: str | None,
                          pre_image_hashes: dict, hard_deadline_seconds: int | None = None,
                          cls: str = "writer") -> dict:
        return await self._call(
            cls, scope,
            "SELECT chg.begin_apply($1,$2,$3,$4::uuid,$5,$6,$7,$8,$9,$10,$11::jsonb,$12::integer)",
            token, call_id, writer_process, host, session, observed_fingerprint, observed_version,
            observed_state_digest, json.dumps(pre_image_hashes), hard_deadline_seconds)

    # ---- approver
    async def approval_digest(self, scope: Scope, change_id: UUID) -> str:
        return await self._call("approver", scope, "SELECT chg.approval_digest($1,$2,$3::uuid)",
                                change_id)

    async def issue_approval_nonce(self, scope: Scope, change_id: UUID) -> dict:
        return await self._call("approver", scope,
                                "SELECT chg.issue_approval_nonce($1,$2,$3::uuid)", change_id)

    async def approve(self, scope: Scope, change_id: UUID, nonce: UUID, digest_set_hash: str,
                      approval_type: str = "HUMAN") -> dict:
        cls = "operator" if approval_type == "TEST_LANE_AUTO" else "approver"
        return await self._call(cls, scope, "SELECT chg.approve($1,$2,$3::uuid,$4::uuid,$5,$6)",
                                change_id, nonce, digest_set_hash, approval_type)

    async def reject(self, scope: Scope, change_id: UUID) -> dict:
        return await self._call("approver", scope, "SELECT chg.reject($1,$2,$3::uuid)", change_id)

    # ---- writer
    async def record_call(self, scope: Scope, change_id: UUID, generation: int,
                          call_id: UUID) -> dict:
        return await self._call("writer", scope,
                                "SELECT chg.record_call($1,$2,$3::uuid,$4::integer,$5::uuid)",
                                change_id, generation, call_id)

    async def complete(self, scope: Scope, change_id: UUID, generation: int, call_id: UUID,
                       evidence_id: UUID) -> dict:
        return await self._call(
            "writer", scope,
            "SELECT chg.complete($1,$2,$3::uuid,$4::integer,$5::uuid,$6::uuid)",
            change_id, generation, call_id, evidence_id)

    async def read_permit(self, scope: Scope, change_id: UUID, generation: int,
                          cls: str = "writer") -> dict:
        return await self._call(cls, scope,
                                "SELECT chg.read_permit($1,$2,$3::uuid,$4::integer)",
                                change_id, generation)

    async def record_evidence(self, scope: Scope, change_id: UUID, kind: str, payload_text: str,
                              content_hash: str, observed_at: datetime, key_id: str,
                              signature: str, cls: str = "worker") -> UUID:
        return await self._call(
            cls, scope,
            "SELECT chg.record_evidence($1,$2,$3::uuid,$4,$5,$6,$7::timestamptz,$8,$9)",
            change_id, kind, payload_text, content_hash, observed_at, key_id, signature)

    # ---- worker
    async def recover_sweep(self, scope: Scope, limit: int = 200) -> list:
        return await self._call("worker", scope, "SELECT chg.recover_sweep($1,$2,$3::integer)",
                                limit)

    async def issue_permit(self, scope: Scope, change_id: UUID, generation: int) -> dict:
        return await self._call("worker", scope,
                                "SELECT chg.issue_permit($1,$2,$3::uuid,$4::integer)",
                                change_id, generation)

    async def attach_permit_signature(self, scope: Scope, change_id: UUID, generation: int,
                                      key_id: str, signature: str) -> None:
        await self._call("worker", scope,
                         "SELECT chg.attach_permit_signature($1,$2,$3::uuid,$4::integer,$5,$6)",
                         change_id, generation, key_id, signature)

    async def resolve_unknown(self, scope: Scope, change_id: UUID, observation_id: UUID,
                              completion_id: UUID | None = None) -> dict:
        return await self._call("worker", scope,
                                "SELECT chg.resolve_unknown($1,$2,$3::uuid,$4::uuid,$5::uuid)",
                                change_id, observation_id, completion_id)

    async def verify(self, scope: Scope, change_id: UUID, field_id: UUID, movement_id: UUID,
                     version_id: UUID) -> dict:
        return await self._call(
            "worker", scope, "SELECT chg.verify($1,$2,$3::uuid,$4::uuid,$5::uuid,$6::uuid)",
            change_id, field_id, movement_id, version_id)

    async def record_checkpoint(self, scope: Scope, seq: int, head_hash: str, sink_kind: str,
                                sink_id: str, key_id: str, signature: str, signed_at: datetime,
                                read_back: bool) -> dict:
        return await self._call(
            "worker", scope,
            "SELECT chg.record_checkpoint($1,$2,$3::bigint,$4,$5,$6,$7,$8,$9::timestamptz,$10)",
            seq, head_hash, sink_kind, sink_id, key_id, signature, signed_at, read_back)

    async def check_anchor(self, scope: Scope, ext_seq: int, ext_head_hash: str) -> dict:
        return await self._call("worker", scope, "SELECT chg.check_anchor($1,$2,$3::bigint,$4)",
                                ext_seq, ext_head_hash)

    async def declare_unclean_restart(self, scope: Scope, base_fingerprint: str) -> int:
        return await self._call("worker", scope, "SELECT chg.declare_unclean_restart($1,$2,$3)",
                                base_fingerprint)

    # ---- operator
    async def operator_resolve(self, scope: Scope, change_id: UUID, resolution: str,
                               signer_role: str, observation_id: UUID,
                               completion_id: UUID) -> dict:
        return await self._call(
            "operator", scope,
            "SELECT chg.operator_resolve($1,$2,$3::uuid,$4,$5,$6::uuid,$7::uuid)",
            change_id, resolution, signer_role, observation_id, completion_id)

    async def release_hold(self, scope: Scope, hold_id: int,
                           evidence_id: UUID | None = None) -> dict:
        return await self._call("operator", scope,
                                "SELECT chg.release_hold($1,$2,$3::bigint,$4::uuid)",
                                hold_id, evidence_id)

    async def kill_switch(self, scope: Scope, mode: str) -> dict:
        return await self._call("operator", scope, "SELECT chg.kill_switch($1,$2,$3)", mode)

    async def budget_admin(self, scope: Scope, grant_id: UUID, currency: str,
                           amount_limit: Any, create_update_limit: int, post_limit: int,
                           window_start: datetime, window_end: datetime, status: str) -> dict:
        return await self._call(
            "operator", scope,
            "SELECT chg.budget_admin($1,$2,$3::uuid,$4,$5::numeric,$6::integer,$7::integer,"
            "$8::timestamptz,$9::timestamptz,$10)",
            grant_id, currency, amount_limit, create_update_limit, post_limit, window_start,
            window_end, status)

    async def bump_epoch(self, scope: Scope, dep_key: str) -> int:
        return await self._call("operator", scope, "SELECT chg.bump_epoch($1,$2,$3)", dep_key)

    # ---- read (any class)
    async def ledger_head(self, scope: Scope, cls: str = "worker") -> dict:
        return await self._call(cls, scope, "SELECT chg.ledger_head($1,$2)")

    async def verify_chain(self, scope: Scope, cls: str = "auditor") -> dict:
        return await self._call(cls, scope, "SELECT chg.verify_chain($1,$2)")

    async def read_status(self, scope: Scope, change_id: UUID, cls: str = "requester") -> dict:
        return await self._call(cls, scope, "SELECT chg.read_status($1,$2,$3::uuid)", change_id)

    # ---- owner administration
    async def add_role_scope(self, scope: Scope, role: str) -> None:
        await self._call("owner", scope, "SELECT chg.add_role_scope($3,$1,$2)", role)

    async def register_principal(self, scope: Scope, principal: str, person_id: str, *,
                                 active: bool = True, approver: bool = False,
                                 operator: bool = False, witness: bool = False) -> None:
        await self._call("owner", scope,
                         "SELECT chg.register_principal($1,$2,$3,$4,$5,$6,$7,$8)",
                         principal, person_id, active, approver, operator, witness)

    async def register_target(self, scope: Scope, organization: str, base_fingerprint: str,
                              target_class: str, status: str = "ACTIVE",
                              permission_expires_at: datetime | None = None,
                              operator_signature: str | None = None) -> None:
        await self._call(
            "owner", scope,
            "SELECT chg.register_target($1,$2,$3,$4,$5,$6,$7::timestamptz,$8)",
            organization, base_fingerprint, target_class, status, permission_expires_at,
            operator_signature)
