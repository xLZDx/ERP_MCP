"""Bounded S13 universal-fence acceptance slice (candidate migration 027).

The route matrix maps the 54 distinct mutation API names / 55 exact legacy-call
signatures in S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md to their
runtime role allowlists, fixture recipe, and falsifying lock-plan oracle. Most
entries remain NOT_RUN here: this module first verifies the exact role matrix
and exercises one complete namespace-7 wait/no-partial-write scenario.

Run: uv run pytest -q tests/phase2/test_s13_universal_fence_matrix.py
All database work uses the invocation-owned, loopback-only PostgreSQL 16 fixture
from test_s13_current_turn_sql.py; no configured lane DB or COM is used.
"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import uuid

import asyncpg
import pytest
import pytest_asyncio

from _pg_harness import disposable_cluster
from test_s13_current_turn_sql import (
    L,
    _OwnedClusterDsn,
    _ledger_snapshot,
    ledger,
)

pytestmark = pytest.mark.integration

T = "T1"
C = "C1"
ALL_ROLES = (
    "requester_role", "approver_role", "operator_role", "writer_role", "worker_role",
    "auditor_role", "checkpoint_role", "business_ai_private_writer",
    "private_writer_evidence_ingest",
)
ROLE_NAMES = {
    "requester": "requester_role",
    "approver": "approver_role",
    "operator": "operator_role",
    "writer": "writer_role",
    "worker": "worker_role",
    "auditor": "auditor_role",
    "checkpoint": "checkpoint_role",
}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def owned_cluster_dsn() -> AsyncIterator[_OwnedClusterDsn]:
    """Expose only generated fixture identity; the shared harness owns verification/cleanup."""
    old_opt_in = os.environ.get("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS")
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    try:
        async with disposable_cluster() as (dsn, name, _owner_token):
            # Container/DB names are generated identifiers, not connection credentials.
            print(f"S13_DISPOSABLE_PG_CONTAINER={name}")
            yield _OwnedClusterDsn(dsn)
    finally:
        if old_opt_in is None:
            os.environ.pop("ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS", None)
        else:
            os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = old_opt_in
# Migration 027 deliberately withdraws these legacy application entry points while
# versioned replacements/private paths remain separately gated. The source inventory
# roles below describe pre-candidate runtime grants; candidate effective ACL is empty.
WITHDRAWN_LEGACY_ROUTES = {
    "operator_resolve", "operator_close_failed_verify", "begin_apply", "issue_permit",
    "record_call", "complete_signed", "complete_lock_busy", "verify_signed",
    "resolve_unknown_signed", "verify_inconclusive", "retry_verify", "recover_sweep",
    "revoke_stale",
}


@dataclass(frozen=True, slots=True)
class MutationRoute:
    signature: str
    roles: tuple[str, ...]
    fixture: str
    lock_keys: str
    oracle: str

    @property
    def name(self) -> str:
        return self.signature.split("(", 1)[0].rsplit(".", 1)[-1]

    @property
    def scenario_id(self) -> str:
        normalized = self.name.upper().replace("_", "-")
        overload = "-2" if self.name == "recover_sweep" and self.signature.endswith("text,text)") else ""
        return f"S13-UF54-{normalized}{overload}-ENTRY-01"


def _route(signature: str, roles: str, fixture: str, lock_keys: str) -> MutationRoute:
    return MutationRoute(
        signature=f"change_ledger.{signature}",
        roles=tuple(roles.split("/")),
        fixture=fixture,
        lock_keys=lock_keys,
        oracle=(
            "hold namespace-7 scope fence; caller waits before relation/unique/trigger work; "
            "snapshot has zero row/event delta while blocked; release fence; assert exact allowed "
            "rows, one-or-zero event behavior, sorted/deduplicated planned keys, and refusal rollback"
        ),
    )


# Runtime roles are copied from the source-final grant inventory, not inferred from v1
# candidate EXECUTE grants. `recover_sweep` has two final signatures but one API name.
ROUTES = (
    _route("propose(text,text,uuid,text,text,text,text,text,text,text,text,uuid,timestamptz,uuid)", "requester", "empty_scope_plus_target", "2,7,lifecycle,6(change-id),target-parent"),
    _route("validate(text,text,uuid)", "requester", "proposed_change", "2,7,lifecycle,6(change-id),4(business-key)"),
    _route("approve(text,text,uuid,text,text)", "approver", "validated_change_and_nonce", "7,lifecycle,6(record,nonce,approval-id)"),
    _route("reject(text,text,uuid,text)", "approver", "validated_change_and_nonce", "7,lifecycle,6(record,nonce,approval-id)"),
    _route("issue_approval_nonce(text,text,uuid)", "approver", "proposed_change", "7,lifecycle,6(record,nonce-id)"),
    _route("claim(text,text,uuid,text,uuid,numeric,boolean,boolean)", "requester", "approved_change_and_grant", "2,7,lifecycle,6(grant,record,token),3/4(resource)"),
    _route("release_claim(text,text,uuid)", "requester/worker", "claimed_change", "7,lifecycle,6(record,token),parent-before-child"),
    _route("begin_apply(text,text,uuid,uuid,text,text)", "requester/writer", "claimed_and_observed_change", "2,7,lifecycle,6(call,token,record,intent)"),
    _route("issue_permit(text,text,uuid,bigint)", "worker", "applying_change_and_checkpoint", "2,7,lifecycle,6(record,permit)"),
    _route("cancel_permit(text,text,uuid,bigint)", "worker/operator", "permitted_or_dispatched_change", "2,7,lifecycle,6(record,permit,tokens),3/4(resources)"),
    _route("record_call(text,text,uuid,bigint,uuid)", "writer", "permitted_change", "2,7,8(base),lifecycle,6(call,record),permit-CAS"),
    _route("complete_signed(text,text,uuid,bigint,text,uuid)", "writer", "dispatched_change_and_completion_evidence", "2,7,8(base),lifecycle,6(record,attempt,evidence),3/4(resources)"),
    _route("complete_lock_busy(text,text,uuid,bigint,uuid,jsonb)", "writer", "dispatched_change_and_lock_busy_evidence", "2,7,8(base),lifecycle,6(record,attempt),3/4(resources)"),
    _route("resolve_unknown_signed(text,text,uuid,uuid,uuid,boolean,boolean)", "worker", "unknown_attempt_and_signed_outcome", "2,7,8(base),lifecycle,6(record,attempt,evidence)"),
    _route("verify_signed(text,text,uuid,uuid,uuid,uuid)", "worker", "completed_change_and_verification_evidence", "2,7,lifecycle,6(record,evidence)"),
    _route("retry_verify(text,text,uuid,uuid,uuid,uuid)", "worker", "failed_verification_change", "2,7,lifecycle,6(record,attempt),3/4(resources)"),
    _route("verify_inconclusive(text,text,uuid,uuid)", "worker", "uncertain_verification_change", "2,7,lifecycle,6(record,counter,hold)"),
    _route("operator_resolve(text,text,uuid,uuid,boolean,boolean)", "operator", "t16_eligible_change_with_witness_cosign", "2,7,8(base),lifecycle,sorted-6(evidence),3/4(resources)"),
    _route("operator_close_failed_verify(text,text,uuid,uuid,boolean)", "operator", "failed_verification_with_witness_cosign", "2,7,lifecycle,sorted-6(ids),3/4(resources)"),
    _route("recover_sweep(text,text,jsonb)", "worker", "stale_recovery_batch", "2,7,lifecycle,5(sweep),6(run-id,selected-ids),3/4(resources)"),
    _route("recover_sweep(text,text)", "worker", "default_stale_recovery_batch", "2,7,lifecycle,5(sweep),6(run-id,selected-ids),3/4(resources)"),
    _route("revoke_change(text,text,uuid,text)", "operator/worker", "revocable_change_and_tokens", "2,7,lifecycle,6(record,tokens),3/4(resources)"),
    _route("revoke_stale(text,text)", "worker", "stale_change_batch", "2,7,lifecycle,5(sweep),6(selected-ids),3/4(resources)"),
    _route("release_hold(text,text,uuid,jsonb)", "operator", "open_hold_and_optional_cosign", "2,7,lifecycle,6(hold-cosign-id),3(hold)"),
    _route("kill_switch(text,text,text)", "operator", "scope_switch_and_optional_recovery_batch", "2-exclusive,7,5(sweep),6(run-id,selected-ids)"),
    _route("budget_admin(text,text,uuid,text,numeric,integer,integer,timestamptz,timestamptz)", "operator", "scope_and_grant_id", "7,lifecycle,6(grant-id)"),
    _route("budget_revoke(text,text,uuid)", "operator", "scope_and_existing_grant", "7,lifecycle,6(grant-id)"),
    _route("declare_budget(text,text,uuid,uuid,text,numeric,boolean,boolean)", "requester", "proposed_change_and_grant", "7,lifecycle,6(record),grant-parent-before-record"),
    _route("check_anchor(text,text,bigint,text)", "worker", "scope_targets_and_open_anchor_holds", "2,7,lifecycle,3(sorted-holds)"),
    _route("declare_anchor_gap(text,text,text,jsonb)", "worker/operator/writer", "scope_targets_and_open_hold", "2,7,lifecycle,6(hold-id),3(hold)"),
    _route("declare_unclean_restart(text,text,text,jsonb)", "worker/operator", "scope_targets_and_open_hold", "2,7,lifecycle,6(hold-id),3(hold)"),
    _route("anchor_gap_cosign(text,text,uuid,jsonb)", "operator", "open_anchor_hold_and_witness", "7,lifecycle,6(cosign-id)"),
    _route("register_principal(text,text,text,text,text[],boolean)", "operator", "registry_change_or_scoped_principal", "7,lifecycle,6(registry-change-id),epoch-key"),
    _route("register_target(text,text,text,text,text,text,timestamptz)", "operator", "registry_change_or_scoped_target", "7,lifecycle,6(registry-change-id),target-parent,epoch-key"),
    _route("register_verifier_key(text,text,text,text,text)", "operator", "registry_change_or_scoped_verifier_key", "7,lifecycle,sorted-verifier-material,6(verifier-key-id)"),
    _route("propose_registry_change(text,text,text,jsonb)", "operator", "empty_registry_change_scope", "7,lifecycle,6(preallocated-registry-change-id)"),
    _route("approve_registry_change(text,text,uuid,text)", "operator", "pending_registry_change", "2-if-applicable,7,lifecycle,sorted-verifier-material,6(change-id)"),
    _route("revoke_verifier_key(text,text,text)", "operator", "active_verifier_key", "7,lifecycle,sorted-verifier-material,6(verifier-key-id)"),
    _route("enforce_registry(text,text)", "operator", "scope_registry_policy", "7,lifecycle,policy-parent-before-event"),
    _route("bump_epoch(text,text,text)", "operator", "scope_epoch_key", "7,lifecycle,epoch-key"),
    _route("declare_target_class(text,text,uuid,text)", "requester", "proposed_change", "7,lifecycle,6(record-id)"),
    _route("observe_target(text,text,uuid,text,text)", "writer", "claimed_change_and_target", "2,7,lifecycle,6(record,token),4(target)"),
    _route("add_epoch_dependency(text,text,uuid,text)", "requester", "proposed_change", "7,lifecycle,6(record-id)"),
    _route("declare_business_key(text,text,uuid,text,text,text)", "requester", "proposed_change_and_business_key", "7,lifecycle,6(record-id),4(business-key)"),
    _route("bind_duplicate_override(text,text,uuid,text)", "approver", "proposed_change_and_override", "2,7,lifecycle,6(record-id),4(override-key)"),
    _route("record_evidence(text,text,uuid,text,text,timestamptz,jsonb,text,text,text,bigint,uuid)", "worker/writer", "dispatched_or_prepared_change_and_evidence", "7,lifecycle,6(record,evidence-id),verifier-key"),
    _route("store_approval_text(text,text,uuid,text,text)", "requester", "proposed_change_and_issued_nonce", "7,lifecycle,6(record,nonce,envelope-id)"),
    _route("witness_cosign_signed(text,text,uuid,uuid)", "operator", "t16_change_and_verified_witness_evidence", "7,lifecycle,6(change-id,cosign-id)"),
    _route("record_checkpoint(text,text,bigint,text,text,text,text,text,timestamptz,boolean)", "checkpoint", "scope_verifier_key_and_signed_checkpoint", "7,lifecycle,checkpoint-identity"),
    _route("attach_permit_signature(text,text,uuid,bigint,text,text)", "checkpoint", "permitted_change_and_signature", "7,lifecycle,6(change-id,permit),permit-trigger"),
    _route("require_dispatch_receipt(text,text,uuid,bigint)", "writer/requester", "claimed_change_and_generation", "7,lifecycle,6(change-id),generation-trigger"),
    _route("record_dispatch_receipt(text,text,uuid,bigint,text,text,text,text)", "writer/requester", "dispatched_change_and_signed_receipt", "7,lifecycle,6(change-id,receipt-id)"),
    _route("verify_dispatch_payload(text,text,uuid,bigint,text)", "writer/requester", "approved_change_and_payload", "7,lifecycle,6(change-id,verification-id)"),
    _route("set_sweep_policy(text,text,jsonb)", "operator", "scope_policy", "7,lifecycle,scope-policy-row"),
    _route("renew_writer_lease(text,text,uuid,bigint,integer)", "writer", "claimed_change_and_writer_lease", "2,7,lifecycle,6(change-id),lease-row"),
)


async def test_s13_uf54_catalog_signature_and_effective_execute_allowlist(ledger: L) -> None:
    """UF54-CATALOG-01: every inventory signature exists and has only its mapped role grants."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    routes = {route.signature: route for route in ROUTES}
    assert len({route.name for route in ROUTES}) == 54
    assert len(routes) == 55
    assert len({route.scenario_id for route in ROUTES}) == 55

    for route in ROUTES:
        oid = await ledger.conn.fetchval("SELECT pg_catalog.to_regprocedure($1)::oid", route.signature)
        assert oid is not None, route.scenario_id
        acl = await ledger.conn.fetchrow(
            """SELECT EXISTS (
                   SELECT 1 FROM pg_catalog.aclexplode(
                     coalesce(p.proacl, pg_catalog.acldefault('f', p.proowner))) a
                   WHERE a.grantee=0 AND a.privilege_type='EXECUTE'
                 ) AS public_execute
                 FROM pg_catalog.pg_proc p WHERE p.oid=$1""",
            oid,
        )
        assert acl["public_execute"] is False, route.scenario_id
        effective = await ledger.conn.fetch(
            "SELECT role_name, pg_catalog.has_function_privilege(role_name::name,$1::oid,'EXECUTE') AS can_execute "
            "FROM unnest($2::text[]) AS roles(role_name) ORDER BY role_name",
            oid,
            list(ALL_ROLES),
        )
        actual = {row["role_name"] for row in effective if row["can_execute"]}
        expected = (
            set() if route.name in WITHDRAWN_LEGACY_ROUTES
            else {ROLE_NAMES[role] for role in route.roles}
        )
        assert actual == expected, (route.scenario_id, sorted(actual), sorted(expected))


