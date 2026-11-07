"""Least-privilege PostgreSQL adapter for the accepted-head promotion service.

The actor is derived by the authenticated Admin API from the verified OAuth subject.  Every
operation sets that actor's provisioned NOLOGIN database role and enters the explicit living
scope in the same transaction; role membership and ``living.set_scope`` are the database-side
authorization boundary.  Request fields never select the database actor.
"""
from __future__ import annotations

import hashlib
import re
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg

from .promotion import AttestationView
from .ports import AcceptanceView, HeadView, PortError, Scope, check_scope_type

_ACTOR_ROLE = re.compile(r"r2p_[a-f0-9]{59}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]+\Z")
_SQLSTATE = {
    "23514": "CHECK_VIOLATION",
    "23505": "UNIQUE_VIOLATION",
    "23503": "FK_VIOLATION",
    "42501": "DATABASE_PRIVILEGE_UNAVAILABLE",
    "42704": "ROLE_NOT_FOUND",
    "3F000": "SCHEMA_NOT_FOUND",
    "42P01": "RELATION_NOT_FOUND",
    "42883": "FUNCTION_NOT_FOUND",
}


def actor_role_for_subject(subject: str) -> str:
    """Stable, non-reversible PostgreSQL role name for a verified OAuth subject."""
    if not isinstance(subject, str) or not subject or len(subject) > 4096:
        raise PortError("INVALID_ARGUMENT", "authenticated subject required")
    digest = hashlib.sha256(subject.encode("utf-8", errors="strict")).hexdigest()
    return "r2p_" + digest[:59]


def _port_error(exc: asyncpg.PostgresError) -> PortError:
    message = (str(exc).splitlines() or [""])[0]
    head = message.split(":", 1)[0].strip()
    if _CODE.fullmatch(head):
        return PortError(head, message[:300])
    state = getattr(exc, "sqlstate", None)
    return PortError(_SQLSTATE.get(state, "SQL_" + str(state or "UNKNOWN")), message[:300])


class PromotionPostgresPort:
    """Concrete head/CAS port and attestation reader for one authenticated actor."""

    def __init__(self, pool: asyncpg.Pool, actor_role: str, company_id: str):
        if not isinstance(pool, asyncpg.Pool) or not isinstance(actor_role, str) \
                or not _ACTOR_ROLE.fullmatch(actor_role) or not isinstance(company_id, str) \
                or not company_id:
            raise ValueError("promotion port configuration invalid")
        self._pool = pool
        self.actor_role = actor_role
        self.company_id = company_id

    @asynccontextmanager
    async def _scoped(self, actor: str, scope: Scope):
        check_scope_type(scope)
        if actor != self.actor_role:
            raise PortError("PERMISSION_DENIED", "actor binding mismatch")
        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    # Identifier is a strict, locally generated hash-based role, never request text.
                    await conn.execute(f'SET LOCAL ROLE "{self.actor_role}"')
                    await conn.fetchval(
                        "SELECT living.set_scope($1,$2,$3)",
                        scope.tenant_id,
                        scope.source_id,
                        self.company_id,
                    )
                    yield conn
        except asyncpg.PostgresError as exc:
            raise _port_error(exc) from None

    async def authorize_scope(self, scope: Scope, company_id: str) -> None:
        """Check current role/source/company authorization before any evidence access."""
        if company_id != self.company_id:
            raise PortError("PERMISSION_DENIED", "company scope mismatch")
        async with self._scoped(self.actor_role, scope) as conn:
            promoter = await conn.fetchval(
                "SELECT pg_has_role(current_user::name, 'living_promoter'::name, 'USAGE')"
            )
            if promoter is not True:
                raise PortError("NOT_A_PROMOTER")

    async def get_revision_digest(self, scope: Scope, revision_id: UUID) -> str | None:
        async with self._scoped(self.actor_role, scope) as conn:
            row = await conn.fetchrow(
                "SELECT digest FROM living.observations "
                "WHERE tenant_id=$1 AND source_id=$2 AND revision_id=$3 AND kind='OBSERVED'",
                scope.tenant_id,
                scope.source_id,
                revision_id,
            )
        return row["digest"] if row is not None else None

    async def find_attestation(self, scope: Scope, revision_id: UUID,
                               evidence_ref: str) -> AttestationView | None:
        async with self._scoped(self.actor_role, scope) as conn:
            row = await conn.fetchrow(
                "SELECT attestation_id, revision_id, proposer_subject, observer_subject, "
                "evidence_ref, evidence_digest, decision, expires_at, revoked_at "
                "FROM living.attestations WHERE tenant_id=$1 AND source_id=$2 "
                "AND revision_id=$3 AND evidence_ref=$4",
                scope.tenant_id,
                scope.source_id,
                revision_id,
                evidence_ref,
            )
        if row is None:
            return None
        if row["expires_at"] is None:
            raise PortError("EVIDENCE_EXPIRED")
        return AttestationView(
            row["attestation_id"], row["revision_id"], row["proposer_subject"],
            row["observer_subject"], row["evidence_ref"], row["evidence_digest"],
            row["decision"], row["expires_at"], row["revoked_at"],
        )

    async def is_trusted_reviewer(self, scope: Scope, subject: str) -> bool:
        async with self._scoped(self.actor_role, scope) as conn:
            return bool(await conn.fetchval(
                "SELECT living.is_trusted_reviewer($1,$2,$3)",
                scope.tenant_id,
                scope.source_id,
                subject,
            ))

    async def promote_head(self, actor: str, scope: Scope, model_key: str,
                           expected_version: int, new_revision: UUID,
                           acceptance_id: UUID, evidence_ref: str) -> int:
        async with self._scoped(actor, scope) as conn:
            value = await conn.fetchval(
                "SELECT living.promote_head($1,$2,$3,$4,$5::uuid,$6::uuid,$7)",
                scope.tenant_id,
                scope.source_id,
                model_key,
                expected_version,
                new_revision,
                acceptance_id,
                evidence_ref,
            )
        return value

    async def get_head(self, actor: str, scope: Scope, model_key: str) -> HeadView | None:
        async with self._scoped(actor, scope) as conn:
            row = await conn.fetchrow(
                "SELECT revision_id, version FROM living.accepted_heads "
                "WHERE tenant_id=$1 AND source_id=$2 AND model_key=$3",
                scope.tenant_id,
                scope.source_id,
                model_key,
            )
        return HeadView(model_key, row["revision_id"], row["version"]) if row else None

    async def list_acceptances(self, actor: str, scope: Scope) -> tuple[AcceptanceView, ...]:
        async with self._scoped(actor, scope) as conn:
            rows = await conn.fetch(
                "SELECT acceptance_id, model_key, from_version, to_version, accepted_revision, "
                "approver_subject, independent_evidence_ref FROM living.acceptance_events "
                "WHERE tenant_id=$1 AND source_id=$2 ORDER BY model_key,to_version",
                scope.tenant_id,
                scope.source_id,
            )
        return tuple(AcceptanceView(
            row["acceptance_id"], row["model_key"], row["from_version"], row["to_version"],
            row["accepted_revision"], row["approver_subject"],
            row["independent_evidence_ref"],
        ) for row in rows)
