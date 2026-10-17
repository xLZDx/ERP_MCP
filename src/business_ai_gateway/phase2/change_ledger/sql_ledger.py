"""Thin asyncpg port over the real ``change_ledger.*`` SQL functions (db/phase2/004-018).

No ledger logic lives here. Every method opens one transaction, optionally ``SET LOCAL ROLE`` for the
caller class, runs ``change_ledger.set_scope`` and then exactly one SQL function (the convention of
tests/phase2/test_change_ledger_sql.py ``L.call``). A rejected call becomes ``LedgerError(code)`` where
``code`` is the RAISE EXCEPTION text. ``SPEC`` is the single table of function name, parameter types,
result type and the caller classes the migrations grant EXECUTE to (the last definition wins; 005, 006 and 007
redefine earlier functions, 007 also changes some signatures); the port test compares it with pg_proc and the grants.

``actors`` maps a caller class (requester/approver/operator/writer/worker/auditor) to the database role to
assume; a missing entry means the connection already is the authenticated principal. The first class in a
function's SPEC entry is the default; ``as_class`` selects another granted class.

``ledger_head`` / ``record_checkpoint`` / ``issue_permit`` / ``attach_permit_signature`` satisfy
``checkpoint.LedgerPort``. ``issue_permit`` and ``ledger_head`` default to the worker class; since 007
``record_checkpoint`` and ``attach_permit_signature`` belong to the dedicated ``checkpoint`` class only
(``checkpoint_role``). 007 revoked the raw ``complete`` / ``verify`` / ``resolve_unknown`` / ``witness_cosign``
from every runtime role: this port has no method for them, only the typed-evidence ``*_signed`` paths.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, NamedTuple
from uuid import UUID

import asyncpg

from ._common import LedgerError, Scope, code_from_message

_IDENT = re.compile(r"[a-z][a-z0-9_]*")
CLASSES = ("requester", "approver", "operator", "writer", "worker", "auditor", "checkpoint")
_TOKEN_ROW = "change_ledger.claim_tokens"


class Fn(NamedTuple):
    name: str
    classes: tuple[str, ...]  # classes with EXECUTE; the first one is the default
    params: tuple[str, ...]  # SQL parameter types after (t, c)
    ret: str  # regtype of the result


def _f(name, classes, params, ret):
    return Fn(name, tuple(classes.split()), tuple(p for p in params.split(",") if p), ret)


SPEC: dict[str, Fn] = {
    # 004 + 005 requester / approver
    "propose": _f("propose", "requester",
                  "uuid,text,text,text,text,text,text,text,text,uuid,timestamptz,uuid", "uuid"),
    "validate": _f("validate", "requester", "uuid", "text"),
    "declare_budget": _f("declare_budget", "requester", "uuid,uuid,text,numeric,boolean,boolean", "text"),
    "claim": _f("claim", "requester", "uuid,text,uuid,numeric,boolean,boolean", _TOKEN_ROW),
    "release_claim": _f("release_claim", "requester worker", "uuid", "text"),
    "begin_apply": _f("begin_apply", "requester writer", "uuid,uuid,text,text", _TOKEN_ROW),
    "issue_approval_nonce": _f("issue_approval_nonce", "approver", "uuid", "text"),
    "approve": _f("approve", "approver", "uuid,text,text", "uuid"),
    "reject": _f("reject", "approver", "uuid,text", "text"),
    # permit / dispatch / completion
    "issue_permit": _f("issue_permit", "worker", "uuid,bigint", "jsonb"),
    "record_call": _f("record_call", "writer", "uuid,bigint,uuid", "boolean"),
    "cancel_permit": _f("cancel_permit", "worker operator", "uuid,bigint", "boolean"),
    "record_checkpoint": _f("record_checkpoint", "checkpoint",
                            "bigint,text,text,text,text,text,timestamptz,boolean", "bigint"),
    "ledger_head": _f("ledger_head", "worker writer auditor checkpoint", "", "jsonb"),
    "attach_permit_signature": _f("attach_permit_signature", "checkpoint", "uuid,bigint,text,text",
                                  "void"),
    # recovery / verification / operator
    "recover_sweep": _f("recover_sweep", "worker", "", "integer"),
    "recover_sweep_params": _f("recover_sweep", "worker", "jsonb", "jsonb"),
    "verify_inconclusive": _f("verify_inconclusive", "worker", "uuid,uuid", "jsonb"),
    "retry_verify": _f("retry_verify", "worker", "uuid,uuid,uuid,uuid", "text"),
    "check_anchor": _f("check_anchor", "worker", "bigint,text", "jsonb"),
    "verify_chain": _f("verify_chain", "auditor worker operator", "", "jsonb"),
    "operator_resolve": _f("operator_resolve", "operator", "uuid,uuid,boolean,boolean", "text"),
    "operator_close_failed_verify": _f("operator_close_failed_verify", "operator",
                                       "uuid,uuid,boolean", "text"),
    "release_hold": _f("release_hold", "operator", "uuid,jsonb", "timestamp with time zone"),
    "kill_switch": _f("kill_switch", "operator", "text", "text"),
    "budget_admin": _f("budget_admin", "operator",
                       "uuid,text,numeric,integer,integer,timestamptz,timestamptz", "uuid"),
    "budget_revoke": _f("budget_revoke", "operator", "uuid", "text"),
    "declare_anchor_gap": _f("declare_anchor_gap", "worker operator writer", "text,jsonb", "integer"),
    "declare_unclean_restart": _f("declare_unclean_restart", "worker operator", "text,jsonb",
                                  "integer"),
    # 005 registry / evidence
    "declare_business_key": _f("declare_business_key", "requester", "uuid,text,text,text", "text"),
    "declare_target_class": _f("declare_target_class", "requester", "uuid,text", "text"),
    "add_epoch_dependency": _f("add_epoch_dependency", "requester", "uuid,text", "jsonb"),
    "bind_duplicate_override": _f("bind_duplicate_override", "approver", "uuid,text", "boolean"),
    "register_principal": _f("register_principal", "operator", "text,text,text[],boolean", "bigint"),
    "enforce_registry": _f("enforce_registry", "operator", "", "boolean"),
    "register_target": _f("register_target", "operator", "text,text,text,text,timestamptz", "bigint"),
    "register_verifier_key": _f("register_verifier_key", "operator", "text,text,text", "void"),
    "revoke_verifier_key": _f("revoke_verifier_key", "operator", "text", "void"),
    "bump_epoch": _f("bump_epoch", "operator", "text", "bigint"),
    "revoke_change": _f("revoke_change", "operator worker", "uuid,text", "text"),
    "revoke_stale": _f("revoke_stale", "worker", "", "integer"),
    "record_evidence": _f("record_evidence", "worker writer",
                          "uuid,text,text,timestamptz,jsonb,text,text,text,bigint,uuid", "uuid"),
    "verify_signed": _f("verify_signed", "worker", "uuid,uuid,uuid,uuid", "text"),
    "complete_signed": _f("complete_signed", "writer", "uuid,bigint,text,uuid", "text"),
    "resolve_unknown_signed": _f("resolve_unknown_signed", "worker", "uuid,uuid,uuid,boolean,boolean",
                                 "text"),
    "witness_cosign_signed": _f("witness_cosign_signed", "operator", "uuid,uuid", "uuid"),
    "observe_target": _f("observe_target", "writer", "uuid,text,text", "boolean"),
    "read_status": _f("read_status", "requester approver auditor", "uuid", "jsonb"),
    "read_evidence": _f("read_evidence", "requester auditor", "uuid", "jsonb"),
    # 009 S12-APPROVAL-2: the canonical approval text is stored by the ledger and hashed as given
    "store_approval_text": _f("store_approval_text", "requester", "uuid,text,text", "text"),
    "read_approval_text": _f("read_approval_text", "requester approver", "uuid", "text"),
    "require_dispatch_receipt": _f("require_dispatch_receipt", "writer requester", "uuid,bigint", "void"),
    "verify_dispatch_payload": _f("verify_dispatch_payload", "writer requester", "uuid,bigint,text", "boolean"),
    "record_dispatch_receipt": _f("record_dispatch_receipt", "writer requester",
                                   "uuid,bigint,text,text,text,text", "uuid"),
    "amount_consumed": _f("amount_consumed", "operator worker auditor", "text,uuid", "numeric"),
    # 006 writer fence (complete_lock_busy re-signed in 007)
    "complete_lock_busy": _f("complete_lock_busy", "writer", "uuid,bigint,uuid,jsonb", "text"),
    "renew_writer_lease": _f("renew_writer_lease", "writer", "uuid,bigint,integer",
                             "timestamp with time zone"),
    "fence_check": _f("fence_check", "writer", "uuid,bigint,uuid", "jsonb"),
}

# Migration 022 is an explicitly staged, optional extension. Keep these signatures outside SPEC:
# consumers that apply the accepted 001-021 test/runtime baseline must remain unchanged.
_LIFECYCLE_SPEC = {
    "lifecycle_begin_recovery": _f("lifecycle_begin_recovery", "worker", "", "jsonb"),
    "lifecycle_status": _f("lifecycle_status", "worker auditor", "", "jsonb"),
    "lifecycle_writer_epoch": _f("lifecycle_writer_epoch", "writer", "uuid,bigint,bigint", "boolean"),
    "lifecycle_permit_epoch": _f("lifecycle_permit_epoch", "worker", "uuid,bigint", "bigint"),
    "lifecycle_checkpoint_suffix": _f("lifecycle_checkpoint_suffix", "worker auditor",
                                       "bigint,text,integer", "jsonb"),
}

_CAST = {"timestamp with time zone": "timestamptz"}


def _arg(ty: str, value: Any) -> Any:
    if value is None:
        return None
    if ty == "jsonb":
        return json.dumps(value)
    if ty == "numeric":
        return value if isinstance(value, Decimal) else Decimal(str(value))
    if ty == "timestamptz" and (not isinstance(value, datetime) or value.tzinfo is None):
        raise ValueError("TIMESTAMP_NOT_AWARE")
    return value


class SqlChangeLedger:
    """Implements ``checkpoint.LedgerPort`` plus the rest of the runtime surface of 004-006."""

    def __init__(self, conn: asyncpg.Connection, actors: Mapping[str, str | None] | None = None, *,
                 lifecycle_fence_enabled: bool = False):
        self.conn = conn
        self._actors = dict(actors or {})
        self._lifecycle_fence_enabled = lifecycle_fence_enabled
        for cls, role in self._actors.items():
            if cls not in CLASSES or (role is not None and not _IDENT.fullmatch(role)):
                raise ValueError("ACTOR_INVALID")

    async def invoke(self, key: str, scope: Scope, *args: Any, as_class: str | None = None) -> Any:
        fn = SPEC.get(key) or _LIFECYCLE_SPEC[key]
        if len(args) != len(fn.params):
            raise TypeError(f"{key} takes {len(fn.params)} arguments after scope, got {len(args)}")
        cls = as_class or fn.classes[0]
        if cls not in fn.classes:
            raise ValueError("ACTOR_INVALID")
        marks = "".join(f",${i + 3}::{_CAST.get(ty, ty)}" for i, ty in enumerate(fn.params))
        call = f"change_ledger.{fn.name}($1,$2{marks})"
        sql = f"SELECT * FROM {call}" if fn.ret == _TOKEN_ROW else f"SELECT {call}"
        params = [_arg(ty, a) for ty, a in zip(fn.params, args, strict=True)]
        role = self._actors.get(cls)
        if self.conn.is_in_transaction():
            # a nested transaction is only a savepoint: SET LOCAL ROLE / the scope would outlive the call and leak
            # the assumed role into the caller's transaction (008 B6q)
            raise LedgerError("TRANSACTION_ACTIVE")
        try:
            async with self.conn.transaction():
                if role:
                    await self.conn.execute(f'SET LOCAL ROLE "{role}"')
                await self.conn.fetchval("SELECT change_ledger.set_scope($1,$2)", scope.tenant_id,
                                         scope.company_id)
                if fn.ret == _TOKEN_ROW:
                    row = await self.conn.fetchrow(sql, scope.tenant_id, scope.company_id, *params)
                    return None if row is None else dict(row)
                value = await self.conn.fetchval(sql, scope.tenant_id, scope.company_id, *params)
        except asyncpg.PostgresError as e:
            raise LedgerError(code_from_message(str(e), e.sqlstate), e.sqlstate) from None
        if fn.ret == "jsonb" and isinstance(value, str):
            return json.loads(value)
        return value

    # ---- requester
    async def propose(self, scope: Scope, change_id: UUID, kind: str, base_fingerprint: str,
                      organization_ref: str, requester: str, request_id: str, payload_digest: str,
                      target_ref: str | None, target_version: str | None,
                      parent_change_id: UUID | None, expires_at: datetime,
                      repair_for: UUID | None = None) -> UUID:
        return await self.invoke("propose", scope, change_id, kind, base_fingerprint, organization_ref,
                                 requester, request_id, payload_digest, target_ref, target_version,
                                 parent_change_id, expires_at, repair_for)

    async def validate(self, scope: Scope, change_id: UUID) -> str:
        """008 (B1): no caller flags; the budget pre-check and the duplicate check come from the stored change."""
        return await self.invoke("validate", scope, change_id)

    async def declare_budget(self, scope: Scope, change_id: UUID, grant_id: UUID, currency: str, amount: Any,
                             counts_create_update: bool = False, counts_post: bool = False) -> str:
        """008 (B1): the budget inputs claim derives its reservation from (inside the approval digest)."""
        return await self.invoke("declare_budget", scope, change_id, grant_id, currency, amount,
                                 counts_create_update, counts_post)

    async def claim(self, scope: Scope, change_id: UUID, key_hash: str | None = None,
                    grant_id: UUID | None = None, amount: Any = None,
                    counts_create_update: bool = False, counts_post: bool = False) -> dict | None:
        return await self.invoke("claim", scope, change_id, key_hash, grant_id, amount,
                                 counts_create_update, counts_post)

    async def release_claim(self, scope: Scope, token_id: UUID, as_class: str | None = None) -> str:
        return await self.invoke("release_claim", scope, token_id, as_class=as_class)

    async def begin_apply(self, scope: Scope, token_id: UUID, call_id: UUID, writer_host: str,
                          onec_session: str, as_class: str | None = None) -> dict | None:
        return await self.invoke("begin_apply", scope, token_id, call_id, writer_host, onec_session,
                                 as_class=as_class)

    async def declare_business_key(self, scope: Scope, change_id: UUID, key_hash: str,
                                   override_of: str | None = None,
                                   justification: str | None = None) -> str:
        return await self.invoke("declare_business_key", scope, change_id, key_hash, override_of,
                                 justification)

    async def declare_target_class(self, scope: Scope, change_id: UUID, target_class: str) -> str:
        return await self.invoke("declare_target_class", scope, change_id, target_class)

    async def add_epoch_dependency(self, scope: Scope, change_id: UUID, key: str) -> dict:
        return await self.invoke("add_epoch_dependency", scope, change_id, key)

    # ---- approver
    async def issue_approval_nonce(self, scope: Scope, change_id: UUID) -> str:
        return await self.invoke("issue_approval_nonce", scope, change_id)

    async def approve(self, scope: Scope, change_id: UUID, nonce: str, digest: str) -> UUID:
        return await self.invoke("approve", scope, change_id, nonce, digest)

    async def reject(self, scope: Scope, change_id: UUID, nonce: str) -> str:
        return await self.invoke("reject", scope, change_id, nonce)

    async def bind_duplicate_override(self, scope: Scope, change_id: UUID, override_digest: str) -> bool:
        return await self.invoke("bind_duplicate_override", scope, change_id, override_digest)

    # ---- permit gate (worker identity) and writer
    async def ledger_head(self, scope: Scope, as_class: str | None = "worker") -> dict:
        return await self.invoke("ledger_head", scope, as_class=as_class)

    async def record_checkpoint(self, scope: Scope, seq: int, head_hash: str, sink_kind: str,
                                sink_id: str, key_id: str, signature: str, signed_at: datetime,
                                read_back: bool, as_class: str | None = "checkpoint") -> int:
        return await self.invoke("record_checkpoint", scope, seq, head_hash, sink_kind, sink_id, key_id,
                                 signature, signed_at, read_back, as_class=as_class)

    async def issue_permit(self, scope: Scope, change_id: UUID, generation: int) -> dict:
        if self._lifecycle_fence_enabled:
            lifecycle = await self.lifecycle_status(scope)
            if lifecycle.get("state") != "READY":
                raise LedgerError("LIFECYCLE_NOT_READY")
        permit = await self.invoke("issue_permit", scope, change_id, generation)
        if not self._lifecycle_fence_enabled:
            return permit
        epoch = await self.invoke("lifecycle_permit_epoch", scope, change_id, generation)
        if permit is None or epoch is None:
            raise LedgerError("LIFECYCLE_NOT_READY")
        return {**permit, "lifecycle_epoch": int(epoch)}

    async def attach_permit_signature(self, scope: Scope, change_id: UUID, generation: int,
                                      key_id: str, signature: str,
                                      as_class: str | None = "checkpoint") -> None:
        await self.invoke("attach_permit_signature", scope, change_id, generation, key_id, signature,
                          as_class=as_class)

    async def record_call(self, scope: Scope, change_id: UUID, generation: int, call_id: UUID) -> bool:
        return await self.invoke("record_call", scope, change_id, generation, call_id)

    async def cancel_permit(self, scope: Scope, change_id: UUID, generation: int,
                            as_class: str | None = None) -> bool:
        return await self.invoke("cancel_permit", scope, change_id, generation, as_class=as_class)

    async def complete_lock_busy(self, scope: Scope, change_id: UUID, generation: int,
                                 completion: UUID | None, params: dict | None = None) -> str:
        return await self.invoke("complete_lock_busy", scope, change_id, generation, completion,
                                 params if params is not None else {})

    async def renew_writer_lease(self, scope: Scope, change_id: UUID, generation: int,
                                 ttl_seconds: int = 300) -> datetime:
        return await self.invoke("renew_writer_lease", scope, change_id, generation, ttl_seconds)

    async def fence_check(self, scope: Scope, change_id: UUID, generation: int, call_id: UUID) -> dict:
        return await self.invoke("fence_check", scope, change_id, generation, call_id)

    async def lifecycle_begin_recovery(self, scope: Scope) -> dict:
        """Atomically invalidate prior writer epochs and fence this scope as RECOVERING."""
        return await self.invoke("lifecycle_begin_recovery", scope)

    async def lifecycle_status(self, scope: Scope) -> dict:
        """Read the durable lifecycle fence; absence is reported by SQL as NOT_READY."""
        return await self.invoke("lifecycle_status", scope)

    async def lifecycle_checkpoint_suffix(self, scope: Scope, checkpoint_seq: int,
                                          checkpoint_hash: str, limit: int = 128) -> dict:
        """Read a bounded, scope-bound event suffix; this does not authorize lifecycle readiness."""
        return await self.invoke("lifecycle_checkpoint_suffix", scope, checkpoint_seq,
                                 checkpoint_hash, limit)

    async def lifecycle_writer_epoch(self, scope: Scope, change_id: UUID, generation: int,
                                    expected_epoch: int) -> bool:
        """Check this persisted permit epoch immediately before a physical writer call.

        The SQL transaction ends before the external call, so this check alone does not close the
        subsequent recovery-start race; the dispatch CAS remains the last transactional fence.
        """
        return await self.invoke("lifecycle_writer_epoch", scope, change_id, generation,
                                 expected_epoch)

    async def observe_target(self, scope: Scope, token_id: UUID, fingerprint: str,
                             target_class: str) -> bool:
        return await self.invoke("observe_target", scope, token_id, fingerprint, target_class)

    async def complete_signed(self, scope: Scope, change_id: UUID, generation: int, outcome: str,
                              completion: UUID | None) -> str:
        return await self.invoke("complete_signed", scope, change_id, generation, outcome, completion)

    # ---- worker
    async def recover_sweep(self, scope: Scope, params: dict | None = None) -> Any:
        """No params: the legacy integer count; with params: the jsonb report of 006."""
        if params is None:
            return await self.invoke("recover_sweep", scope)
        return await self.invoke("recover_sweep_params", scope, params)

    async def verify_inconclusive(self, scope: Scope, change_id: UUID, observation: UUID) -> dict:
        return await self.invoke("verify_inconclusive", scope, change_id, observation)

    async def retry_verify(self, scope: Scope, change_id: UUID, field: UUID | None,
                           movement: UUID | None, version: UUID | None) -> str:
        return await self.invoke("retry_verify", scope, change_id, field, movement, version)

    async def check_anchor(self, scope: Scope, ext_seq: int, ext_head_hash: str) -> dict:
        return await self.invoke("check_anchor", scope, ext_seq, ext_head_hash)

    async def verify_chain(self, scope: Scope, as_class: str | None = None) -> dict:
        return await self.invoke("verify_chain", scope, as_class=as_class)

    async def revoke_stale(self, scope: Scope) -> int:
        return await self.invoke("revoke_stale", scope)

    async def record_evidence(self, scope: Scope, change_id: UUID, kind: str, content_hash: str,
                              observed_at: datetime, content: dict | None, key_id: str,
                              binding_hash: str, signature: str, generation: int | None,
                              call_id: UUID | None, as_class: str | None = None) -> UUID:
        return await self.invoke("record_evidence", scope, change_id, kind, content_hash, observed_at,
                                 content, key_id, binding_hash, signature, generation, call_id,
                                 as_class=as_class)

    async def verify_signed(self, scope: Scope, change_id: UUID, field: UUID | None,
                            movement: UUID | None, version: UUID | None) -> str:
        return await self.invoke("verify_signed", scope, change_id, field, movement, version)

    async def resolve_unknown_signed(self, scope: Scope, change_id: UUID, observation: UUID,
                                     completion: UUID | None, found: bool | None,
                                     attributed: bool = False) -> str:
        return await self.invoke("resolve_unknown_signed", scope, change_id, observation, completion,
                                 found, attributed)

    # ---- operator
    async def witness_cosign_signed(self, scope: Scope, change_id: UUID, completion: UUID) -> UUID:
        return await self.invoke("witness_cosign_signed", scope, change_id, completion)

    async def operator_resolve(self, scope: Scope, change_id: UUID, cosign_id: UUID | None,
                               present: bool, attributed: bool) -> str:
        return await self.invoke("operator_resolve", scope, change_id, cosign_id, present, attributed)

    async def operator_close_failed_verify(self, scope: Scope, change_id: UUID,
                                           cosign_id: UUID | None, effect_present: bool) -> str:
        return await self.invoke("operator_close_failed_verify", scope, change_id, cosign_id,
                                 effect_present)

    async def release_hold(self, scope: Scope, hold_id: UUID, release_evidence: dict | None) -> datetime:
        return await self.invoke("release_hold", scope, hold_id, release_evidence)

    async def kill_switch(self, scope: Scope, mode: str) -> str:
        return await self.invoke("kill_switch", scope, mode)

    async def budget_revoke(self, scope: Scope, grant_id: UUID) -> str:
        return await self.invoke("budget_revoke", scope, grant_id)

    async def budget_admin(self, scope: Scope, grant_id: UUID | None, currency: str, amount_limit: Any,
                           count_limit: int, post_count_limit: int, window_start: datetime,
                           window_end: datetime) -> UUID:
        return await self.invoke("budget_admin", scope, grant_id, currency, amount_limit, count_limit,
                                 post_count_limit, window_start, window_end)

    async def declare_anchor_gap(self, scope: Scope, base: str | None, detail: dict | None,
                                 as_class: str | None = None) -> int:
        return await self.invoke("declare_anchor_gap", scope, base, detail, as_class=as_class)

    async def declare_unclean_restart(self, scope: Scope, base: str | None, detail: dict | None,
                                      as_class: str | None = None) -> int:
        return await self.invoke("declare_unclean_restart", scope, base, detail, as_class=as_class)

    async def revoke_change(self, scope: Scope, change_id: UUID, cause: str,
                            as_class: str | None = None) -> str:
        return await self.invoke("revoke_change", scope, change_id, cause, as_class=as_class)

    async def register_principal(self, scope: Scope, principal: str, person_id: str | None,
                                 capabilities: list[str], active: bool = True) -> int:
        return await self.invoke("register_principal", scope, principal, person_id, capabilities, active)

    async def enforce_registry(self, scope: Scope) -> bool:
        return await self.invoke("enforce_registry", scope)

    async def register_target(self, scope: Scope, base: str, org: str, target_class: str,
                              status: str = "ACTIVE", permission_expires_at: datetime | None = None) -> int:
        return await self.invoke("register_target", scope, base, org, target_class, status,
                                 permission_expires_at)

    async def register_verifier_key(self, scope: Scope, key_id: str, role_name: str,
                                    key_material: str) -> None:
        await self.invoke("register_verifier_key", scope, key_id, role_name, key_material)

    async def revoke_verifier_key(self, scope: Scope, key_id: str) -> None:
        await self.invoke("revoke_verifier_key", scope, key_id)

    async def bump_epoch(self, scope: Scope, key: str) -> int:
        return await self.invoke("bump_epoch", scope, key)

    # ---- 009 S12-APPROVAL-2
    async def store_approval_text(self, scope: Scope, change_id: UUID, nonce: str, text: str) -> str:
        """Store the canonical approval text (change.proposal.approval_canonical_text) for one issued nonce; returns
        its digest (sha256 of the stored UTF-8 bytes). The ledger refuses a text that differs from its own state."""
        return await self.invoke("store_approval_text", scope, change_id, nonce, text)

    async def read_approval_text(self, scope: Scope, change_id: UUID, as_class: str | None = None) -> str | None:
        return await self.invoke("read_approval_text", scope, change_id, as_class=as_class)

    async def verify_dispatch_payload(self, scope: Scope, change_id: UUID, generation: int,
                                      payload_text: str | None, as_class: str | None = None) -> bool:
        """Check canonical JSON text against the approved payload and persist its distinct wire-byte SHA-256.

        ``None`` represents the canonical ``{}`` bytes for operations without a payload. The typed-payload digest
        remains the approval identity; the byte digest binds the clone receipt. Non-canonical text is refused.
        """
        return await self.invoke("verify_dispatch_payload", scope, change_id, generation, payload_text,
                                 as_class=as_class)

    async def require_dispatch_receipt(self, scope: Scope, change_id: UUID, generation: int,
                                       as_class: str | None = None) -> None:
        """Require a clone receipt before this generation can complete as APPLIED (opt-in per generation)."""
        await self.invoke("require_dispatch_receipt", scope, change_id, generation, as_class=as_class)

    async def record_dispatch_receipt(self, scope: Scope, change_id: UUID, generation: int,
                                      key_id: str, received_payload_sha256: str, new_version: str,
                                      signature: str, as_class: str | None = None) -> UUID:
        """Persist the clone-produced receipt; SQL verifies its signature and verified wire digest."""
        return await self.invoke("record_dispatch_receipt", scope, change_id, generation, key_id,
                                 received_payload_sha256, new_version, signature, as_class=as_class)

    # ---- reads
    async def read_status(self, scope: Scope, change_id: UUID, as_class: str | None = None) -> dict:
        return await self.invoke("read_status", scope, change_id, as_class=as_class)

    async def read_evidence(self, scope: Scope, change_id: UUID, as_class: str | None = None) -> list:
        return await self.invoke("read_evidence", scope, change_id, as_class=as_class)

    async def amount_consumed(self, scope: Scope, document: str, grant_id: UUID,
                              as_class: str | None = None) -> Decimal:
        return await self.invoke("amount_consumed", scope, document, grant_id, as_class=as_class)