async def _wait_for_advisory_wait(conn: asyncpg.Connection, application_name: str,
                                  task: asyncio.Task, scenario_id: str, scope_key: str,
                                  timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    last_wait: str | None = None
    while asyncio.get_running_loop().time() < deadline:
        if task.done():
            await task
            raise AssertionError(f"{scenario_id}: entry did not wait on namespace 7")
        row = await conn.fetchrow(
            """SELECT a.pid,a.wait_event_type,a.wait_event,EXISTS (
                   SELECT 1 FROM pg_catalog.pg_locks l
                   WHERE l.pid=a.pid AND l.locktype='advisory'
                     AND l.classid=7::oid
                     AND l.objid=((pg_catalog.hashtext($2)::bigint & 4294967295)::oid)
                     AND l.objsubid=2 AND NOT l.granted
                 ) AS waiting_on_expected_lock
                 FROM pg_catalog.pg_stat_activity a WHERE a.application_name=$1""",
            application_name,
            scope_key,
        )
        if row:
            last_wait = (
                f"pid={row['pid']} wait_event_type={row['wait_event_type']} "
                f"wait_event={row['wait_event']} target_lock={row['waiting_on_expected_lock']}"
            )
        if (row and row["wait_event_type"] == "Lock" and row["wait_event"] == "advisory"
                and row["waiting_on_expected_lock"]):
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"{scenario_id}: expected ungranted namespace-7 advisory lock was not observed; {last_wait}"
    )


