"""Thin asyncpg port over the real ``change_ledger.*`` SQL functions (db/phase2/004-018).

No ledger logic lives here. Every method opens one transaction, optionally ``SET LOCAL ROLE`` for the
caller class, runs ``change_ledger.set_scope`` and then exactly one SQL function (the convention of
tests/phase2/test_change_ledger_sql.py ``L.call``). A rejected call becomes ``LedgerError(code)`` where
``code`` is the RAISE EXCEPTION text for contract codes or a safe SQLSTATE-derived fallback. A raw
SQLSTATE 55P03 remains ``SQL_55P03``; only the future S13 fence helper can identify its own bounded
lock wait and raise the explicit ``LEDGER_LOCK_TIMEOUT`` contract code. ``SPEC`` is the single table
of function name, parameter types,
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
from types import MappingProxyType
from typing import Any, NamedTuple
from uuid import UUID, uuid4

import asyncpg

from ._common import LedgerError, Scope, code_from_message

_IDENT = re.compile(r"[a-z][a-z0-9_]*")
CLASSES = ("requester", "approver", "operator", "writer", "worker", "auditor", "checkpoint")
_TOKEN_ROW = "change_ledger.claim_tokens"
_SQL_LEDGER_IMMUTABLE_CONFIGURATION = frozenset({
    "conn", "_actors", "_lifecycle_fence_enabled", "_private_writer_schema_enabled",
})


class Fn(NamedTuple):
    name: str
    classes: tuple[str, ...]  # classes with EXECUTE; the first one is the default
    params: tuple[str, ...]  # SQL parameter types after (t, c)
    ret: str  # regtype of the result


def _f(name, classes, params, ret):
    return Fn(name, tuple(classes.split()), tuple(p for p in params.split(",") if p), ret)


SPEC: Mapping[str, Fn] = MappingProxyType({
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
    "propose_registry_change": _f("propose_registry_change", "operator", "text,jsonb", "uuid"),
    "bump_epoch": _f("bump_epoch", "operator", "text", "bigint"),
    "approve_registry_change": _f("approve_registry_change", "operator", "uuid,text", "jsonb"),
    "set_sweep_policy": _f("set_sweep_policy", "operator", "jsonb", "jsonb"),
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
})

# Migration 022 is an explicitly staged, optional extension. Keep these signatures outside SPEC:
# consumers that apply the accepted 001-021 test/runtime baseline must remain unchanged.
_LIFECYCLE_SPEC: Mapping[str, Fn] = MappingProxyType({
    "lifecycle_begin_recovery": _f("lifecycle_begin_recovery", "worker", "", "jsonb"),
    "lifecycle_status": _f("lifecycle_status", "worker auditor", "", "jsonb"),
    "lifecycle_writer_epoch": _f("lifecycle_writer_epoch", "writer", "uuid,bigint,bigint", "boolean"),
    "lifecycle_permit_epoch": _f("lifecycle_permit_epoch", "worker", "uuid,bigint", "bigint"),
    "lifecycle_checkpoint_suffix": _f("lifecycle_checkpoint_suffix", "worker auditor",
                                       "bigint,text,integer", "jsonb"),
})

# Migration 027's additive S13 preparation path stays opt-in until the disposable
# qualification and role-by-role grant review have passed. These signatures do not
# replace the 001-026 adapter surface by default.
_PRIVATE_WRITER_SPEC: Mapping[str, Fn] = MappingProxyType({
    "begin_apply_s13": _f("change_ledger_begin_apply_v1", "requester writer",
                           "uuid,uuid,text,text", _TOKEN_ROW),
    # Proposal v1 captures target/principal epoch dependencies. Keep the granted legacy
    # proposal entry unchanged until every concurrent epoch writer shares namespace 7.
    # Use the granted SECURITY DEFINER bridge; direct propose_v1 is deliberately revoked.
    "propose_s13": _f("propose", "requester",
                        "uuid,text,text,text,text,text,text,text,text,uuid,timestamptz,uuid", "uuid"),
    # The bridge preserves caller ACLs while delegating to the fenced candidate body.
    "validate_s13": _f("validate", "requester", "uuid", "text"),
    "dispatch_intent_for_call": _f("private_writer_dispatch_intent_for_call_v1",
                                    "requester writer worker", "uuid", "jsonb_composite"),
    "permit_binding_for_intent": _f("private_writer_permit_binding_for_intent_v1",
                                     "worker", "uuid", "jsonb_composite"),
    "issue_permit_s13": _f("private_writer_issue_permit_v1", "worker",
                            "uuid,bigint,uuid,uuid,text,text,text", "jsonb_composite"),
    # S13 replaces the legacy checkpoint function body with the scope-fenced candidate body.
    # Keep the candidate-mode call explicit so it cannot fall through the legacy API allowlist.
    "record_checkpoint_s13": _f("record_checkpoint", "checkpoint",
                                "bigint,text,text,text,text,text,timestamptz,boolean", "bigint"),
    # The adapter preserves the legacy default, but an explicitly enabled S13 schema must
    # route this writer entry to the versioned fence/replay contract and fail closed if absent.
    "observe_target_s13": _f("observe_target_v1", "writer", "uuid,text,text", "boolean"),
    # Approval-envelope persistence joins the S13 scope/lifecycle/global-record fence.
    # Keep the legacy route as the default until the complete nonce/approval writer cutover is qualified.
    "store_approval_text_s13": _f("store_approval_text_v1", "requester", "uuid,text,text,uuid", "text"),
    "issue_approval_nonce_s13": _f("issue_approval_nonce_v1", "approver", "uuid,text", "text"),
    "approve_s13": _f("approve_v1", "approver", "uuid,text,text,uuid", "uuid"),
    "reject_s13": _f("reject_v1", "approver", "uuid,text,uuid", "text"),
    # Epoch dependency v1 is source-only and intentionally has no candidate-schema EXECUTE grant
    # yet: its namespace-7 snapshot is unsafe until every same-scope epoch writer is fenced.
    # Keep the legacy default and fail closed if an enabled candidate schema lacks the grant.
    "add_epoch_dependency_s13": _f("add_epoch_dependency_v1", "requester", "uuid,text", "jsonb"),
    # Candidate bump shares namespace 2/7 with dependency capture, but remains ungranted until
    # principal/target registration and registry approval have joined the same fence.
    "bump_epoch_s13": _f("bump_epoch_v1", "operator", "text", "bigint"),
    # Candidate registry entries take namespace 2/7 and validate lifecycle before registry reads.
    # They remain ungranted until registry approval and verifier-key paths complete the same gate.
    "register_principal_s13": _f("register_principal_v1", "operator",
                                   "text,text,text[],boolean", "bigint"),
    "register_target_s13": _f("register_target_v1", "operator",
                                "text,text,text,text,timestamptz", "bigint"),
    "approve_registry_change_s13": _f("approve_registry_change_v1", "operator",
                                        "uuid,text", "jsonb"),
    "enforce_registry_s13": _f("enforce_registry_v1", "operator", "", "boolean"),
    "register_verifier_key_s13": _f("register_verifier_key_v1", "operator",
                                      "text,text,text", "void"),
    "revoke_verifier_key_s13": _f("revoke_verifier_key_v1", "operator", "text", "void"),
    "propose_registry_change_s13": _f("propose_registry_change_v1", "operator",
                                        "uuid,text,jsonb", "uuid"),
    "require_dispatch_receipt_s13": _f("require_dispatch_receipt_v1", "writer requester",
                                         "uuid,bigint", "void"),
    "record_dispatch_receipt_s13": _f("record_dispatch_receipt_v1", "writer requester",
                                        "uuid,bigint,text,text,text,text,uuid", "uuid"),
    "verify_dispatch_payload_s13": _f("verify_dispatch_payload_v1", "writer requester",
                                        "uuid,bigint,text,uuid", "boolean"),
    "record_evidence_s13": _f("record_evidence_v1", "worker writer",
                                "uuid,text,text,timestamptz,jsonb,text,text,text,bigint,uuid,uuid", "uuid"),
    # A signed T16 witness joins the candidate scope fence and uses an explicit replay identity.
    # It remains ungranted until the complete cosign/cutover path is qualified.
    "witness_cosign_signed_s13": _f("witness_cosign_signed_v1", "operator", "uuid,uuid", "uuid"),
    # Terminal T16 resolution consumes immutable private-writer evidence references and returns
    # the exact appended event ID for the separate post-commit checkpoint/read-back boundary.
    "operator_resolve_s13": _f("operator_resolve_v1", "operator",
                                 "uuid,uuid,uuid,text,text,text,text,text", "jsonb"),
    # There is no separate legacy adapter key; migration 027 preserves the SQL name as a bridge,
    # while direct versioned adapter routing remains feature-gated and separately qualified.
    "anchor_gap_cosign_s13": _f("anchor_gap_cosign_v1", "operator", "uuid,jsonb", "uuid"),
    # T17's additive closure route is source-only until its FK-SCC/race qualification passes.
    "operator_close_failed_verify_s13": _f("operator_close_failed_verify_v1", "operator",
                                             "uuid,uuid,boolean", "text"),
    # Direct v1 routing remains explicitly feature-gated. In a disposable 027 candidate schema,
    # the preserved legacy SQL signature itself bridges to v1 and is qualified as a separate route.
    "attach_permit_signature_s13": _f("attach_permit_signature_v1", "checkpoint",
                                        "uuid,bigint,text,text", "void"),
    "set_sweep_policy_s13": _f("set_sweep_policy_v1", "operator", "jsonb", "jsonb"),
    "bind_duplicate_override_s13": _f("bind_duplicate_override_v1", "approver", "uuid,text", "boolean"),
    "declare_business_key_s13": _f("declare_business_key_v1", "requester",
                                     "uuid,text,text,text", "text"),
    "budget_admin_s13": _f("budget_admin_v1", "operator",
                              "uuid,text,numeric,integer,integer,timestamptz,timestamptz", "uuid"),
    "budget_revoke_s13": _f("budget_revoke_v1", "operator", "uuid", "text"),
    "declare_budget_s13": _f("declare_budget_v1", "requester",
                                "uuid,uuid,text,numeric,boolean,boolean", "text"),
    "claim_s13": _f("claim_with_id_v1", "requester",
                     "uuid,text,uuid,numeric,boolean,boolean,uuid", _TOKEN_ROW),
    # Candidate migration keeps direct release_claim_v1 revoked and preserves its legacy
    # SECURITY DEFINER bridge as the caller boundary.
    "release_claim_s13": _f("release_claim", "requester worker", "uuid", "text"),
    "renew_writer_lease_s13": _f("renew_writer_lease_v1", "writer", "uuid,bigint,integer", "timestamptz"),
    "declare_anchor_gap_s13": _f("declare_anchor_gap_v1", "worker operator writer", "text,jsonb", "integer"),
    "declare_unclean_restart_s13": _f("declare_unclean_restart_v1", "worker operator", "text,jsonb", "integer"),
    "check_anchor_s13": _f("check_anchor_v1", "worker", "bigint,text", "jsonb"),
    "cancel_permit_s13": _f("cancel_permit_v1", "worker operator", "uuid,bigint", "boolean"),
    "release_hold_s13": _f("release_hold_v1", "operator", "uuid,jsonb", "timestamptz"),
    "revoke_change_s13": _f("revoke_change_v1", "operator", "uuid,text", "text"),
    "revoke_stale_s13": _f("revoke_stale_v1", "worker", "", "integer"),
    "recover_sweep_s13": _f("recover_sweep_v1", "worker", "jsonb,uuid", "jsonb"),
    "kill_switch_s13": _f("kill_switch_v1", "operator", "text", "text"),
    "retry_verify_s13": _f("retry_verify_v1", "worker", "uuid,uuid,uuid,uuid", "text"),
    "declare_target_class_s13": _f("declare_target_class_v1", "requester", "uuid,text", "text"),
    # Verification remains a ledger-worker API; an enabled S13 schema must resolve the
    # versioned global-evidence-ID contract without falling back to the legacy function.
    "verify_inconclusive_s13": _f("verify_inconclusive_v1", "worker", "uuid,uuid", "jsonb"),
    # S13 triage requires a physically returned call and immutable attempt-linked evidence;
    # indeterminate calls and conditional conflicts stay held for the witnessed T16 path.
    "resolve_unknown_s13": _f("resolve_unknown_v2", "worker",
                               "uuid,uuid,text,text,text", "text"),
})

# In candidate mode, only versioned candidates and these known read-only legacy calls are allowed.
# Every other registered 001-026 API is a mutation/recovery entry without a complete S13 plan and
# must fail closed instead of silently falling through to legacy SQL.
_S13_LEGACY_READS = frozenset({
    "ledger_head",
    "verify_chain",
    "read_status",
    "read_evidence",
    "read_approval_text",
    "amount_consumed",
    "lifecycle_status",
    "lifecycle_writer_epoch",
    "lifecycle_permit_epoch",
    "lifecycle_checkpoint_suffix",
})

_CAST: Mapping[str, str] = MappingProxyType({"timestamp with time zone": "timestamptz"})


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

    __slots__ = (
        "conn", "_actors", "_lifecycle_fence_enabled", "_private_writer_schema_enabled",
    )

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _SQL_LEDGER_IMMUTABLE_CONFIGURATION and hasattr(self, name):
            raise AttributeError("S13_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        if name in _SQL_LEDGER_IMMUTABLE_CONFIGURATION:
            raise AttributeError("S13_CONFIGURATION_IMMUTABLE")
        object.__delattr__(self, name)

    def __init__(self, conn: asyncpg.Connection, actors: Mapping[str, str | None] | None = None, *,
                 lifecycle_fence_enabled: bool = False,
                 private_writer_schema_enabled: bool = False):
        if (type(lifecycle_fence_enabled) is not bool
                or type(private_writer_schema_enabled) is not bool):
            raise ValueError("S13_CONFIGURATION_INVALID")
        self.conn = conn
        actor_map = dict(actors or {})
        self._actors = MappingProxyType(actor_map)
        self._lifecycle_fence_enabled = lifecycle_fence_enabled
        self._private_writer_schema_enabled = private_writer_schema_enabled is True
        for cls, role in self._actors.items():
            if (type(cls) is not str or cls not in CLASSES
                    or (role is not None
                        and (type(role) is not str or _IDENT.fullmatch(role) is None))):
                raise ValueError("ACTOR_INVALID")

    @property
    def private_writer_schema_enabled(self) -> bool:
        return self._private_writer_schema_enabled

    async def invoke(self, key: str, scope: Scope, *args: Any, as_class: str | None = None) -> Any:
        if key in _PRIVATE_WRITER_SPEC:
            if not self._private_writer_schema_enabled:
                raise LedgerError("S13_NOT_ENABLED")
            fn = _PRIVATE_WRITER_SPEC[key]
        else:
            if (self._private_writer_schema_enabled
                    and key in (SPEC.keys() | _LIFECYCLE_SPEC.keys())
                    and key not in _S13_LEGACY_READS):
                raise LedgerError("S13_ENTRY_NOT_IMPLEMENTED")
            fn = SPEC.get(key) or _LIFECYCLE_SPEC[key]
        if len(args) != len(fn.params):
            raise TypeError(f"{key} takes {len(fn.params)} arguments after scope, got {len(args)}")
        if as_class is None:
            cls = fn.classes[0]
        elif type(as_class) is not str or _IDENT.fullmatch(as_class) is None:
            raise ValueError("ACTOR_INVALID")
        else:
            cls = as_class
        if cls not in fn.classes:
            raise ValueError("ACTOR_INVALID")
        marks = "".join(f",${i + 3}::{_CAST.get(ty, ty)}" for i, ty in enumerate(fn.params))
        call = f"change_ledger.{fn.name}($1,$2{marks})"
        if fn.ret == _TOKEN_ROW:
            sql = f"SELECT * FROM {call}"
        elif fn.ret == "jsonb_composite":
            sql = f"SELECT pg_catalog.to_jsonb({call})"
        else:
            sql = f"SELECT {call}"
        params = [_arg(ty, a) for ty, a in zip(fn.params, args, strict=True)]
        role = self._actors.get(cls)
        if self.conn.is_in_transaction():
            # a nested transaction is only a savepoint: SET LOCAL ROLE / the scope would outlive the call and leak
            # the assumed role into the caller's transaction (008 B6q)
            raise LedgerError("TRANSACTION_ACTIVE")
        try:
            async with self.conn.transaction():
                # S13 lock plans rely on a fresh READ COMMITTED statement snapshot
                # after each advisory fence. Set it as the first SQL command in
                # this owned top-level transaction, before role or scope setup.
                await self.conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
                if await self.conn.fetchval("SHOW transaction_isolation") != "read committed":
                    raise LedgerError("TRANSACTION_ISOLATION_INVALID")
                schema_is_s13 = await self.conn.fetchval(
                    "SELECT pg_catalog.to_regtype("
                    "'change_ledger.private_writer_identity_v1') IS NOT NULL"
                )
                if (type(schema_is_s13) is not bool
                        or schema_is_s13 is not self._private_writer_schema_enabled):
                    raise LedgerError("S13_SCHEMA_MODE_MISMATCH")
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
        if fn.ret in {"jsonb", "jsonb_composite"} and isinstance(value, str):
            return json.loads(value)
        return value

    # ---- requester
    async def propose(self, scope: Scope, change_id: UUID, kind: str, base_fingerprint: str,
                      organization_ref: str, requester: str, request_id: str, payload_digest: str,
                      target_ref: str | None, target_version: str | None,
                      parent_change_id: UUID | None, expires_at: datetime,
                      repair_for: UUID | None = None) -> UUID:
        key = "propose_s13" if self._private_writer_schema_enabled else "propose"
        return await self.invoke(key, scope, change_id, kind, base_fingerprint, organization_ref,
                                 requester, request_id, payload_digest, target_ref, target_version,
                                 parent_change_id, expires_at, repair_for)

    async def validate(self, scope: Scope, change_id: UUID) -> str:
        """008 (B1): no caller flags; the budget pre-check and the duplicate check come from the stored change."""
        key = "validate_s13" if self._private_writer_schema_enabled else "validate"
        return await self.invoke(key, scope, change_id)

    async def declare_budget(self, scope: Scope, change_id: UUID, grant_id: UUID, currency: str, amount: Any,
                             counts_create_update: bool = False, counts_post: bool = False) -> str:
        """008 (B1): the budget inputs claim derives its reservation from (inside the approval digest)."""
        route = "declare_budget_s13" if self._private_writer_schema_enabled else "declare_budget"
        return await self.invoke(route, scope, change_id, grant_id, currency, amount,
                                 counts_create_update, counts_post)

    async def claim(self, scope: Scope, change_id: UUID, key_hash: str | None = None,
                    grant_id: UUID | None = None, amount: Any = None,
                    counts_create_update: bool = False, counts_post: bool = False) -> dict | None:
        if self._private_writer_schema_enabled:
            return await self.invoke("claim_s13", scope, change_id, key_hash, grant_id, amount,
                                     counts_create_update, counts_post, uuid4())
        return await self.invoke("claim", scope, change_id, key_hash, grant_id, amount,
                                 counts_create_update, counts_post)

    async def release_claim(self, scope: Scope, token_id: UUID, as_class: str | None = None) -> str:
        key = "release_claim_s13" if self._private_writer_schema_enabled else "release_claim"
        return await self.invoke(key, scope, token_id, as_class=as_class)

    async def begin_apply(self, scope: Scope, token_id: UUID, call_id: UUID, writer_host: str,
                          onec_session: str, as_class: str | None = None) -> dict | None:
        key = "begin_apply_s13" if self._private_writer_schema_enabled else "begin_apply"
        return await self.invoke(key, scope, token_id, call_id, writer_host, onec_session,
                                 as_class=as_class)

    async def declare_business_key(self, scope: Scope, change_id: UUID, key_hash: str,
                                   override_of: str | None = None,
                                   justification: str | None = None) -> str:
        route = ("declare_business_key_s13" if self._private_writer_schema_enabled
                 else "declare_business_key")
        return await self.invoke(route, scope, change_id, key_hash, override_of,
                                 justification)

    async def declare_target_class(self, scope: Scope, change_id: UUID, target_class: str) -> str:
        route = ("declare_target_class_s13" if self._private_writer_schema_enabled
                 else "declare_target_class")
        return await self.invoke(route, scope, change_id, target_class)

    async def add_epoch_dependency(self, scope: Scope, change_id: UUID, key: str) -> dict:
        route = ("add_epoch_dependency_s13" if self._private_writer_schema_enabled
                 else "add_epoch_dependency")
        return await self.invoke(route, scope, change_id, key)

    # ---- approver
    async def issue_approval_nonce(self, scope: Scope, change_id: UUID) -> str:
        if self._private_writer_schema_enabled:
            nonce = uuid4().hex + uuid4().hex
            return await self.invoke("issue_approval_nonce_s13", scope, change_id, nonce)
        return await self.invoke("issue_approval_nonce", scope, change_id)

    async def approve(self, scope: Scope, change_id: UUID, nonce: str, digest: str) -> UUID:
        if self._private_writer_schema_enabled:
            return await self.invoke("approve_s13", scope, change_id, nonce, digest, uuid4())
        return await self.invoke("approve", scope, change_id, nonce, digest)

    async def reject(self, scope: Scope, change_id: UUID, nonce: str) -> str:
        if self._private_writer_schema_enabled:
            return await self.invoke("reject_s13", scope, change_id, nonce, uuid4())
        return await self.invoke("reject", scope, change_id, nonce)

    async def bind_duplicate_override(self, scope: Scope, change_id: UUID, override_digest: str) -> bool:
        route = ("bind_duplicate_override_s13" if self._private_writer_schema_enabled
                 else "bind_duplicate_override")
        return await self.invoke(route, scope, change_id, override_digest)

    # ---- permit gate (worker identity) and writer
    async def ledger_head(self, scope: Scope, as_class: str | None = "worker") -> dict:
        return await self.invoke("ledger_head", scope, as_class=as_class)

    async def record_checkpoint(self, scope: Scope, seq: int, head_hash: str, sink_kind: str,
                                sink_id: str, key_id: str, signature: str, signed_at: datetime,
                                read_back: bool, as_class: str | None = "checkpoint") -> int:
        return await self.invoke("record_checkpoint", scope, seq, head_hash, sink_kind, sink_id, key_id,
                                 signature, signed_at, read_back, as_class=as_class)

    async def record_checkpoint_s13(self, scope: Scope, seq: int, head_hash: str, sink_kind: str,
                                    sink_id: str, key_id: str, signature: str, signed_at: datetime,
                                    read_back: bool, as_class: str | None = "checkpoint") -> int:
        return await self.invoke("record_checkpoint_s13", scope, seq, head_hash, sink_kind, sink_id,
                                 key_id, signature, signed_at, read_back, as_class=as_class)

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

    async def dispatch_intent_for_call(self, scope: Scope, call_id: UUID,
                                       as_class: str = "worker") -> dict | None:
        value = await self.invoke("dispatch_intent_for_call", scope, call_id, as_class=as_class)
        if value is not None and not isinstance(value, dict):
            raise LedgerError("S13_STORE_OUTCOME_UNKNOWN")
        return value

    async def permit_binding_for_intent(self, scope: Scope, dispatch_intent_id: UUID,
                                        as_class: str = "worker") -> dict | None:
        value = await self.invoke("permit_binding_for_intent", scope, dispatch_intent_id,
                                  as_class=as_class)
        if value is not None and not isinstance(value, dict):
            raise LedgerError("S13_STORE_OUTCOME_UNKNOWN")
        return value

    async def issue_permit_s13(self, scope: Scope, change_id: UUID, generation: int,
                               dispatch_intent_id: UUID, permit_id: UUID,
                               signer_key_id: str, signer_key_version: str,
                               signature: str) -> dict:
        value = await self.invoke("issue_permit_s13", scope, change_id, generation,
                                  dispatch_intent_id, permit_id, signer_key_id,
                                  signer_key_version, signature, as_class="worker")
        if not isinstance(value, dict):
            raise LedgerError("S13_STORE_OUTCOME_UNKNOWN")
        return value

    async def attach_permit_signature(self, scope: Scope, change_id: UUID, generation: int,
                                      key_id: str, signature: str,
                                      as_class: str | None = "checkpoint") -> None:
        key = "attach_permit_signature_s13" if self._private_writer_schema_enabled else "attach_permit_signature"
        await self.invoke(key, scope, change_id, generation, key_id, signature, as_class=as_class)

    async def record_call(self, scope: Scope, change_id: UUID, generation: int, call_id: UUID) -> bool:
        return await self.invoke("record_call", scope, change_id, generation, call_id)

    async def cancel_permit(self, scope: Scope, change_id: UUID, generation: int,
                            as_class: str | None = None) -> bool:
        key = "cancel_permit_s13" if self._private_writer_schema_enabled else "cancel_permit"
        return await self.invoke(key, scope, change_id, generation, as_class=as_class)

    async def complete_lock_busy(self, scope: Scope, change_id: UUID, generation: int,
                                 completion: UUID | None, params: dict | None = None) -> str:
        return await self.invoke("complete_lock_busy", scope, change_id, generation, completion,
                                 params if params is not None else {})

    async def renew_writer_lease(self, scope: Scope, change_id: UUID, generation: int,
                                 ttl_seconds: int = 300) -> datetime:
        key = "renew_writer_lease_s13" if self._private_writer_schema_enabled else "renew_writer_lease"
        return await self.invoke(key, scope, change_id, generation, ttl_seconds)

    async def fence_check(self, scope: Scope, change_id: UUID, generation: int, call_id: UUID) -> dict:
        """Retain the legacy preflight without treating it as S13 COM-entry authority.

        This short transaction cannot fence a later physical COM call. S13 admission and the
        committed mark-invoking transition are the only supported writer-entry path.
        """
        if self._private_writer_schema_enabled:
            raise LedgerError("S13_COM_ENTRY_GUARD_REQUIRED")
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
        """Retain the legacy epoch query without treating it as S13 call authority.

        Its transaction ends before the external call, so it cannot fence a later physical COM
        entry. S13 requires the process-bound one-way entry guard instead.
        """
        if self._private_writer_schema_enabled:
            raise LedgerError("S13_COM_ENTRY_GUARD_REQUIRED")
        return await self.invoke("lifecycle_writer_epoch", scope, change_id, generation,
                                 expected_epoch)

    async def observe_target(self, scope: Scope, token_id: UUID, fingerprint: str,
                             target_class: str) -> bool:
        key = "observe_target_s13" if self._private_writer_schema_enabled else "observe_target"
        return await self.invoke(key, scope, token_id, fingerprint, target_class)

    async def complete_signed(self, scope: Scope, change_id: UUID, generation: int, outcome: str,
                              completion: UUID | None) -> str:
        return await self.invoke("complete_signed", scope, change_id, generation, outcome, completion)

    # ---- worker
    async def recover_sweep(self, scope: Scope, params: dict | None = None) -> Any:
        """Keep the legacy return contracts unless the fail-closed S13 route is selected."""
        if self._private_writer_schema_enabled:
            report = await self.invoke("recover_sweep_s13", scope, params or {}, uuid4())
            if not isinstance(report, dict):
                raise LedgerError("S13_STORE_OUTCOME_UNKNOWN")
            return report
        if params is None:
            return await self.invoke("recover_sweep", scope)
        return await self.invoke("recover_sweep_params", scope, params)

    async def verify_inconclusive(self, scope: Scope, change_id: UUID, observation: UUID) -> dict:
        key = "verify_inconclusive_s13" if self._private_writer_schema_enabled else "verify_inconclusive"
        return await self.invoke(key, scope, change_id, observation)

    async def retry_verify(self, scope: Scope, change_id: UUID, field: UUID | None,
                           movement: UUID | None, version: UUID | None) -> str:
        if self._private_writer_schema_enabled:
            return await self.invoke("retry_verify_s13", scope, change_id, field, movement, version)
        return await self.invoke("retry_verify", scope, change_id, field, movement, version)

    async def check_anchor(self, scope: Scope, ext_seq: int, ext_head_hash: str) -> dict:
        key = "check_anchor_s13" if self._private_writer_schema_enabled else "check_anchor"
        return await self.invoke(key, scope, ext_seq, ext_head_hash)

    async def verify_chain(self, scope: Scope, as_class: str | None = None) -> dict:
        return await self.invoke("verify_chain", scope, as_class=as_class)

    async def revoke_stale(self, scope: Scope) -> int:
        key = "revoke_stale_s13" if self._private_writer_schema_enabled else "revoke_stale"
        return await self.invoke(key, scope)

    async def record_evidence(self, scope: Scope, change_id: UUID, kind: str, content_hash: str,
                              observed_at: datetime, content: dict | None, key_id: str,
                              binding_hash: str, signature: str, generation: int | None,
                              call_id: UUID | None, as_class: str | None = None) -> UUID:
        if self._private_writer_schema_enabled:
            return await self.invoke("record_evidence_s13", scope, change_id, kind, content_hash,
                                     observed_at, content, key_id, binding_hash, signature,
                                     generation, call_id, uuid4(), as_class=as_class)
        return await self.invoke("record_evidence", scope, change_id, kind, content_hash, observed_at,
                                 content, key_id, binding_hash, signature, generation, call_id,
                                 as_class=as_class)

    async def verify_signed(self, scope: Scope, change_id: UUID, field: UUID | None,
                            movement: UUID | None, version: UUID | None) -> str:
        return await self.invoke("verify_signed", scope, change_id, field, movement, version)

    async def resolve_unknown_signed(self, scope: Scope, change_id: UUID, observation: UUID,
                                     completion: UUID | None, found: bool | None,
                                     attributed: bool = False) -> str:
        if self._private_writer_schema_enabled:
            raise LedgerError("S13_ENTRY_REQUIRES_EVIDENCE_REFS")
        return await self.invoke("resolve_unknown_signed", scope, change_id, observation, completion,
                                 found, attributed)

    async def resolve_unknown_s13(self, scope: Scope, change_id: UUID, dispatch_cas_id: UUID,
                                  receipt_ref: str, completion_ref: str,
                                  outcome_ref: str) -> str:
        """Enter T16 triage only after exact returned-call terminality is evidenced."""
        if not self._private_writer_schema_enabled:
            raise LedgerError("S13_SCHEMA_DISABLED")
        if any(type(value) is not UUID or value.int == 0
               for value in (change_id, dispatch_cas_id)):
            raise LedgerError("SCHEMA_INVALID")
        refs = (receipt_ref, completion_ref, outcome_ref)
        if any(not isinstance(ref, str) or not ref or ref != ref.strip() for ref in refs):
            raise LedgerError("SCHEMA_INVALID")
        if len(set(refs)) != len(refs):
            raise LedgerError("SCHEMA_INVALID")
        value = await self.invoke("resolve_unknown_s13", scope, change_id, dispatch_cas_id,
                                  receipt_ref, completion_ref, outcome_ref)
        if value not in {"APPLIED", "FAILED_APPLY", "TRIAGE_REQUIRED"}:
            raise LedgerError("S13_STORE_OUTCOME_UNKNOWN")
        return value

    # ---- operator
    async def witness_cosign_signed(self, scope: Scope, change_id: UUID, completion: UUID) -> UUID:
        key = ("witness_cosign_signed_s13" if self._private_writer_schema_enabled
               else "witness_cosign_signed")
        return await self.invoke(key, scope, change_id, completion)

    async def operator_resolve(self, scope: Scope, change_id: UUID, cosign_id: UUID | None,
                               present: bool, attributed: bool) -> str:
        return await self.invoke("operator_resolve", scope, change_id, cosign_id, present, attributed)

    async def operator_resolve_s13(self, scope: Scope, change_id: UUID, dispatch_cas_id: UUID,
                                   cosign_id: UUID, receipt_ref: str, completion_ref: str,
                                   outcome_ref: str, challenge_ref: str | None = None,
                                   read_attestation_ref: str | None = None) -> dict:
        """Resolve T16 from immutable evidence and return the committed event identity.

        Checkpointing and read-back must happen after this one SQL transaction commits. The
        caller must keep the ANCHOR_GAP stop-effects gate active until that exact event is
        durably checkpointed and read back.
        """
        if not self._private_writer_schema_enabled:
            raise LedgerError("S13_SCHEMA_DISABLED")
        if any(type(value) is not UUID or value.int == 0
               for value in (change_id, dispatch_cas_id, cosign_id)):
            raise LedgerError("SCHEMA_INVALID")
        refs = (receipt_ref, completion_ref, outcome_ref)
        if any(not isinstance(ref, str) or not ref or ref != ref.strip() for ref in refs):
            raise LedgerError("SCHEMA_INVALID")
        if (challenge_ref is None) != (read_attestation_ref is None):
            raise LedgerError("SCHEMA_INVALID")
        if challenge_ref is not None and (
                not isinstance(challenge_ref, str) or not challenge_ref
                or challenge_ref != challenge_ref.strip()
                or not isinstance(read_attestation_ref, str) or not read_attestation_ref
                or read_attestation_ref != read_attestation_ref.strip()):
            raise LedgerError("SCHEMA_INVALID")
        value = await self.invoke("operator_resolve_s13", scope, change_id, dispatch_cas_id,
                                  cosign_id, receipt_ref, completion_ref, outcome_ref,
                                  challenge_ref, read_attestation_ref)
        if (not isinstance(value, dict) or value.get("execution_state") not in {
                "APPLIED", "FAILED_APPLY"} or value.get("checkpoint_required") is not True
                or not isinstance(value.get("event_id"), str)):
            raise LedgerError("S13_STORE_OUTCOME_UNKNOWN")
        try:
            event_id_raw = value["event_id"]
            event_id = UUID(event_id_raw)
        except (ValueError, TypeError, AttributeError) as exc:
            raise LedgerError("S13_STORE_OUTCOME_UNKNOWN") from exc
        event_seq = value.get("event_seq")
        event_hash = value.get("event_hash")
        hold_id = value.get("hold_id")
        checkpoint_hold_ids = value.get("checkpoint_hold_ids")
        try:
            call_hold = UUID(hold_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise LedgerError("S13_STORE_OUTCOME_UNKNOWN") from exc
        if (str(event_id) != event_id_raw or str(call_hold) != hold_id
                or event_id.int == 0 or call_hold.int == 0
                or type(event_seq) is not int or event_seq < 1
                or not isinstance(event_hash, str) or len(event_hash) != 64
                or any(char not in "0123456789abcdef" for char in event_hash)
                or type(checkpoint_hold_ids) is not list or not checkpoint_hold_ids):
            raise LedgerError("S13_STORE_OUTCOME_UNKNOWN")
        try:
            if any(type(item) is not str for item in checkpoint_hold_ids):
                raise ValueError("hold UUID must be canonical text")
            holds = [UUID(item) for item in checkpoint_hold_ids]
        except (ValueError, TypeError, AttributeError) as exc:
            raise LedgerError("S13_STORE_OUTCOME_UNKNOWN") from exc
        if (any(hold.int == 0 for hold in holds)
                or any(str(hold) != raw for hold, raw in zip(holds, checkpoint_hold_ids, strict=True))
                or len(set(holds)) != len(holds)
                or call_hold in holds):
            raise LedgerError("S13_STORE_OUTCOME_UNKNOWN")
        return value

    async def operator_close_failed_verify(self, scope: Scope, change_id: UUID,
                                           cosign_id: UUID | None, effect_present: bool) -> str:
        key = ("operator_close_failed_verify_s13" if self._private_writer_schema_enabled
               else "operator_close_failed_verify")
        return await self.invoke(key, scope, change_id, cosign_id, effect_present)

    async def release_hold(self, scope: Scope, hold_id: UUID, release_evidence: dict | None) -> datetime:
        key = "release_hold_s13" if self._private_writer_schema_enabled else "release_hold"
        return await self.invoke(key, scope, hold_id, release_evidence)

    async def anchor_gap_cosign(self, scope: Scope, hold_id: UUID, evidence: dict) -> UUID:
        return await self.invoke("anchor_gap_cosign_s13", scope, hold_id, evidence)

    async def kill_switch(self, scope: Scope, mode: str) -> str:
        key = "kill_switch_s13" if self._private_writer_schema_enabled else "kill_switch"
        return await self.invoke(key, scope, mode)

    async def budget_revoke(self, scope: Scope, grant_id: UUID) -> str:
        route = "budget_revoke_s13" if self._private_writer_schema_enabled else "budget_revoke"
        return await self.invoke(route, scope, grant_id)

    async def budget_admin(self, scope: Scope, grant_id: UUID | None, currency: str, amount_limit: Any,
                           count_limit: int, post_count_limit: int, window_start: datetime,
                           window_end: datetime) -> UUID:
        route = "budget_admin_s13" if self._private_writer_schema_enabled else "budget_admin"
        return await self.invoke(route, scope, grant_id, currency, amount_limit, count_limit,
                                 post_count_limit, window_start, window_end)

    async def declare_anchor_gap(self, scope: Scope, base: str | None, detail: dict | None,
                                 as_class: str | None = None) -> int:
        key = "declare_anchor_gap_s13" if self._private_writer_schema_enabled else "declare_anchor_gap"
        return await self.invoke(key, scope, base, detail, as_class=as_class)

    async def declare_unclean_restart(self, scope: Scope, base: str | None, detail: dict | None,
                                      as_class: str | None = None) -> int:
        key = "declare_unclean_restart_s13" if self._private_writer_schema_enabled else "declare_unclean_restart"
        return await self.invoke(key, scope, base, detail, as_class=as_class)

    async def revoke_change(self, scope: Scope, change_id: UUID, cause: str,
                            as_class: str | None = None) -> str:
        key = "revoke_change_s13" if self._private_writer_schema_enabled else "revoke_change"
        return await self.invoke(key, scope, change_id, cause, as_class=as_class)

    async def register_principal(self, scope: Scope, principal: str, person_id: str | None,
                                 capabilities: list[str], active: bool = True) -> int:
        route = ("register_principal_s13" if self._private_writer_schema_enabled
                 else "register_principal")
        return await self.invoke(route, scope, principal, person_id, capabilities, active)

    async def enforce_registry(self, scope: Scope) -> bool:
        route = "enforce_registry_s13" if self._private_writer_schema_enabled else "enforce_registry"
        return await self.invoke(route, scope)

    async def register_target(self, scope: Scope, base: str, org: str, target_class: str,
                              status: str = "ACTIVE", permission_expires_at: datetime | None = None) -> int:
        route = ("register_target_s13" if self._private_writer_schema_enabled else "register_target")
        return await self.invoke(route, scope, base, org, target_class, status, permission_expires_at)

    async def register_verifier_key(self, scope: Scope, key_id: str, role_name: str,
                                    key_material: str) -> None:
        route = ("register_verifier_key_s13" if self._private_writer_schema_enabled
                 else "register_verifier_key")
        await self.invoke(route, scope, key_id, role_name, key_material)

    async def revoke_verifier_key(self, scope: Scope, key_id: str) -> None:
        route = ("revoke_verifier_key_s13" if self._private_writer_schema_enabled
                 else "revoke_verifier_key")
        await self.invoke(route, scope, key_id)

    async def approve_registry_change(self, scope: Scope, change_id: UUID, digest: str) -> dict:
        route = ("approve_registry_change_s13" if self._private_writer_schema_enabled
                 else "approve_registry_change")
        return await self.invoke(route, scope, change_id, digest)

    async def propose_registry_change(self, scope: Scope, kind: str, params: dict) -> UUID:
        if self._private_writer_schema_enabled:
            return await self.invoke("propose_registry_change_s13", scope, uuid4(), kind, params)
        return await self.invoke("propose_registry_change", scope, kind, params)

    async def bump_epoch(self, scope: Scope, key: str) -> int:
        route = "bump_epoch_s13" if self._private_writer_schema_enabled else "bump_epoch"
        return await self.invoke(route, scope, key)

    async def set_sweep_policy(self, scope: Scope, params: dict) -> dict:
        """Set bounded operator sweep-policy overrides for one tenant/company scope."""
        route = "set_sweep_policy_s13" if self._private_writer_schema_enabled else "set_sweep_policy"
        return await self.invoke(route, scope, params)

    # ---- 009 S12-APPROVAL-2
    async def store_approval_text(self, scope: Scope, change_id: UUID, nonce: str, text: str) -> str:
        """Store the canonical approval text (change.proposal.approval_canonical_text) for one issued nonce; returns
        its digest (sha256 of the stored UTF-8 bytes). The ledger refuses a text that differs from its own state."""
        if self._private_writer_schema_enabled:
            return await self.invoke("store_approval_text_s13", scope, change_id, nonce, text, uuid4())
        return await self.invoke("store_approval_text", scope, change_id, nonce, text)

    async def read_approval_text(self, scope: Scope, change_id: UUID, as_class: str | None = None) -> str | None:
        return await self.invoke("read_approval_text", scope, change_id, as_class=as_class)

    async def verify_dispatch_payload(self, scope: Scope, change_id: UUID, generation: int,
                                      payload_text: str | None, as_class: str | None = None) -> bool:
        """Check canonical JSON text against the approved payload and persist its distinct wire-byte SHA-256.

        ``None`` represents the canonical ``{}`` bytes for operations without a payload. The typed-payload digest
        remains the approval identity; the byte digest binds the clone receipt. Non-canonical text is refused.
        """
        if self._private_writer_schema_enabled:
            return await self.invoke("verify_dispatch_payload_s13", scope, change_id, generation,
                                     payload_text, uuid4(), as_class=as_class)
        return await self.invoke("verify_dispatch_payload", scope, change_id, generation, payload_text,
                                 as_class=as_class)

    async def require_dispatch_receipt(self, scope: Scope, change_id: UUID, generation: int,
                                       as_class: str | None = None) -> None:
        """Require a clone receipt before this generation can complete as APPLIED (opt-in per generation)."""
        route = "require_dispatch_receipt_s13" if self._private_writer_schema_enabled else "require_dispatch_receipt"
        await self.invoke(route, scope, change_id, generation, as_class=as_class)

    async def record_dispatch_receipt(self, scope: Scope, change_id: UUID, generation: int,
                                      key_id: str, received_payload_sha256: str, new_version: str,
                                      signature: str, as_class: str | None = None) -> UUID:
        """Persist the clone-produced receipt; SQL verifies its signature and verified wire digest."""
        if self._private_writer_schema_enabled:
            return await self.invoke("record_dispatch_receipt_s13", scope, change_id, generation, key_id,
                                     received_payload_sha256, new_version, signature, uuid4(),
                                     as_class=as_class)
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
