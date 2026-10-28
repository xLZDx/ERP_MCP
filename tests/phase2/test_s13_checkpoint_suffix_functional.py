"""Focused S13 suffix-classifier and migration-026 acceptance.

Run directly (not via pytest):
    .venv/Scripts/python.exe tests/phase2/test_s13_checkpoint_suffix_functional.py

The PostgreSQL portion creates an invocation-owned loopback container and a throwaway
database, applies the complete 001-026 chain, and removes only its owned container/volume.
Coverage is limited to CR152/153's read-only suffix inspection contract; it does not qualify S13.
"""
from __future__ import annotations

import asyncio
import os
import hashlib
import json
from pathlib import Path
from datetime import UTC, datetime
from uuid import uuid4

import asyncpg

from _pg_harness import MIGRATIONS, disposable_cluster, throwaway_db
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.checkpoint import CheckpointRecord
from business_ai_gateway.phase2.change_ledger.lifecycle import (
    LifecycleReason, _classify_checkpoint_suffix,
)
from test_change_ledger_sql import C, L, T, _setup

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_CHAIN = [f"{i:03d}_{name}.sql" for i, name in [
    (19, "ed25519_action_only"), (20, "kill_switch_recovery_guard"),
    (21, "ed25519_consumer_cutover"), (22, "lifecycle_epoch_fence"),
    (23, "lifecycle_activation_cap"), (24, "restore_caller_lock_timeout"),
    (25, "lifecycle_checkpoint_suffix"), (26, "lifecycle_checkpoint_payload_minimization"),
]]
FUNCTION = "change_ledger.lifecycle_checkpoint_suffix(text,text,bigint,text,integer)"
H = "a" * 64


def checkpoint(seq: int = 4, digest: str = H) -> CheckpointRecord:
    return CheckpointRecord(T, C, seq, digest, datetime(2026, 1, 1, tzinfo=UTC),
                            "key", "sig", "sink", "TEST")


def valid_event(seq: int, *, event_type: str = "VERIFY_VERIFIED", event_id=None,
                change_id=None, payload=None, state=None) -> dict:
    payload = {"evidence": "fixture"} if payload is None else payload
    return {
        "seq": seq,
        "event_id": str(event_id or uuid4()),
        "change_id": str(change_id or uuid4()),
        "event_type": event_type,
        "payload_found": payload.get("found") if event_type == "RESOLVE_UNKNOWN" else None,
        "payload_nonempty": bool(payload) if event_type == "VERIFY_VERIFIED" else False,
        "record": state or {
            "execution_state": "APPLIED", "verification_state": "VERIFIED",
            "call_ownership": "PROVEN_FINISHED", "reservation_state": "CONSUMED",
            "dispatch_state": "DISPATCHED",
        },
    }


def suffix(events=None, *, head_seq=None, **overrides):
    events = [] if events is None else events
    value = {
        "tenant_id": T, "company_id": C, "checkpoint_seq": 4,
        "checkpoint_hash": H, "anchor_matches": True,
        "head_seq": (4 + len(events)) if head_seq is None else head_seq,
        "has_more": False, "events": events,
    }
    value.update(overrides)
    return value


def classify(value, *, record=None, count=None):
    record = record or checkpoint()
    count = value.get("head_seq", 4) if count is None and type(value) is dict else (4 if count is None else count)
    return _classify_checkpoint_suffix(Scope(T, C), record, value, count)[0]