async def _wait_for_exact_lock_tuple(conn: asyncpg.Connection, application_name: str,
                                     task: asyncio.Task, scenario_id: str, namespace: int,
                                     lock_hash: int, mode: str,
                                     timeout: float = 5.0) -> int:
    deadline = asyncio.get_running_loop().time() + timeout
    last_wait: str | None = None
    while asyncio.get_running_loop().time() < deadline:
        if task.done():
            await task
            raise AssertionError(f"{scenario_id}: entry did not wait on advisory tuple")
        row = await conn.fetchrow(
            """SELECT a.pid,a.wait_event_type,a.wait_event,EXISTS (
                   SELECT 1 FROM pg_catalog.pg_locks l
                   WHERE l.pid=a.pid AND l.locktype='advisory'
                     AND l.classid=($2::bigint)::oid
                     AND l.objid=(($3::bigint & 4294967295)::oid)
                     AND l.objsubid=2 AND NOT l.granted AND l.mode=$4
                 ) AS waiting_on_expected_lock
                 FROM pg_catalog.pg_stat_activity a WHERE a.application_name=$1""",
            application_name,
            namespace,
            lock_hash,
            mode,
        )
        if row:
            last_wait = (
                f"pid={row['pid']} wait_event_type={row['wait_event_type']} "
                f"wait_event={row['wait_event']} target_lock={row['waiting_on_expected_lock']}"
            )
        if (row and row["wait_event_type"] == "Lock" and row["wait_event"] == "advisory"
                and row["waiting_on_expected_lock"]):
            return row["pid"]
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"{scenario_id}: expected ungranted advisory tuple namespace={namespace}, "
        f"hash={lock_hash}, mode={mode} was not observed; {last_wait}"
    )


