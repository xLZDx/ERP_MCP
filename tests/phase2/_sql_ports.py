"""Thin SQL adapter: the Phase 2 living-registry ports implemented by the real ``living.*`` functions.

Used only by tests/phase2/test_ports_contract.py. Every scoped call runs in one transaction:
``SET LOCAL ROLE <actor>``, ``living.set_scope`` and then the function itself, so a rejected call
rolls everything back exactly as in production. SQL errors become ``PortError(code)`` where the
code is the RAISE EXCEPTION text (constraint/permission errors map by SQLSTATE).
"""
import json
import re
from contextlib import asynccontextmanager

import asyncpg

from business_ai_gateway.phase2.ports import (
    AcceptanceView,
    CommitResult,
    CursorView,
    EffectiveRow,
    HeadView,
    JobView,
    KnownRow,
    Observation,
    OutboxRow,
    PortError,
)

_CODE = re.compile(r"[A-Z][A-Z0-9_]+")
_IDENT = re.compile(r"[a-z][a-z0-9_]*")
_SQLSTATE = {"23514": "CHECK_VIOLATION", "23505": "UNIQUE_VIOLATION", "23503": "FK_VIOLATION",
             "42501": "PERMISSION_DENIED"}


def to_port_error(e: asyncpg.PostgresError) -> PortError:
    msg = (str(e).splitlines() or [""])[0]
    head = msg.split(":")[0].strip()
    if _CODE.fullmatch(head):
        return PortError(head, msg)
    return PortError(_SQLSTATE.get(e.sqlstate, "SQL_" + str(e.sqlstate)), msg)


def _obs(r) -> Observation:
    return Observation(r["observation_id"], r["object_id"], r["revision_id"], r["kind"],
                       r["digest"], r["source_effective_at"], r["observed_at"], r["recorded_at"],
                       r["ingest_seq"], r["supersedes"])


def _outbox(r) -> OutboxRow:
    content = r["content"]
    return OutboxRow(r["seq"], r["connection_id"], r["event_id"], r["event_digest"],
                     json.loads(content) if isinstance(content, str) else content, r["status"],
                     r["attempts"], r["lease_owner"], r["lease_until"], r["claim_generation"])


def _job(r) -> JobView:
    return JobView(r["job_id"], r["state"], r["lease_owner"], r["lease_until"], r["fence"],
                   r["attempt"], r["max_attempts"], r["next_run_at"], r["last_error"],
                   r["scope_epoch"])


