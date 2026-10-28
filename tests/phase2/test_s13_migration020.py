"""Focused standalone acceptance harness for S13 migration 020 (never invoke through pytest).

Run: .venv/Scripts/python.exe tests/phase2/test_s13_migration020.py
Creates one invocation-owned loopback PostgreSQL container, applies migrations 001–020,
and removes only that owned container and its anonymous volume.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import pytest

from _pg_harness import FILES, disposable_cluster, seed_basic, throwaway_db
from _ed25519_fixtures import sign_hex
from test_change_ledger_sql import C, ORG, T, L, _setup, exp

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "phase2"
M019 = MIGRATIONS / "019_ed25519_action_only.sql"
M020 = MIGRATIONS / "020_kill_switch_recovery_guard.sql"


async def apply(conn: asyncpg.Connection, path: Path) -> None:
    raw = path.read_bytes()
    await conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
    await conn.execute(raw.decode("utf-8"))


async def call(led: L, role: str, function: str, *args, conn=None, t=T, c=C):
    return await led.call(role, function, *args, conn=conn, t=t, c=c)


async def expect_error(needle: str, awaitable) -> None:
    try:
        await awaitable
    except asyncpg.PostgresError as error:
        assert needle in str(error), f"expected {needle}, got {error!s}"
        return
    raise AssertionError(f"expected database error containing {needle!r}")


async def add_base(conn, name: str) -> None:
    await conn.execute(
        "INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,target_class) "
        "VALUES($1,$2,$3,$4,'DISPOSABLE_CLONE') ON CONFLICT DO NOTHING", T, C, name, ORG)


async def sweep(led: L, **params):
    policy_keys = {"claim_ttl_seconds", "permit_ttl_seconds", "t12_window_seconds", "t12_max_attempts",
                   "anchor_gap_window_seconds", "verify_max_attempts"}
    policy = {key: params.pop(key) for key in list(params) if key in policy_keys}
    old_policy = await led.conn.fetchval("SELECT params FROM change_ledger.sweep_policy WHERE tenant_id=$1 AND company_id=$2",
                                         T, C)
    if policy:
        await led.conn.execute("INSERT INTO change_ledger.sweep_policy(tenant_id,company_id,params,updated_by) "
            "VALUES($1,$2,$3::jsonb,'s13-test-fixture') ON CONFLICT(tenant_id,company_id) DO UPDATE "
            "SET params=EXCLUDED.params", T, C, json.dumps(policy))
    result = await call(led, "clt_wrk", "recover_sweep", json.dumps(params))
    if policy:
        if old_policy is None:
            await led.conn.execute("DELETE FROM change_ledger.sweep_policy WHERE tenant_id=$1 AND company_id=$2", T, C)
        else:
            await led.conn.execute("UPDATE change_ledger.sweep_policy SET params=$3 WHERE tenant_id=$1 AND company_id=$2",
                                   T, C, old_policy)
    return json.loads(result) if isinstance(result, str) else result


async def seed_failure(led: L, subject, stage: str) -> None:
    await led.conn.execute(
        "INSERT INTO change_ledger.sweep_failures(tenant_id,company_id,subject_id,stage,last_sqlstate,last_error) "
        "VALUES($1,$2,$3,$4,'P0001','fixture failure') ON CONFLICT(subject_id,stage) DO UPDATE "
        "SET failures=1,last_sqlstate='P0001',last_error='fixture failure'", T, C, subject, stage)


async def run_api_and_clean_off(led: L) -> None:
    for signature, result in (
        ("change_ledger.kill_switch(text,text,text)", "text"),
        ("change_ledger.recover_sweep(text,text,jsonb)", "jsonb"),
        ("change_ledger.recover_sweep(text,text)", "integer"),
    ):
        actual = await led.conn.fetchval("SELECT pg_get_function_result($1::regprocedure)", signature)
        assert actual == result, (signature, actual)
    assert await led.conn.fetchval("SELECT has_function_privilege('clt_dave',"
        "'change_ledger.kill_switch(text,text,text)','EXECUTE')")
    assert not await led.conn.fetchval("SELECT has_function_privilege('clt_wrk',"
        "'change_ledger.kill_switch(text,text,text)','EXECUTE')")
    assert await led.conn.fetchval("SELECT has_function_privilege('clt_wrk',"
        "'change_ledger.recover_sweep(text,text,jsonb)','EXECUTE')")
    assert not await led.conn.fetchval("SELECT has_function_privilege('clt_dave',"
        "'change_ledger.recover_sweep(text,text,jsonb)','EXECUTE')")
    assert await led.conn.fetchval("SELECT has_function_privilege('clt_wrk',"
        "'change_ledger.recover_sweep(text,text)','EXECUTE')")

    await expect_error("SCHEMA_INVALID", call(led, "clt_dave", "kill_switch", "BAD_MODE"))
    await expect_error("permission denied", call(led, "clt_wrk", "kill_switch", "STOP_ADMIT"))
    await expect_error("SCOPE_NOT_GRANTED", call(led, "clt_dave", "kill_switch", "STOP_ADMIT", t="T2", c="C2"))
    await expect_error("SCOPE_NOT_GRANTED", call(led, "clt_wrk", "recover_sweep", "{}", t="T2", c="C2"))

    assert await call(led, "clt_dave", "kill_switch", "STOP_ADMIT") == "STOP_ADMIT"
    before_runs = await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_runs")
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "OFF"
    after_runs = await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_runs")
    assert after_runs == before_runs + 1
    assert await led.conn.fetchval("SELECT mode FROM change_ledger.kill_switch_state WHERE tenant_id=$1 AND company_id=$2",
                                   T, C) == "OFF"
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "OFF"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_runs") == after_runs
    print("PASS: signatures/grants, invalid mode/scope/role, clean STOP->OFF, repeated OFF")


async def run_each_active_hold_blocks_off(led: L) -> None:
    for cause in ("CALL_OWNERSHIP", "FAILED_VERIFY_HALT", "ANCHOR_GAP", "RLC_UNCLEAN"):
        await call(led, "clt_dave", "kill_switch", "STOP_ADMIT")
        hold_id = uuid4()
        await led.conn.execute(
            "INSERT INTO change_ledger.holds(hold_id,tenant_id,company_id,base_fingerprint,cause) "
            "VALUES($1,$2,$3,'base-1',$4)", hold_id, T, C, cause)
        assert await call(led, "clt_dave", "kill_switch", "OFF") == "STOP_ADMIT", cause
        event = await led.conn.fetchrow("SELECT payload FROM change_ledger.events WHERE event_type='KILL_SWITCH' "
            "ORDER BY seq DESC LIMIT 1")
        payload = event["payload"] if isinstance(event["payload"], dict) else json.loads(event["payload"])
        assert payload["outcome"] == "BLOCKED" and payload["has_unresolved"] is True, (cause, payload)
        await led.conn.execute("UPDATE change_ledger.holds SET released_at=clock_timestamp() WHERE hold_id=$1", hold_id)
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "OFF"
    print("PASS: each allowed active hold cause independently retains STOP, including RLC_UNCLEAN")


async def install_record_poison(conn, cid, trigger_name: str, function_name: str, condition: str) -> None:
    await conn.execute(f"CREATE FUNCTION public.{function_name}() RETURNS trigger LANGUAGE plpgsql AS $$ "
        f"BEGIN IF {condition} THEN RAISE EXCEPTION 'S13_TEST_POISON'; END IF; RETURN NEW; END $$")
    await conn.execute(f"CREATE TRIGGER {trigger_name} BEFORE UPDATE ON change_ledger.records "
        f"FOR EACH ROW EXECUTE FUNCTION public.{function_name}()")


async def remove_record_poison(conn, trigger_name: str, function_name: str) -> None:
    await conn.execute(f"DROP TRIGGER {trigger_name} ON change_ledger.records")
    await conn.execute(f"DROP FUNCTION public.{function_name}()")


async def run_partial_failure_t9_retry_and_repair(led: L) -> None:
    await add_base(led.conn, "s13-poison")
    bad, token = await led.approved(request_id="s13-poison", base="s13-poison"), None
    token = await led.claimed(bad)
    good, good_token, _ = await led.dispatched(request_id="s13-t9", base="base-1")
    await led.conn.execute("UPDATE change_ledger.call_deadlines SET hard_deadline_at=now()-interval '1 second' "
                           "WHERE change_id=$1", good)
    await install_record_poison(led.conn, bad, "s13_poison_claim_trigger", "s13_poison_claim",
        f"OLD.change_id='{bad}'::uuid AND NEW.authorization_state='APPROVED'")
    await call(led, "clt_dave", "kill_switch", "STOP_ADMIT")
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "STOP_ADMIT"
    event = await led.conn.fetchrow("SELECT payload FROM change_ledger.events WHERE event_type='KILL_SWITCH' "
                                    "ORDER BY seq DESC LIMIT 1")
    payload = event["payload"] if isinstance(event["payload"], dict) else json.loads(event["payload"])
    assert payload["outcome"] == "BLOCKED" and payload["failed_count"] == 1
    assert payload["has_unresolved"] is True and payload["selected_counts"]["T12"] == 0
    state = await led.rec(good)
    assert state["execution_state"] == "APPLY_UNKNOWN" and state["call_ownership"] == "POSSIBLY_EXECUTING"
    failure = await led.conn.fetchrow("SELECT failures,last_sqlstate,last_error FROM change_ledger.sweep_failures "
                                      "WHERE subject_id=$1 AND stage='T5x'", bad)
    assert failure and failure["failures"] == 1 and failure["last_sqlstate"] == "P0001"
    assert "S13_TEST_POISON" in failure["last_error"]
    assert await led.conn.fetchval("SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", token["token_id"]) == "ISSUED"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1 "
                                   "AND event_type='HARD_DEADLINE_UNKNOWN'", good) == 1
    assert await led.conn.fetchval("SELECT mode FROM change_ledger.kill_switch_state WHERE tenant_id=$1 AND company_id=$2",
                                   T, C) == "STOP_ADMIT"
    await remove_record_poison(led.conn, "s13_poison_claim_trigger", "s13_poison_claim")

    # Retry executes the now-repaired claim, but the independently unresolved T9 item keeps STOP active.
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "STOP_ADMIT"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='T5x'", bad) == 0
    assert await led.conn.fetchval("SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", token["token_id"]) == "SUPERSEDED"
    assert await led.resolve_unknown(good, False, proof="b") == "FAILED_APPLY"
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "OFF"
    print("PASS: poisoned item failure and T9 partial progress commit; repair/retry clears failure before OFF")


async def run_t9_t12_delays_and_cleanup_stages(led: L) -> None:
    # Delayed T12: selection may inspect the item, but no attempt/failure cleanup is allowed before due time.
    unk, _, _ = await led.unknown(request_id="s13-delayed-t12", base="base-2")
    await led.conn.execute("INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,"
        "next_attempt_at) VALUES($1,$2,$3,'RESOLVE',now(),now()+interval '1 hour')", T, C, unk)
    await seed_failure(led, unk, "T12")
    cid, tok, _ = await led.dispatched(request_id="s13-delayed-verify", base="base-3")
    assert await led.complete(cid, tok["generation"], "SUCCESS") == "APPLIED"
    await led.conn.execute("INSERT INTO change_ledger.sweep_counters(tenant_id,company_id,subject_id,kind,started_at,"
        "next_attempt_at) VALUES($1,$2,$3,'VERIFY',now(),now()+interval '1 hour')", T, C, cid)
    await seed_failure(led, cid, "VERIFY")
    await call(led, "clt_dave", "kill_switch", "STOP_ADMIT")
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "STOP_ADMIT"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='T12'", unk) == 1
    assert await led.conn.fetchval("SELECT execution_state FROM change_ledger.records WHERE change_id=$1", unk) == "APPLY_UNKNOWN"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='VERIFY'", cid) == 1
    assert await led.conn.fetchval("SELECT verification_state FROM change_ledger.records WHERE change_id=$1", cid) == "NOT_VERIFIED"

    # Once due, a durable T12 attempt and VERIFY attempt clear their stage failures; then resolve the real outcomes.
    await led.conn.execute("UPDATE change_ledger.sweep_counters SET next_attempt_at=now()-interval '1 second' "
                           "WHERE subject_id=$1 AND kind IN ('RESOLVE','VERIFY')", unk)
    await led.conn.execute("UPDATE change_ledger.sweep_counters SET next_attempt_at=now()-interval '1 second' "
                           "WHERE subject_id=$1 AND kind='VERIFY'", cid)
    await sweep(led, t12_interval_seconds=0, t12_jitter_seconds=0, verify_interval_seconds=0)
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='T12'", unk) == 0
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='VERIFY'", cid) == 0
    assert await led.resolve_unknown(unk, False, proof="b") == "FAILED_APPLY"
    assert await led.verify(cid, True) == "VERIFIED"
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "OFF"

    # REVOKE_STALE: selection without a stale dependency preserves the row; terminal revoke clears it on retry.
    stale = await led.validated(request_id="s13-revoke-stale", base="base-4")
    await led.call("clt_alice", "add_epoch_dependency", stale, "source:s1")
    nonce = await led.call("clt_bob", "issue_approval_nonce", stale)
    await led.call("clt_bob", "approve", stale, nonce, await led.approval_digest(stale))
    await seed_failure(led, stale, "REVOKE_STALE")
    assert await led.call("clt_wrk", "revoke_stale") == 0
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='REVOKE_STALE'", stale) == 1
    await led.call("clt_dave", "bump_epoch", "source:s1")
    await install_record_poison(led.conn, stale, "s13_poison_revoke_trigger", "s13_poison_revoke",
        f"OLD.change_id='{stale}'::uuid AND NEW.authorization_state='VOIDED'")
    assert await led.call("clt_wrk", "revoke_stale") == 0
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='REVOKE_STALE'", stale) == 1
    await remove_record_poison(led.conn, "s13_poison_revoke_trigger", "s13_poison_revoke")
    assert await led.call("clt_wrk", "revoke_stale") == 1
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='REVOKE_STALE'", stale) == 0
    assert (await led.rec(stale))["authorization_state"] == "VOIDED"

    # GAP_BOUND: the failed item stays while not due, then clears only with the bound counter and audit event.
    await call(led, "clt_wrk", "declare_anchor_gap", "base-5", "{}")
    hold = await led.conn.fetchval("SELECT hold_id FROM change_ledger.holds WHERE base_fingerprint='base-5' "
                                   "AND cause='ANCHOR_GAP' AND released_at IS NULL")
    await seed_failure(led, hold, "GAP_BOUND")
    await sweep(led)  # the default bound window has not elapsed
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='GAP_BOUND'", hold) == 1
    await led.conn.execute("UPDATE change_ledger.holds SET opened_at=now()-interval '1 hour' WHERE hold_id=$1", hold)
    # Poison the counter insert once; its failure must remain and be observable.
    await led.conn.execute("CREATE FUNCTION public.s13_poison_gap_bound() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN IF NEW.subject_id='" + str(hold) + "'::uuid AND NEW.kind='ANCHOR_GAP' THEN "
        "RAISE EXCEPTION 'S13_GAP_BOUND_POISON'; END IF; RETURN NEW; END $$")
    await led.conn.execute("CREATE TRIGGER s13_poison_gap_bound BEFORE INSERT ON change_ledger.sweep_counters "
                           "FOR EACH ROW EXECUTE FUNCTION public.s13_poison_gap_bound()")
    report = await sweep(led, anchor_gap_window_seconds=0)
    assert report["FAILED"] and any(f["stage"] == "GAP_BOUND" for f in report["FAILED"])
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='GAP_BOUND'", hold) == 1
    await led.conn.execute("DROP TRIGGER s13_poison_gap_bound ON change_ledger.sweep_counters")
    await led.conn.execute("DROP FUNCTION public.s13_poison_gap_bound()")
    report = await sweep(led, anchor_gap_window_seconds=0)
    assert report["failed_count"] == 0
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_failures WHERE subject_id=$1 AND stage='GAP_BOUND'", hold) == 0
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_counters WHERE subject_id=$1 "
                                   "AND kind='ANCHOR_GAP' AND close_reason='BOUND_EXCEEDED'", hold) == 1
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE event_type='ANCHOR_GAP_BOUND_EXCEEDED' "
                                   "AND payload->>'hold_id'=$1", str(hold)) == 1
    await led.checkpoint()
    assert await led.call("clt_dave", "release_hold", hold, '{"store_accepted":true}') is not None
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "OFF"
    print("PASS: delayed T12/VERIFY remain unresolved; REVOKE_STALE and GAP_BOUND failures clear only after terminal evidence")


async def run_batch_bound_and_concurrent_serialization(led: L) -> None:
    # Default effective batch_size is 100. Create 101 actual issued claims with distinct base locks.
    bases = [f"s13-batch-{i:03d}" for i in range(101)]
    await led.conn.executemany("INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,"
        "organization_ref,target_class) VALUES($1,$2,$3,$4,'DISPOSABLE_CLONE')",
        [(T, C, base, ORG) for base in bases])
    ids = []
    for i, base in enumerate(bases):
        cid = await led.approved(request_id=f"s13-batch-{i}", base=base)
        await led.claimed(cid)
        ids.append(cid)
    await call(led, "clt_dave", "kill_switch", "STOP_ADMIT")
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "STOP_ADMIT"
    first = await led.conn.fetchrow("SELECT payload FROM change_ledger.events WHERE event_type='KILL_SWITCH' "
        "ORDER BY seq DESC LIMIT 1")
    payload = first["payload"] if isinstance(first["payload"], dict) else json.loads(first["payload"])
    assert payload["outcome"] == "BLOCKED" and payload["has_more_eligible"] is True
    assert payload["selected_counts"]["T5x"] == 100
    released = await led.conn.fetchval("SELECT count(*) FROM change_ledger.claim_tokens WHERE change_id=ANY($1) "
                                       "AND state='SUPERSEDED'", ids)
    assert released == 100
    assert await call(led, "clt_dave", "kill_switch", "OFF") == "OFF"
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.claim_tokens WHERE change_id=ANY($1) "
                                   "AND state='SUPERSEDED'", ids) == 101

    # Two live recovery calls: a scoped test trigger holds the first call inside its selected T3 item;
    # the second call must wait for the migration's sweep advisory lock and then see no duplicate work.
    await add_base(led.conn, "s13-concurrent")
    expiring = await led.validated(request_id="s13-concurrent", base="s13-concurrent")
    await led.conn.execute("UPDATE change_ledger.records SET created_at=now()-interval '2 hours', "
                           "expires_at=now()-interval '1 second' WHERE change_id=$1", expiring)
    await led.conn.execute("CREATE FUNCTION public.s13_pause_t3() RETURNS trigger LANGUAGE plpgsql AS $$ "
        f"BEGIN IF OLD.change_id='{expiring}'::uuid AND NEW.lifecycle='EXPIRED_QUEUED' THEN PERFORM pg_sleep(1); "
        "END IF; RETURN NEW; END $$")
    await led.conn.execute("CREATE TRIGGER s13_pause_t3 BEFORE UPDATE ON change_ledger.records "
                           "FOR EACH ROW EXECUTE FUNCTION public.s13_pause_t3()")
    conn_a = await led.db.connect()
    conn_b = await led.db.connect()
    try:
        pid_b = await conn_b.fetchval("SELECT pg_backend_pid()")
        task_a = asyncio.create_task(sweep(L(SimpleNamespace(conn=conn_a)), batch_size=10))
        for _ in range(200):
            if await led.conn.fetchval("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE state='active' "
                "AND query ILIKE '%recover_sweep%' AND wait_event='PgSleep')"):
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("first recover_sweep did not enter the delay trigger")
        task_b = asyncio.create_task(sweep(L(SimpleNamespace(conn=conn_b)), batch_size=10))
        for _ in range(200):
            if await led.conn.fetchval("SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=$1", pid_b):
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("second recover_sweep did not wait on the serialized sweep lock")
        first_result, second_result = await asyncio.gather(task_a, task_b)
        assert first_result["T3"] == [str(expiring)] and second_result["T3"] == []
        assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE change_id=$1 "
            "AND event_type='EXPIRED'", expiring) == 1
    finally:
        await conn_a.close()
        await conn_b.close()
        await led.conn.execute("DROP TRIGGER s13_pause_t3 ON change_ledger.records")
        await led.conn.execute("DROP FUNCTION public.s13_pause_t3()")
    print("PASS: 100-item bounded claim batch retains STOP for 101st item; concurrent sweeps serialize")


async def main() -> int:
    os.environ["ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS"] = "1"
    async with disposable_cluster() as (dsn, container_name, _token):
        async with throwaway_db(dsn) as db:
            await _setup(db.conn)
            await apply(db.conn, M019)
            await apply(db.conn, M020)
            for version in ("019", "020"):
                found = await db.conn.fetchval("SELECT count(*) FROM living.schema_migrations WHERE version=$1", version)
                assert found == 1, (version, found)
            led = L(db)
            await run_api_and_clean_off(led)
            await run_each_active_hold_blocks_off(led)
            await run_partial_failure_t9_retry_and_repair(led)
            await run_t9_t12_delays_and_cleanup_stages(led)
            await run_batch_bound_and_concurrent_serialization(led)
    print(f"PASS: S13 migration 020 focused acceptance on owned PostgreSQL container {container_name}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except pytest.skip.Exception as unavailable:
        print(f"NOT_RUN: {unavailable}")
        raise SystemExit(0)