async def _call_set_policy(conn: asyncpg.Connection, application_name: str) -> str | dict:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_erin"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await conn.fetchval(
            "SELECT change_ledger.set_sweep_policy($1,$2,$3::jsonb)",
            T,
            C,
            json.dumps({"verify_max_attempts": 7}),
        )


@pytest.mark.asyncio
async def test_s13_uf54_set_sweep_policy_waits_before_any_row_or_event_delta(ledger: L) -> None:
    """S13-UF54-SET-SWEEP-POLICY-ENTRY-01: a namespace-7 waiter has no partial effects."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-set-policy"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    tx = blocker.transaction()
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        await tx.start()
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        task = asyncio.create_task(_call_set_policy(contender, application_name))
        await _wait_for_advisory_wait(
            ledger.conn, application_name, task, "S13-UF54-SET-SWEEP-POLICY-ENTRY-01", scope_key
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            "scope-fence wait must precede relation/unique/trigger writes"
        )
        await tx.commit()
        result = await asyncio.wait_for(task, timeout=10)
        if isinstance(result, str):
            result = json.loads(result)
        assert result["verify_max_attempts"] == 7
        policy = await ledger.conn.fetchrow(
            "SELECT params FROM change_ledger.sweep_policy WHERE tenant_id=$1 AND company_id=$2", T, C
        )
        assert policy is not None
        params = policy["params"]
        if isinstance(params, str):
            params = json.loads(params)
        assert params["verify_max_attempts"] == 7
        after = await _ledger_snapshot(ledger.conn)
        assert after != before
        event_count = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C
        )
        assert event_count == 1
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await tx.rollback()
        except (asyncpg.InterfaceError, asyncpg.PostgresError):
            pass
        await contender.close()
        await blocker.close()


async def _call_bump_epoch(conn: asyncpg.Connection, application_name: str, key: str) -> int:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_erin"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await conn.fetchval("SELECT change_ledger.bump_epoch($1,$2,$3)", T, C, key)


@pytest.mark.asyncio
async def test_s13_uf54_bump_epoch_waits_before_epoch_row_and_event_effects(ledger: L) -> None:
    """S13-UF54-BUMP-EPOCH-ENTRY-01: namespace-7 wait precedes epoch and event writes."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-bump-epoch"
    scenario_id = "S13-UF54-BUMP-EPOCH-ENTRY-01"
    key = "s13-uf54-bump-epoch-fence-probe"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    tx = blocker.transaction()
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        await tx.start()
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        task = asyncio.create_task(_call_bump_epoch(contender, application_name, key))
        await _wait_for_advisory_wait(ledger.conn, application_name, task, scenario_id, scope_key)
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: epoch row or event changed before namespace-7 release"
        )
        await tx.commit()
        value = await asyncio.wait_for(task, timeout=10)
        assert value == 1, f"{scenario_id}: first key epoch must be 1"
        epoch = await ledger.conn.fetchval(
            "SELECT value FROM change_ledger.epochs "
            "WHERE tenant_id=$1 AND company_id=$2 AND epoch_key=$3", T, C, key
        )
        assert epoch == 1, f"{scenario_id}: persisted epoch does not match return value"
        event_count = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND event_type='EPOCH_BUMPED' AND payload->>'key'=$3", T, C, key
        )
        assert event_count == 1, f"{scenario_id}: exactly one matching event is required"
        assert await _ledger_snapshot(ledger.conn) != before
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await tx.rollback()
        except (asyncpg.InterfaceError, asyncpg.PostgresError):
            pass
        await contender.close()
        await blocker.close()


async def _call_declare_target_class(conn: asyncpg.Connection, application_name: str,
                                    change_id: object) -> str:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_alice"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await conn.fetchval(
            "SELECT change_ledger.declare_target_class($1,$2,$3,$4)",
            T, C, change_id, "CLONE",
        )