class SqlLiving:
    """LedgerPort + JobQueuePort + CursorOutboxPort + HeadAttestationPort over asyncpg."""

    def __init__(self, conn: asyncpg.Connection):
        self.conn = conn  # superuser connection of a throwaway, migrated and seeded database

    # ------------------------------------------------------------------ plumbing
    @asynccontextmanager
    async def _scoped(self, actor, scope):
        assert _IDENT.fullmatch(actor), actor
        async with self.conn.transaction():
            await self.conn.execute(f'SET LOCAL ROLE "{actor}"')
            await self.conn.fetchval("SELECT living.set_scope($1,$2,$3)", scope.tenant_id,
                                     scope.source_id, None)
            yield

    async def _val(self, actor, scope, sql, *args):
        try:
            async with self._scoped(actor, scope):
                return await self.conn.fetchval(sql, scope.tenant_id, scope.source_id, *args)
        except asyncpg.PostgresError as e:
            raise to_port_error(e) from None

    async def _rows(self, actor, scope, sql, *args):
        try:
            async with self._scoped(actor, scope):
                return await self.conn.fetch(sql, scope.tenant_id, scope.source_id, *args)
        except asyncpg.PostgresError as e:
            raise to_port_error(e) from None

    async def _admin(self, sql, *args):
        try:
            async with self.conn.transaction():
                return await self.conn.fetchval(sql, *args)
        except asyncpg.PostgresError as e:
            raise to_port_error(e) from None

    # ------------------------------------------------------------------ ledger
    async def now(self):
        return await self.conn.fetchval("SELECT clock_timestamp()")

    async def scope_epoch(self, scope):
        return await self.conn.fetchval(
            "SELECT scope_epoch FROM living.sources WHERE tenant_id=$1 AND source_id=$2",
            scope.tenant_id, scope.source_id)

    async def ingest_observation(self, actor, scope, observation_id, object_id, revision_id, kind,
                                 digest, source_effective_at, observed_at, supersedes=None,
                                 provenance=None):
        return await self._val(
            actor, scope,
            "SELECT living.ingest_observation($1,$2,$3::uuid,$4,$5::uuid,$6,$7,$8::timestamptz,"
            "$9::timestamptz,$10::uuid,$11::jsonb)",
            observation_id, object_id, revision_id, kind, digest, source_effective_at, observed_at,
            supersedes, json.dumps({} if provenance is None else provenance))

    async def as_known_at(self, actor, scope, k):
        rows = await self._rows(actor, scope, "SELECT * FROM living.as_known_at($1,$2,$3)", k)
        return tuple(KnownRow(_obs(r), r["available"], r["latest_kind"], r["revoked"])
                     for r in rows)

    async def as_effective_at(self, actor, scope, valid_at, k):
        rows = await self._rows(actor, scope,
                                "SELECT * FROM living.as_effective_at($1,$2,$3,$4)", valid_at, k)
        return tuple(EffectiveRow(_obs(r), r["effective_unknown"], r["revoked"]) for r in rows)

    # ------------------------------------------------------------------ jobs
    async def enqueue_job(self, actor, scope, job_id, job_kind, request_digest, idempotency_key,
                          payload=None):
        return await self._val(
            actor, scope, "SELECT living.enqueue_job($1,$2,$3::uuid,$4,$5,$6,$7::jsonb)",
            job_id, job_kind, request_digest, idempotency_key,
            json.dumps({} if payload is None else payload))

    async def acquire_job(self, actor, scope, job_id, worker, lease_seconds):
        return await self._val(actor, scope, "SELECT living.acquire_job($1,$2,$3::uuid,$4,$5)",
                               job_id, worker, lease_seconds)

    async def renew_lease(self, actor, scope, job_id, worker, fence, lease_seconds):
        return await self._val(
            actor, scope, "SELECT living.renew_lease($1,$2,$3::uuid,$4,$5,$6)",
            job_id, worker, fence, lease_seconds)

    async def finish_job(self, actor, scope, job_id, worker, fence, completed_state, error=None):
        await self._val(actor, scope, "SELECT living.finish_job($1,$2,$3::uuid,$4,$5,$6,$7)",
                        job_id, worker, fence, completed_state, error)

    async def reap_expired_jobs(self, actor, scope):
        return await self._val(actor, scope, "SELECT living.reap_expired_jobs($1,$2)")

    async def get_job(self, actor, scope, job_id):
        rows = await self._rows(
            actor, scope, "SELECT * FROM living.jobs WHERE tenant_id=$1 AND source_id=$2 "
            "AND job_id=$3::uuid", job_id)
        return _job(rows[0]) if rows else None

    # ------------------------------------------------------------------ cursor + outbox
    async def create_cursor(self, actor, scope, connection_id, initial_cursor):
        return await self._val(actor, scope, "SELECT living.create_cursor($1,$2,$3,$4)",
                               connection_id, initial_cursor)

    async def commit_cursor_page(self, actor, scope, connection_id, job_id, worker, fence,
                                 prior_cursor, prior_version, expected_epoch, new_cursor, events):
        notices: list[str] = []

        def listener(_conn, message):
            notices.append(getattr(message, "message", str(message)))

        self.conn.add_log_listener(listener)
        try:
            version = await self._val(
                actor, scope,
                "SELECT living.commit_cursor_page($1,$2,$3,$4::uuid,$5,$6,$7,$8,$9,$10,$11::jsonb)",
                connection_id, job_id, worker, fence, prior_cursor, prior_version, expected_epoch,
                new_cursor, None if events is None else json.dumps(events))
        finally:
            self.conn.remove_log_listener(listener)
        return CommitResult(version, any("CURSOR_ALREADY_APPLIED" in n for n in notices))

    async def get_cursor(self, actor, scope, connection_id):
        rows = await self._rows(
            actor, scope, "SELECT * FROM living.cursors WHERE tenant_id=$1 AND source_id=$2 "
            "AND connection_id=$3", connection_id)
        if not rows:
            return None
        r = rows[0]
        return CursorView(r["connection_id"], r["cursor_value"], r["version"], r["scope_epoch"],
                          r["last_page_digest"])

    async def claim_outbox(self, actor, scope, limit, lease_seconds, max_attempts=5):
        rows = await self._rows(actor, scope, "SELECT * FROM living.claim_outbox($1,$2,$3,$4,$5)",
                                limit, lease_seconds, max_attempts)
        return tuple(sorted((_outbox(r) for r in rows), key=lambda o: o.seq))

    async def finish_outbox(self, actor, scope, connection_id, event_id, generation, delivered,
                            max_attempts=5):
        await self._val(actor, scope, "SELECT living.finish_outbox($1,$2,$3,$4,$5,$6,$7)",
                        connection_id, event_id, generation, delivered, max_attempts)

    async def list_outbox(self, actor, scope):
        rows = await self._rows(
            actor, scope, "SELECT * FROM living.outbox WHERE tenant_id=$1 AND source_id=$2 "
            "ORDER BY seq")
        return tuple(_outbox(r) for r in rows)

    # ------------------------------------------------------------------ heads + attestations
    async def create_head(self, actor, scope, model_key):
        return await self._val(actor, scope, "SELECT living.create_head($1,$2,$3)", model_key)

    async def promote_head(self, actor, scope, model_key, expected_version, new_revision,
                           acceptance_id, evidence_ref):
        return await self._val(
            actor, scope, "SELECT living.promote_head($1,$2,$3,$4,$5::uuid,$6::uuid,$7)",
            model_key, expected_version, new_revision, acceptance_id, evidence_ref)

    async def record_attestation(self, actor, scope, attestation_id, revision_id, proposer,
                                 evidence_ref, evidence_digest, decision, expires_at):
        return await self._val(
            actor, scope,
            "SELECT living.record_attestation($1,$2,$3::uuid,$4::uuid,$5,$6,$7,$8,$9::timestamptz)",
            attestation_id, revision_id, proposer, evidence_ref, evidence_digest, decision,
            expires_at)

    async def revoke_attestation(self, actor, scope, attestation_id):
        return await self._val(actor, scope, "SELECT living.revoke_attestation($1,$2,$3::uuid)",
                               attestation_id)

    async def set_trusted_reviewer(self, role, scope, active, expires_at):
        await self._admin("SELECT living.set_trusted_reviewer($1,$2,$3,$4,$5)", role,
                          scope.tenant_id, scope.source_id, active, expires_at)

    async def define_actor(self, name, member_of):
        assert _IDENT.fullmatch(name) and all(_IDENT.fullmatch(p) for p in member_of)
        if not await self.conn.fetchval("SELECT 1 FROM pg_catalog.pg_roles WHERE rolname=$1", name):
            await self.conn.execute(f'CREATE ROLE "{name}" NOLOGIN')
        for parent in member_of:
            await self.conn.execute(f'GRANT "{parent}" TO "{name}"')

    async def get_head(self, actor, scope, model_key):
        rows = await self._rows(
            actor, scope, "SELECT * FROM living.accepted_heads WHERE tenant_id=$1 AND "
            "source_id=$2 AND model_key=$3", model_key)
        return HeadView(model_key, rows[0]["revision_id"], rows[0]["version"]) if rows else None

    async def list_acceptances(self, actor, scope):
        rows = await self._rows(
            actor, scope, "SELECT * FROM living.acceptance_events WHERE tenant_id=$1 AND "
            "source_id=$2 ORDER BY model_key, to_version")
        return tuple(AcceptanceView(r["acceptance_id"], r["model_key"], r["from_version"],
                                    r["to_version"], r["accepted_revision"], r["approver_subject"],
                                    r["independent_evidence_ref"]) for r in rows)

    # ------------------------------------------------------------------ test support
    async def warp(self, seconds: float) -> None:
        """Move job and outbox leases / run times ``seconds`` into the past (a clock jump forward).

        Superuser-only direct UPDATE of timing columns the functions compare with clock_timestamp();
        no guard under test reads any other column, and no function under test is bypassed.
        """
        await self.conn.execute(
            "UPDATE living.jobs SET lease_until=lease_until-make_interval(secs=>$1), "
            "next_run_at=next_run_at-make_interval(secs=>$1)", float(seconds))
        await self.conn.execute(
            "UPDATE living.outbox SET lease_until=lease_until-make_interval(secs=>$1)",
            float(seconds))