def test_python_classifier() -> int:
    checks = 0
    assert classify(suffix()) is None; checks += 1  # exact anchor, empty tail
    one = valid_event(5)
    assert classify(suffix([one])) is None; checks += 1
    two = valid_event(6)
    assert classify(suffix([one, two])) is None; checks += 1

    for event_type in ("APPROVED", "APPLYING", "COMPLETE_SUCCESS",
                       "COMPLETE_PRE_WRITE_REFUSAL", "OPERATOR_RESOLVE"):
        event = valid_event(5, event_type=event_type)
        assert classify(suffix([event])) is LifecycleReason.CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT
        checks += 1
    for found, expected in ((False, LifecycleReason.CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT),
                            (True, LifecycleReason.CHECKPOINT_SUFFIX_UNSUPPORTED),
                            (None, LifecycleReason.CHECKPOINT_SUFFIX_INVALID)):
        event = valid_event(5, event_type="RESOLVE_UNKNOWN", payload={"found": found})
        if found is None:
            event["payload_found"] = None
        assert classify(suffix([event])) is expected; checks += 1
    for event_type in ("EVIDENCE_RECORDED", "UNRECOGNIZED"):
        assert classify(suffix([valid_event(5, event_type=event_type)])) \
            is LifecycleReason.CHECKPOINT_SUFFIX_UNSUPPORTED
        checks += 1

    malformed = [
        (suffix(company_id="OTHER"), LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        (suffix(tenant_id="OTHER"), LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        (suffix(checkpoint_seq=3), LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        (suffix(checkpoint_hash="c" * 64), LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        (suffix(anchor_matches=False), LifecycleReason.CHECKPOINT_NOT_ANCESTOR),
        (suffix(head_seq=6), LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        (suffix([valid_event(6)]), LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        (suffix([valid_event(5)], head_hash="c" * 64), LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        (suffix([valid_event(5)], has_more=True), LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        (suffix([valid_event(5)], head_seq=True), LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        (suffix("bad"), LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
        ({}, LifecycleReason.CHECKPOINT_SUFFIX_INVALID),
    ]
    for value, expected in malformed:
        assert classify(value) is expected, (value, classify(value), expected); checks += 1
    assert classify([]) is LifecycleReason.CHECKPOINT_SUFFIX_INVALID; checks += 1

    # Duplicate event and change IDs, malformed event/payload/state and each joined state gate.
    dup_id = uuid4(); dup_change = uuid4()
    e1 = valid_event(5, event_id=dup_id)
    e2 = valid_event(6, event_id=dup_id)
    assert classify(suffix([e1, e2])) is LifecycleReason.CHECKPOINT_SUFFIX_INVALID; checks += 1
    e1 = valid_event(5, change_id=dup_change)
    e2 = valid_event(6, change_id=dup_change)
    assert classify(suffix([e1, e2])) is LifecycleReason.CHECKPOINT_SUFFIX_INVALID; checks += 1
    for event in (
        None,
        {**valid_event(5), "seq": "5"},
        {**valid_event(5), "event_id": "not-a-uuid"},
        {**valid_event(5), "hash": "must not be exposed"},
        {**valid_event(5), "payload_found": "false"},
        {**valid_event(5), "payload_found": {"found": False}},
        {**valid_event(5), "payload_nonempty": False},
        {**valid_event(5), "event_type": "RESOLVE_UNKNOWN", "payload_nonempty": True},
        {**valid_event(5), "event_type": "EVIDENCE_RECORDED", "payload_found": False},
        {**valid_event(5), "payload": {"raw": "must not be accepted"}},
        {**valid_event(5), "record": None},
        {**valid_event(5), "record": {"execution_state": "APPLIED"}},
    ):
        assert classify(suffix([event])) is LifecycleReason.CHECKPOINT_SUFFIX_INVALID; checks += 1
    for field, bad in (("execution_state", "APPLY_UNKNOWN"),
                       ("verification_state", "FAILED_VERIFY"),
                       ("call_ownership", "POSSIBLY_EXECUTING"),
                       ("reservation_state", "RESERVED"),
                       ("dispatch_state", "PERMITTED")):
        state = valid_event(5)["record"]
        state[field] = bad
        assert classify(suffix([valid_event(5, state=state)])) \
            is LifecycleReason.CHECKPOINT_SUFFIX_INVALID; checks += 1
    assert classify(suffix([valid_event(5, payload={})])) is LifecycleReason.CHECKPOINT_SUFFIX_INVALID
    checks += 1
    over_cap = [valid_event(i) for i in range(5, 134)]
    assert classify(suffix(over_cap, head_seq=133)) \
        is LifecycleReason.CHECKPOINT_SUFFIX_INVALID; checks += 1
    return checks


async def apply_migration(conn: asyncpg.Connection, filename: str) -> None:
    raw = (MIGRATIONS / filename).read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)",
                       hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


async def scoped_suffix(conn, role: str, seq: int, digest: str, *, t=T, c=C,
                        arg_t=None, arg_c=None, limit=128):
    async with conn.transaction():
        await conn.execute(f'SET LOCAL ROLE "{role}"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", t, c)
        value = await conn.fetchval("SELECT change_ledger.lifecycle_checkpoint_suffix($1,$2,$3,$4,$5)",
                                     arg_t or t, arg_c or c, seq, digest, limit)
        return json.loads(value) if isinstance(value, str) else value


async def run_migration_026(db) -> int:
    conn = db.conn
    versions = {r["version"] for r in await conn.fetch("SELECT version FROM living.schema_migrations")}
    assert versions == {f"{n:03d}" for n in range(1, 27)}, (len(versions), sorted(versions))

    grants = await conn.fetchrow(
        "SELECT has_function_privilege('clt_wrk',$1,'EXECUTE') worker, "
        "has_function_privilege('clt_aud',$1,'EXECUTE') auditor, "
        "has_function_privilege('clt_alice',$1,'EXECUTE') requester, "
        "p.prosecdef, p.provolatile, pg_get_userbyid(p.proowner) owner "
        "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='change_ledger' AND p.proname='lifecycle_checkpoint_suffix'", FUNCTION)
    assert tuple(grants) == (True, True, False, True, b"s", "ledger_owner"), tuple(grants)
    public_execute = await conn.fetchval(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "CROSS JOIN LATERAL aclexplode(p.proacl) a "
        "WHERE n.nspname='change_ledger' AND p.proname='lifecycle_checkpoint_suffix' "
        "AND a.grantee=0 AND a.privilege_type='EXECUTE'")
    assert public_execute == 0, public_execute

    # A first event establishes the exact anchor. With no later rows, only worker/auditor can read it.
    anchor = await conn.fetchrow(
        "INSERT INTO change_ledger.events(tenant_id,company_id,event_type,payload,hash) "
        "VALUES($1,$2,'ANCHOR_FIXTURE','{}'::jsonb,$3) RETURNING seq,hash", T, C, H)
    record_count = await conn.fetchval("SELECT count(*) FROM change_ledger.records WHERE tenant_id=$1 AND company_id=$2", T, C)
    empty = await scoped_suffix(conn, "clt_wrk", anchor["seq"], anchor["hash"])
    assert empty == {"tenant_id": T, "company_id": C, "checkpoint_seq": anchor["seq"],
                     "checkpoint_hash": anchor["hash"], "anchor_matches": True,
                     "head_seq": anchor["seq"], "has_more": False, "events": []}, empty
    assert "head_hash" not in empty
    aud = await scoped_suffix(conn, "clt_aud", anchor["seq"], anchor["hash"])
    assert aud == empty
    try:
        await scoped_suffix(conn, "clt_alice", anchor["seq"], anchor["hash"])
    except asyncpg.InsufficientPrivilegeError:
        pass
    else:
        raise AssertionError("requester unexpectedly executed suffix function")
    for seq, digest, limit in ((0, H, 128), (1, "bad", 128), (1, H, 129)):
        try:
            await scoped_suffix(conn, "clt_wrk", seq, digest, limit=limit)
        except asyncpg.PostgresError as error:
            assert "INVALID_ARGUMENT" in str(error), error
        else:
            raise AssertionError("invalid function argument was accepted")
    try:
        await scoped_suffix(conn, "clt_wrk", anchor["seq"], anchor["hash"], arg_t="T-other")
    except asyncpg.PostgresError as error:
        assert "SCOPE_NOT_GRANTED" in str(error), error
    else:
        raise AssertionError("out-of-scope function call was accepted")

    missing = await scoped_suffix(conn, "clt_wrk", anchor["seq"], "c" * 64)
    assert missing["anchor_matches"] is False and missing["head_seq"] == anchor["seq"]
    assert "head_hash" not in missing
    assert missing["events"] == []

    # Exercise the joined record state with a minimal canonical record created by the ledger.
    ledger = L(db)
    change = await ledger.propose(kind="POST", target="m025-linked-record")
    # The successful terminal state cannot be reached through the deliberately disabled lifecycle
    # writer path. Arrange only this joined-state fixture in the disposable superuser database,
    # bypassing user triggers for this one transaction; the API itself remains read-only.
    async with conn.transaction():
        await conn.execute("SET LOCAL session_replication_role='replica'")
        await conn.execute("UPDATE change_ledger.records SET execution_state='APPLIED',verification_state='VERIFIED',"
                           "call_ownership='PROVEN_FINISHED',reservation_state='CONSUMED',dispatch_state='DISPATCHED' "
                           "WHERE change_id=$1", change)
    await conn.execute("INSERT INTO change_ledger.events(tenant_id,company_id,change_id,event_type,payload,hash) "
                       "VALUES($1,$2,$3,'VERIFY_VERIFIED',$4::jsonb,$5)",
                       T, C, change, '{"evidence":"fixture"}', "b" * 64)
    linked = await scoped_suffix(conn, "clt_wrk", anchor["seq"], anchor["hash"])
    assert linked["head_seq"] == anchor["seq"] + len(linked["events"]), linked
    assert "head_hash" not in linked and all("hash" not in event for event in linked["events"])
    verified = linked["events"][-1]
    assert verified["event_type"] == "VERIFY_VERIFIED" and verified["change_id"] == str(change)
    assert "payload" not in verified and "hash" not in verified
    assert "head_hash" not in linked
    assert verified["payload_found"] is None and verified["payload_nonempty"] is True
    assert verified["record"] == {
        "execution_state": "APPLIED", "verification_state": "VERIFIED",
        "call_ownership": "PROVEN_FINISHED", "reservation_state": "CONSUMED",
        "dispatch_state": "DISPATCHED",
    }, verified
    assert any(event["event_type"] == "PROPOSED" and event["change_id"] == str(change)
               for event in linked["events"])

    # Migration 026 exposes only event-specific facts. It must preserve the classifier's
    # T11/T12 distinction while dropping the original JSON bodies from the worker response.
    await conn.execute(
        "INSERT INTO change_ledger.events(tenant_id,company_id,event_type,payload,hash) "
        "VALUES($1,$2,'RESOLVE_UNKNOWN','{\"found\":false,\"private_detail\":\"redacted\"}'::jsonb,$3),"
        "($1,$2,'RESOLVE_UNKNOWN','{\"found\":true,\"private_detail\":\"redacted\"}'::jsonb,$4)",
        T, C, "d" * 64, "e" * 64)
    summaries = await scoped_suffix(conn, "clt_wrk", anchor["seq"], anchor["hash"])
    false_event, true_event = summaries["events"][-2:]
    expected_event_keys = {"seq", "event_id", "change_id", "event_type", "payload_found",
                           "payload_nonempty", "record"}
    assert set(false_event) == expected_event_keys and "payload" not in false_event
    assert false_event["payload_found"] is False and false_event["payload_nonempty"] is False
    assert set(true_event) == expected_event_keys and "payload" not in true_event
    assert true_event["payload_found"] is True and true_event["payload_nonempty"] is False
    assert "head_hash" not in summaries and all("hash" not in event for event in summaries["events"])
    before_false = summaries["events"][-3]
    before_false_hash = await conn.fetchval(
        "SELECT hash FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 AND seq=$3",
        T, C, before_false["seq"])
    false_tail = await scoped_suffix(conn, "clt_wrk", before_false["seq"], before_false_hash)
    false_reason, _, _ = _classify_checkpoint_suffix(
        Scope(T, C), checkpoint(before_false["seq"], before_false_hash), false_tail,
        false_tail["head_seq"])
    assert false_reason is LifecycleReason.CHECKPOINT_SUFFIX_REQUIRES_CHECKPOINT
    false_event_hash = await conn.fetchval(
        "SELECT hash FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 AND seq=$3",
        T, C, false_event["seq"])
    true_tail = await scoped_suffix(conn, "clt_wrk", false_event["seq"], false_event_hash)
    true_reason, _, _ = _classify_checkpoint_suffix(
        Scope(T, C), checkpoint(false_event["seq"], false_event_hash), true_tail,
        true_tail["head_seq"])
    assert true_reason is LifecycleReason.CHECKPOINT_SUFFIX_UNSUPPORTED

    # Non-boolean RESOLVE_UNKNOWN values become SQL NULL; scalar and array VERIFY payloads
    # become payload_nonempty=false. Each summary must fail closed in the Python classifier.
    await conn.execute(
        "INSERT INTO change_ledger.events(tenant_id,company_id,change_id,event_type,payload,hash) "
        "VALUES($1,$2,NULL,'RESOLVE_UNKNOWN','{\"found\":{\"nested\":true},\"private\":\"redacted\"}'::jsonb,$3),"
        "($1,$2,NULL,'RESOLVE_UNKNOWN','{\"found\":\"false\",\"private\":\"redacted\"}'::jsonb,$4),"
        "($1,$2,$5,'VERIFY_VERIFIED','\"scalar evidence\"'::jsonb,$6),"
        "($1,$2,$5,'VERIFY_VERIFIED','[\"array evidence\"]'::jsonb,$7)",
        T, C, "f" * 64, "1" * 64, change, "2" * 64, "3" * 64)
    true_event_hash = await conn.fetchval(
        "SELECT hash FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 AND seq=$3",
        T, C, true_event["seq"])
    malformed_summaries = await scoped_suffix(
        conn, "clt_wrk", true_event["seq"], true_event_hash)
    bad_summary_events = malformed_summaries["events"]
    assert len(bad_summary_events) == 4
    assert all("payload" not in event and set(event) == expected_event_keys
               for event in bad_summary_events)
    assert [event["payload_found"] for event in bad_summary_events] == [None, None, None, None]
    assert [event["payload_nonempty"] for event in bad_summary_events] == [False, False, False, False]
    previous, previous_hash = true_event, true_event_hash
    for event in bad_summary_events:
        isolated_tail = await scoped_suffix(conn, "clt_wrk", previous["seq"], previous_hash)
        reason, _, _ = _classify_checkpoint_suffix(
            Scope(T, C), checkpoint(previous["seq"], previous_hash), isolated_tail,
            isolated_tail["head_seq"])
        assert reason is LifecycleReason.CHECKPOINT_SUFFIX_INVALID, (event, reason)
        previous = event
        previous_hash = await conn.fetchval(
            "SELECT hash FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 AND seq=$3",
            T, C, previous["seq"])

    # More than 128 events must be explicitly marked as truncated; never presented as complete.
    pre_trunc_count = await conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C)
    for _ in range(130):
        await conn.execute("INSERT INTO change_ledger.events(tenant_id,company_id,event_type,payload,hash) "
                           "VALUES($1,$2,'SUFFIX_FIXTURE','{}'::jsonb,$3)", T, C, "c" * 64)
    bounded = await scoped_suffix(conn, "clt_wrk", anchor["seq"], anchor["hash"])
    assert len(bounded["events"]) == 128 and bounded["has_more"] is True
    assert bounded["events"][0]["seq"] == anchor["seq"] + 1
    assert bounded["events"][-1]["seq"] == anchor["seq"] + 128
    assert "head_hash" not in bounded
    assert all("hash" not in event and "payload" not in event for event in bounded["events"])
    after = await conn.fetchrow("SELECT count(*) n,max(hash) h FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C)
    assert after["n"] == pre_trunc_count + 130
    # Snapshot reads themselves must not append events or alter records.
    stable_events = after["n"]
    stable_records = await conn.fetchval("SELECT count(*) FROM change_ledger.records WHERE tenant_id=$1 AND company_id=$2", T, C)
    stable_record_state = await conn.fetchrow(
        "SELECT execution_state,verification_state,call_ownership,reservation_state,dispatch_state "
        "FROM change_ledger.records WHERE tenant_id=$1 AND company_id=$2 AND change_id=$3", T, C, change)
    for _ in range(2):
        await scoped_suffix(conn, "clt_wrk", anchor["seq"], anchor["hash"])
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C) == stable_events
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.records WHERE tenant_id=$1 AND company_id=$2", T, C) == stable_records == record_count + 1
    assert tuple(await conn.fetchrow(
        "SELECT execution_state,verification_state,call_ownership,reservation_state,dispatch_state "
        "FROM change_ledger.records WHERE tenant_id=$1 AND company_id=$2 AND change_id=$3", T, C, change)
    ) == tuple(stable_record_state)

    # Reapplication preserves migration record and function behavior.
    migration_row = await conn.fetchrow("SELECT version,checksum,applied_at FROM living.schema_migrations WHERE version='026'")
    await apply_migration(conn, MIGRATION_CHAIN[-1])
    assert tuple(await conn.fetchrow("SELECT version,checksum,applied_at FROM living.schema_migrations WHERE version='026'")) \
        == tuple(migration_row)
    assert await conn.fetchval("SELECT has_function_privilege('clt_wrk',$1,'EXECUTE')", FUNCTION) is True
    assert await conn.fetchval("SELECT has_function_privilege('clt_alice',$1,'EXECUTE')", FUNCTION) is False
    assert await conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2", T, C) == stable_events
    return 14


async def run() -> None:
    count = test_python_classifier()
    print(f"PASS: Python checkpoint suffix classifier ({count} assertions)", flush=True)
    async with disposable_cluster() as (dsn, container, owner_token):
        async with throwaway_db(dsn) as db:
            # throwaway_db applies and seeds 001-018. Match the established 023-024 fixture order.
            for filename in MIGRATION_CHAIN[:3]:
                await apply_migration(db.conn, filename)
            await _setup(db.conn)
            for filename in MIGRATION_CHAIN[3:]:
                await apply_migration(db.conn, filename)
            sql_checks = await run_migration_026(db)
            print(f"PASS: migration 026 PostgreSQL contract ({sql_checks} grouped checks); "
                  f"owned container {container}; token {owner_token[:8]}", flush=True)


if __name__ == "__main__":
    # Direct runs provision their own disposable cluster, as the sibling migration scripts do.
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    asyncio.run(run())