@pytest.mark.asyncio
async def test_s13_uf54_declare_target_class_waits_before_record_and_event_effects(ledger: L) -> None:
    """S13-UF54-DECLARE-TARGET-CLASS-ENTRY-01: fence wait precedes record/event writes."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id = await ledger.propose(budget=False, declare_class=False)
    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-target-class"
    scenario_id = "S13-UF54-DECLARE-TARGET-CLASS-ENTRY-01"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    tx = blocker.transaction()
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        await tx.start()
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        task = asyncio.create_task(
            _call_declare_target_class(contender, application_name, change_id)
        )
        await _wait_for_advisory_wait(
            ledger.conn, application_name, task, scenario_id, scope_key
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: record or event changed before namespace-7 release"
        )
        await tx.commit()
        result = await asyncio.wait_for(task, timeout=10)
        assert result == "DISPOSABLE_CLONE", f"{scenario_id}: normalized class mismatch"
        row = await ledger.conn.fetchrow(
            "SELECT declared_target_class FROM change_ledger.records "
            "WHERE tenant_id=$1 AND company_id=$2 AND change_id=$3", T, C, change_id
        )
        assert row is not None and row["declared_target_class"] == "DISPOSABLE_CLONE"
        event_count = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3 AND event_type='TARGET_CLASS_DECLARED'", T, C, change_id
        )
        assert event_count == 1, f"{scenario_id}: exactly one matching event is required"
        assert await _ledger_snapshot(ledger.conn) != before
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await tx.rollback()
        except (asyncpg.InterfaceError, asyncpg.PostgresError):
            pass
        await contender.close()
        await blocker.close()


async def _call_budget_admin(conn: asyncpg.Connection, application_name: str,
                             grant_id: uuid.UUID) -> uuid.UUID:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_erin"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await conn.fetchval(
            "SELECT change_ledger.budget_admin($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            T, C, grant_id, "EUR", 1250, 17, 9,
            datetime(2020, 1, 1, tzinfo=UTC), datetime(2030, 1, 1, tzinfo=UTC),
        )


@pytest.mark.asyncio
async def test_s13_uf54_budget_admin_waits_before_grant_and_event_effects(ledger: L) -> None:
    """S13-UF54-BUDGET-ADMIN-ENTRY-01: scope fence wait precedes grant and event writes."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-budget-admin"
    scenario_id = "S13-UF54-BUDGET-ADMIN-ENTRY-01"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    grant_id = uuid.uuid4()
    tx = blocker.transaction()
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        await tx.start()
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        task = asyncio.create_task(_call_budget_admin(contender, application_name, grant_id))
        await _wait_for_advisory_wait(
            ledger.conn, application_name, task, scenario_id, scope_key
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: grant row or event changed before namespace-7 release"
        )
        await tx.commit()
        result = await asyncio.wait_for(task, timeout=10)
        assert result == grant_id, f"{scenario_id}: returned grant identity changed"
        grant = await ledger.conn.fetchrow(
            "SELECT tenant_id,company_id,currency,amount_limit,count_limit,post_count_limit,"
            "window_start,window_end,status FROM change_ledger.grants WHERE grant_id=$1", grant_id
        )
        assert grant is not None
        assert (
            grant["tenant_id"], grant["company_id"], grant["currency"],
            grant["amount_limit"], grant["count_limit"], grant["post_count_limit"],
            grant["status"],
        ) == (T, C, "EUR", 1250, 17, 9, "ACTIVE")
        assert grant["window_start"] == datetime(2020, 1, 1, tzinfo=UTC)
        assert grant["window_end"] == datetime(2030, 1, 1, tzinfo=UTC)
        event_count = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND event_type='BUDGET_GRANT_SET' AND payload->>'grant_id'=$3",
            T, C, str(grant_id),
        )
        assert event_count == 1, f"{scenario_id}: exactly one matching event is required"
        assert await _ledger_snapshot(ledger.conn) != before
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await tx.rollback()
        except (asyncpg.InterfaceError, asyncpg.PostgresError):
            pass
        await contender.close()
        await blocker.close()


async def _call_budget_revoke(conn: asyncpg.Connection, application_name: str,
                              grant_id: uuid.UUID) -> str:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_erin"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await conn.fetchval("SELECT change_ledger.budget_revoke($1,$2,$3)", T, C, grant_id)


@pytest.mark.asyncio
async def test_s13_uf54_budget_revoke_waits_before_grant_and_event_effects(ledger: L) -> None:
    """S13-UF54-BUDGET-REVOKE-ENTRY-01: scope fence wait precedes revoke effects."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    grant_id = uuid.uuid4()
    assert await _call_budget_admin(ledger.conn, "s13-uf54-budget-revoke-seed", grant_id) == grant_id
    seeded = await ledger.conn.fetchval(
        "SELECT status FROM change_ledger.grants WHERE grant_id=$1", grant_id
    )
    assert seeded == "ACTIVE"

    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-budget-revoke"
    scenario_id = "S13-UF54-BUDGET-REVOKE-ENTRY-01"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    tx = blocker.transaction()
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        await tx.start()
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        task = asyncio.create_task(_call_budget_revoke(contender, application_name, grant_id))
        await _wait_for_advisory_wait(
            ledger.conn, application_name, task, scenario_id, scope_key
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: grant row or event changed before namespace-7 release"
        )
        await tx.commit()
        result = await asyncio.wait_for(task, timeout=10)
        assert result == "REVOKED", f"{scenario_id}: revocation result mismatch"
        status = await ledger.conn.fetchval(
            "SELECT status FROM change_ledger.grants WHERE grant_id=$1", grant_id
        )
        assert status == "REVOKED", f"{scenario_id}: grant remains active"
        event_count = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND event_type='BUDGET_GRANT_REVOKED' AND payload->>'grant_id'=$3",
            T, C, str(grant_id),
        )
        assert event_count == 1, f"{scenario_id}: exactly one matching event is required"
        assert await _ledger_snapshot(ledger.conn) != before
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await tx.rollback()
        except (asyncpg.InterfaceError, asyncpg.PostgresError):
            pass
        await contender.close()
        await blocker.close()


async def _call_issue_approval_nonce(conn: asyncpg.Connection, application_name: str,
                                    change_id: uuid.UUID) -> str:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_bob"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await conn.fetchval(
            "SELECT change_ledger.issue_approval_nonce($1,$2,$3)", T, C, change_id
        )


@pytest.mark.asyncio
async def test_s13_uf54_issue_approval_nonce_waits_before_nonce_row_effect(ledger: L) -> None:
    """S13-UF54-ISSUE-APPROVAL-NONCE-ENTRY-01: namespace-7 wait precedes nonce insert."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id = await ledger.propose(budget=False, declare_class=False)
    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-issue-approval-nonce"
    scenario_id = "S13-UF54-ISSUE-APPROVAL-NONCE-ENTRY-01"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    tx = blocker.transaction()
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        events_before = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C
        )
        await tx.start()
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        task = asyncio.create_task(
            _call_issue_approval_nonce(contender, application_name, change_id)
        )
        await _wait_for_advisory_wait(
            ledger.conn, application_name, task, scenario_id, scope_key
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: nonce row or any other state changed before namespace-7 release"
        )
        release_at = datetime.now(UTC)
        await tx.commit()
        nonce = await asyncio.wait_for(task, timeout=10)
        assert len(nonce) == 64 and all(ch in "0123456789abcdef" for ch in nonce)
        rows = await ledger.conn.fetch(
            "SELECT nonce,change_id,approver,state,expires_at FROM change_ledger.approval_nonces "
            "WHERE change_id=$1 ORDER BY nonce", change_id
        )
        assert len(rows) == 1, f"{scenario_id}: expected one nonce row for proposed change"
        row = rows[0]
        assert (row["nonce"], row["change_id"], row["approver"], row["state"]) == (
            nonce, change_id, "clt_bob", "ISSUED"
        )
        assert release_at + timedelta(minutes=9, seconds=55) <= row["expires_at"] <= (
            release_at + timedelta(minutes=10, seconds=5)
        ), (
            f"{scenario_id}: expiry must be within five seconds of ten minutes after lock release"
        )
        events_after = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C
        )
        assert events_after == events_before, f"{scenario_id}: nonce issuance must not append an event"
        assert await _ledger_snapshot(ledger.conn) != before
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await tx.rollback()
        except (asyncpg.InterfaceError, asyncpg.PostgresError):
            pass
        await contender.close()
        await blocker.close()


async def _call_approve(conn: asyncpg.Connection, application_name: str, change_id: uuid.UUID,
                       nonce: str, digest: str) -> uuid.UUID:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_bob"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await conn.fetchval(
            "SELECT change_ledger.approve($1,$2,$3,$4,$5)", T, C, change_id, nonce, digest
        )


@pytest.mark.asyncio
async def test_s13_uf54_approve_waits_before_approval_and_event_effects(ledger: L) -> None:
    """S13-UF54-APPROVE-ENTRY-01: namespace-7 wait precedes approval consumption/writes."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id = await ledger.validated()
    nonce = await ledger.call("clt_bob", "issue_approval_nonce", change_id)
    digest = await ledger.approval_digest(change_id)
    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-approve"
    scenario_id = "S13-UF54-APPROVE-ENTRY-01"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    tx = blocker.transaction()
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        events_before = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        await tx.start()
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        task = asyncio.create_task(
            _call_approve(contender, application_name, change_id, nonce, digest)
        )
        await _wait_for_advisory_wait(
            ledger.conn, application_name, task, scenario_id, scope_key
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: approval, record, nonce, or event state changed before release"
        )
        await tx.commit()
        approval_id = await asyncio.wait_for(task, timeout=10)
        approval = await ledger.conn.fetchrow(
            "SELECT approval_id,change_id,approver,nonce,digest,decision FROM change_ledger.approvals "
            "WHERE approval_id=$1", approval_id
        )
        assert approval is not None
        assert (
            approval["approval_id"], approval["change_id"], approval["approver"],
            approval["nonce"], approval["digest"], approval["decision"],
        ) == (approval_id, change_id, "clt_bob", nonce, digest, "APPROVE")
        assert await ledger.conn.fetchval(
            "SELECT authorization_state FROM change_ledger.records WHERE change_id=$1", change_id
        ) == "APPROVED"
        assert await ledger.conn.fetchval(
            "SELECT state FROM change_ledger.approval_nonces WHERE nonce=$1", nonce
        ) == "CONSUMED"
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.approvals WHERE change_id=$1", change_id
        ) == 1
        events_after = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        assert events_after == events_before + 1
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3 AND event_type='APPROVED'", T, C, change_id
        ) == 1
        assert await _ledger_snapshot(ledger.conn) != before
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await tx.rollback()
        except (asyncpg.InterfaceError, asyncpg.PostgresError):
            pass
        await contender.close()
        await blocker.close()


async def _call_reject(conn: asyncpg.Connection, application_name: str, change_id: uuid.UUID,
                       nonce: str) -> str:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_bob"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await conn.fetchval(
            "SELECT change_ledger.reject($1,$2,$3,$4)", T, C, change_id, nonce
        )


@pytest.mark.asyncio
async def test_s13_uf54_reject_waits_before_approval_and_event_effects(ledger: L) -> None:
    """S13-UF54-REJECT-ENTRY-01: namespace-7 wait precedes rejection effects."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id = await ledger.validated()
    nonce = await ledger.call("clt_bob", "issue_approval_nonce", change_id)
    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-reject"
    scenario_id = "S13-UF54-REJECT-ENTRY-01"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    tx = blocker.transaction()
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        events_before = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        await tx.start()
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        task = asyncio.create_task(
            _call_reject(contender, application_name, change_id, nonce)
        )
        await _wait_for_advisory_wait(
            ledger.conn, application_name, task, scenario_id, scope_key
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: approval, record, nonce, or event state changed before release"
        )
        await tx.commit()
        result = await asyncio.wait_for(task, timeout=10)
        assert result == "REJECTED"
        approval_rows = await ledger.conn.fetch(
            "SELECT approval_id,change_id,approver,nonce,digest,decision "
            "FROM change_ledger.approvals WHERE change_id=$1 ORDER BY approval_id", change_id
        )
        assert len(approval_rows) == 1, f"{scenario_id}: expected one rejection approval row"
        approval = approval_rows[0]
        assert (
            approval["change_id"], approval["approver"], approval["nonce"],
            approval["digest"], approval["decision"],
        ) == (change_id, "clt_bob", nonce, "0" * 64, "REJECT")
        assert await ledger.conn.fetchval(
            "SELECT lifecycle FROM change_ledger.records WHERE change_id=$1", change_id
        ) == "REJECTED"
        assert await ledger.conn.fetchval(
            "SELECT authorization_state FROM change_ledger.records WHERE change_id=$1", change_id
        ) == "NONE"
        assert await ledger.conn.fetchval(
            "SELECT state FROM change_ledger.approval_nonces WHERE nonce=$1", nonce
        ) == "CONSUMED"
        events_after = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        assert events_after == events_before + 1
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3 AND event_type='REJECTED'", T, C, change_id
        ) == 1
        assert await _ledger_snapshot(ledger.conn) != before
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await tx.rollback()
        except (asyncpg.InterfaceError, asyncpg.PostgresError):
            pass
        await contender.close()
        await blocker.close()


async def _call_validate(conn: asyncpg.Connection, application_name: str,
                         change_id: uuid.UUID) -> str:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_alice"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await conn.fetchval("SELECT change_ledger.validate($1,$2,$3)", T, C, change_id)


@pytest.mark.asyncio
async def test_s13_uf54_validate_waits_before_record_and_event_effects(ledger: L) -> None:
    """S13-UF54-VALIDATE-ENTRY-01: fence precedes row/event effects and replay is inert."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id = await ledger.propose()
    blocker = await ledger.db.connect()
    contender = await ledger.db.connect()
    application_name = "s13-uf54-validate"
    scenario_id = "S13-UF54-VALIDATE-ENTRY-01"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    tx = blocker.transaction()
    task: asyncio.Task | None = None
    try:
        before = await _ledger_snapshot(ledger.conn)
        events_before = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        await tx.start()
        await blocker.fetchval(
            "SELECT pg_catalog.pg_advisory_xact_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        task = asyncio.create_task(_call_validate(contender, application_name, change_id))
        await _wait_for_advisory_wait(
            ledger.conn, application_name, task, scenario_id, scope_key
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: record, business key, or event state changed before release"
        )
        await tx.commit()
        result = await asyncio.wait_for(task, timeout=10)
        assert result == "VALIDATED"
        record_state = await ledger.conn.fetchval(
            "SELECT lifecycle FROM change_ledger.records WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        assert record_state == "VALIDATED"
        events_after_validate = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        assert events_after_validate == events_before + 1
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3 AND event_type='VALIDATED'", T, C, change_id
        ) == 1
        after_validate = await _ledger_snapshot(ledger.conn)
        assert after_validate != before

        replay = await _call_validate(ledger.conn, "s13-uf54-validate-replay", change_id)
        assert replay == "VALIDATED"
        assert await _ledger_snapshot(ledger.conn) == after_validate, (
            f"{scenario_id}: already-validated replay changed state"
        )
        events_after_replay = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        assert events_after_replay == events_after_validate, (
            f"{scenario_id}: replay appended an unexpected event"
        )
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await tx.rollback()
        except (asyncpg.InterfaceError, asyncpg.PostgresError):
            pass
        await contender.close()
        await blocker.close()


async def _call_claim(conn: asyncpg.Connection, application_name: str, change_id: uuid.UUID,
                     grant_id: uuid.UUID, amount: object, counts_create_update: bool,
                     counts_post: bool) -> asyncpg.Record:
    await conn.execute("SELECT pg_catalog.set_config('application_name',$1,false)", application_name)
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "clt_alice"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
        return await conn.fetchrow(
            "SELECT * FROM change_ledger.claim($1,$2,$3,$4,$5,$6,$7,$8)",
            T, C, change_id, None, grant_id, amount, counts_create_update, counts_post,
        )


@pytest.mark.asyncio
async def test_s13_uf54_claim_obeys_ranked_fences_before_resource_and_event_effects(ledger: L) -> None:
    """S13-UF54-CLAIM-ENTRY-01: 2→7→6→sorted 4 locks precede claim resource writes."""
    print(f"S13_DISPOSABLE_DB={ledger.db.name}")
    change_id = await ledger.approved()
    rec = await ledger.conn.fetchrow(
        "SELECT base_fingerprint,target_ref FROM change_ledger.records WHERE change_id=$1", change_id
    )
    budget = await ledger.conn.fetchrow(
        "SELECT grant_id,amount,counts_create_update,counts_post "
        "FROM change_ledger.change_budget WHERE change_id=$1", change_id
    )
    business_key = await ledger.conn.fetchval(
        "SELECT key_hash FROM change_ledger.business_keys WHERE change_id=$1", change_id
    )
    assert rec is not None and budget is not None and business_key is not None
    target_ref = rec["target_ref"] or str(change_id)
    resource_keys = [
        f"target-lock:v1:{T}:{C}:{rec['base_fingerprint']}:{target_ref}",
        f"{T}:{C}:{rec['base_fingerprint']}:{business_key}",
    ]
    resource_hash_rows = await ledger.conn.fetch(
        "SELECT DISTINCT pg_catalog.hashtext(k) AS lock_hash "
        "FROM pg_catalog.unnest($1::text[]) AS keys(k) ORDER BY lock_hash", resource_keys
    )
    resource_hashes = [row["lock_hash"] for row in resource_hash_rows]
    assert len(resource_hashes) == 2, "target and business-key fences must be distinct"
    resource_hash_to_key = {
        await ledger.conn.fetchval("SELECT pg_catalog.hashtext($1)", key): key
        for key in resource_keys
    }
    scenario_id = "S13-UF54-CLAIM-ENTRY-01"
    application_name = "s13-uf54-claim"
    switch_key = f"{T}:{C}"
    scope_key = (
        f"s13-scope:v1:{len(T.encode('utf-8'))}:{T}:"
        f"{len(C.encode('utf-8'))}:{C}"
    )
    switch_hash = await ledger.conn.fetchval("SELECT pg_catalog.hashtext($1)", switch_key)
    scope_hash = await ledger.conn.fetchval("SELECT pg_catalog.hashtext($1)", scope_key)

    blocker2 = await ledger.db.connect()
    blocker7 = await ledger.db.connect()
    blocker4 = await ledger.db.connect()
    contender = await ledger.db.connect()
    task: asyncio.Task | None = None
    try:
        await blocker2.fetchval(
            "SELECT pg_catalog.pg_advisory_lock(2,pg_catalog.hashtext($1))", switch_key
        )
        await blocker7.fetchval(
            "SELECT pg_catalog.pg_advisory_lock(7,pg_catalog.hashtext($1))", scope_key
        )
        for key in resource_keys:
            await blocker4.fetchval(
                "SELECT pg_catalog.pg_advisory_lock(4,pg_catalog.hashtext($1))", key
            )

        before = await _ledger_snapshot(ledger.conn)
        events_before = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        task = asyncio.create_task(_call_claim(
            contender, application_name, change_id, budget["grant_id"], budget["amount"],
            budget["counts_create_update"], budget["counts_post"],
        ))

        lock_pid_2 = await _wait_for_exact_lock_tuple(
            ledger.conn, application_name, task, scenario_id, 2, switch_hash, "ShareLock"
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: state changed while waiting on namespace 2"
        )
        assert await blocker2.fetchval(
            "SELECT pg_catalog.pg_advisory_unlock(2,pg_catalog.hashtext($1))", switch_key
        ) is True

        lock_pid_7 = await _wait_for_exact_lock_tuple(
            ledger.conn, application_name, task, scenario_id, 7, scope_hash, "ExclusiveLock"
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: state changed before namespace-7 release"
        )
        assert await blocker7.fetchval(
            "SELECT pg_catalog.pg_advisory_unlock(7,pg_catalog.hashtext($1))", scope_key
        ) is True

        first_hash, second_hash = resource_hashes
        first_key, second_key = resource_hash_to_key[first_hash], resource_hash_to_key[second_hash]
        lock_pid_4_first = await _wait_for_exact_lock_tuple(
            ledger.conn, application_name, task, scenario_id, 4, first_hash, "ExclusiveLock"
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: state changed while waiting for first sorted namespace-4 key"
        )
        assert await blocker4.fetchval(
            "SELECT pg_catalog.pg_advisory_unlock(4,pg_catalog.hashtext($1))", first_key
        ) is True
        lock_pid_4_second = await _wait_for_exact_lock_tuple(
            ledger.conn, application_name, task, scenario_id, 4, second_hash, "ExclusiveLock"
        )
        assert len({lock_pid_2, lock_pid_7, lock_pid_4_first, lock_pid_4_second}) == 1, (
            f"{scenario_id}: lock observations came from different contenders: "
            f"{lock_pid_2}, {lock_pid_7}, {lock_pid_4_first}, {lock_pid_4_second}"
        )
        assert await _ledger_snapshot(ledger.conn) == before, (
            f"{scenario_id}: state changed while waiting for second sorted namespace-4 key"
        )
        assert await blocker4.fetchval(
            "SELECT pg_catalog.pg_advisory_unlock(4,pg_catalog.hashtext($1))", second_key
        ) is True

        token = await asyncio.wait_for(task, timeout=10)
        assert token["change_id"] == change_id and token["generation"] == 1
        assert token["state"] == "ISSUED"
        record = await ledger.conn.fetchrow(
            "SELECT authorization_state,execution_state,claim_generation,reservation_state "
            "FROM change_ledger.records WHERE change_id=$1", change_id
        )
        assert tuple(record) == ("CLAIMED", "NOT_STARTED", 1, "RESERVED")
        tokens = await ledger.conn.fetch(
            "SELECT token_id,change_id,generation,state FROM change_ledger.claim_tokens "
            "WHERE change_id=$1 ORDER BY generation", change_id
        )
        assert len(tokens) == 1
        assert tuple(tokens[0]) == (token["token_id"], change_id, 1, "ISSUED")
        reservation = await ledger.conn.fetchrow(
            "SELECT grant_id,amount,state,counts_create_update,counts_post "
            "FROM change_ledger.reservations WHERE change_id=$1", change_id
        )
        assert tuple(reservation) == (
            budget["grant_id"], budget["amount"], "RESERVED",
            budget["counts_create_update"], budget["counts_post"],
        )
        target_lock = await ledger.conn.fetchrow(
            "SELECT tenant_id,company_id,base_fingerprint,target_ref,owner_change_id "
            "FROM change_ledger.target_locks WHERE owner_change_id=$1", change_id
        )
        assert tuple(target_lock) == (T, C, rec["base_fingerprint"], target_ref, change_id)
        key_lock = await ledger.conn.fetchrow(
            "SELECT tenant_id,company_id,base_fingerprint,key_hash,owner_change_id "
            "FROM change_ledger.key_locks WHERE owner_change_id=$1", change_id
        )
        assert tuple(key_lock) == (T, C, rec["base_fingerprint"], business_key, change_id)
        lease_count = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.writer_leases WHERE owner_change_id=$1", change_id
        )
        assert lease_count == 1
        events_after = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        assert events_after == events_before + 1
        assert await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3 AND event_type='CLAIMED'", T, C, change_id
        ) == 1
        after_claim = await _ledger_snapshot(ledger.conn)
        assert after_claim != before

        replay = await _call_claim(
            ledger.conn, "s13-uf54-claim-replay", change_id, budget["grant_id"],
            budget["amount"], budget["counts_create_update"], budget["counts_post"],
        )
        assert replay["token_id"] == token["token_id"]
        assert await _ledger_snapshot(ledger.conn) == after_claim, (
            f"{scenario_id}: exact live-token replay changed state"
        )
        events_after_replay = await ledger.conn.fetchval(
            "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
            "AND change_id=$3", T, C, change_id
        )
        assert events_after_replay == events_after, (
            f"{scenario_id}: exact replay appended an event"
        )
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        for namespace, key in (
            (2, switch_key), (7, scope_key), (4, resource_keys[0]), (4, resource_keys[1])
        ):
            try:
                await blocker2.fetchval("SELECT pg_catalog.pg_advisory_unlock_all()") if namespace == 2 else None
                if namespace != 2:
                    blocker = blocker7 if namespace == 7 else blocker4
                    await blocker.fetchval(
                        "SELECT pg_catalog.pg_advisory_unlock($1,pg_catalog.hashtext($2))",
                        namespace, key,
                    )
            except asyncpg.PostgresError:
                pass
        await contender.close()
        await blocker4.close()
        await blocker7.close()
        await blocker2.close()
