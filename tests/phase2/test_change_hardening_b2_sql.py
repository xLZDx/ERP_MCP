"""Focused PostgreSQL tests for db/phase2/008_change_hardening_b.sql, round 2: findings B4 and B5 of
docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md (batch B).

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database with all migrations applied and the actors of
test_change_ledger_sql._setup. Superuser access arranges only what no API can produce (a restored older ledger, a
back-dated deadline, a tampered lock row) and reads results; it never removes a guard.
"""
import asyncio
import json
import re
import uuid
from pathlib import Path

import asyncpg
import pytest
from _pg_harness import fails, require_dsn, throwaway_db
from test_change_ledger_sql import C, ORG, T, L, _failed_parent, _repair, _setup

pytestmark = pytest.mark.integration

MIGRATION = Path(__file__).resolve().parents[2] / "db" / "phase2" / "008_change_hardening_b.sql"
FAST = {"t12_interval_seconds": 0, "t12_jitter_seconds": 0, "verify_interval_seconds": 0}
CONTRACT_KEYS = ["claim_ttl_seconds", "permit_ttl_seconds", "t12_window_seconds", "t12_max_attempts",
                 "anchor_gap_window_seconds", "verify_max_attempts"]
EXPECTED_REFUSALS = ("TICKET_SUPERSEDED", "FORBIDDEN_TRANSITION", "PERMIT_MISSING", "APPROVAL_MISSING",
                     "LOCK_BUSY", "BASE_HOLD")


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


async def sweep(led, conn=None, **params):
    got = await led.call("clt_wrk", "recover_sweep", json.dumps(params), conn=conn)
    return json.loads(got) if isinstance(got, str) else got


async def add_base(led, name):
    await led.conn.execute(
        "INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,target_class) "
        "VALUES($1,$2,$3,$4,'DISPOSABLE_CLONE')", T, C, name, ORG)


async def wait_blocked(led, pid, seconds=30):
    """Wait on the observable condition: the backend `pid` waits for a lock."""
    for _ in range(int(seconds / 0.05)):
        if await led.conn.fetchval("SELECT wait_event_type='Lock' FROM pg_stat_activity WHERE pid=$1", pid):
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the session never blocked on a lock")


async def event_count(led, etype, cid=None):
    return await led.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE event_type=$1 AND ($2::uuid IS NULL OR change_id=$2)",
        etype, cid)


# ============================================================================ B4
async def restored_ledger(led):
    """Anchor an advanced head, 'restore' an older ledger snapshot (trailing events deleted as superuser: fixture
    setup), run check_anchor and record a fresh REAL checkpoint of the RESTORED head. Returns the anchored head and
    the lost events (so a test can replay them as the reconciliation)."""
    await led.approved(request_id="an1", base="base-1")
    await led.checkpoint()
    head = await led.call("clt_wrk", "ledger_head")
    await led.approved(request_id="an2", base="base-2")
    await led.checkpoint()
    anchored = await led.call("clt_wrk", "ledger_head")
    assert anchored["seq"] > head["seq"]
    lost = await led.conn.fetch("SELECT change_id,event_type,payload FROM change_ledger.events WHERE seq>$1 "
                                "ORDER BY seq", head["seq"])
    await led.conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable")
    await led.conn.execute("DELETE FROM change_ledger.events WHERE seq>$1", head["seq"])
    await led.conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable")
    got = await led.call("clt_wrk", "check_anchor", anchored["seq"], anchored["head_hash"])
    assert got["ok"] is False and got["holds_opened"] > 0
    await led.checkpoint()                                      # a fresh REAL checkpoint of the restored head
    return head, anchored, lost


async def hold_of(led, base):
    return await led.conn.fetchval("SELECT hold_id FROM change_ledger.holds WHERE base_fingerprint=$1 AND "
                                   "cause='ANCHOR_GAP' AND released_at IS NULL", base)


async def test_b4_the_hold_remembers_the_external_head_and_a_fresh_checkpoint_does_not_release_it(led):
    head, anchored, _ = await restored_ledger(led)
    rows = await led.conn.fetch("SELECT ext_seq, ext_head_hash FROM change_ledger.holds WHERE cause='ANCHOR_GAP'")
    assert rows and all((r["ext_seq"], r["ext_head_hash"]) == (anchored["seq"], anchored["head_hash"]) for r in rows)
    hold = await hold_of(led, "base-1")
    # the restored head is checkpointed REAL after the hold opened and the chain is fine: the 006 release rule alone
    # would have accepted this; the lost head was never reconciled
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.checkpoints WHERE sink_kind='REAL' AND "
                                   "ledger_seq=$1", head["seq"]) >= 1
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True
    await fails("AUDIT_UNAVAILABLE", led.call("clt_dave", "release_hold", hold, '{"store_accepted":true}'))
    assert await hold_of(led, "base-1") == hold
    fresh = await led.approved(request_id="an3", base="base-3")
    await fails("BASE_HOLD", led.claimed(fresh, key="3" * 64))


async def test_b4_a_second_detection_keeps_the_newest_external_head_on_the_open_holds(led):
    _, anchored, _ = await restored_ledger(led)
    await led.call("clt_wrk", "check_anchor", anchored["seq"] + 5, "e" * 64)
    seqs = {r["ext_seq"] for r in await led.conn.fetch(
        "SELECT ext_seq FROM change_ledger.holds WHERE cause='ANCHOR_GAP' AND released_at IS NULL")}
    assert seqs == {anchored["seq"] + 5}
    await fails("SCHEMA_INVALID", led.call("clt_wrk", "check_anchor", 5, "nothex"))
    await fails("SCHEMA_INVALID", led.call("clt_wrk", "check_anchor", 0, "a" * 64))


async def test_b4_replayed_history_that_contains_the_exact_event_releases_the_hold(led):
    head, anchored, lost = await restored_ledger(led)
    hold = await hold_of(led, "base-1")
    # the lost history is restored from the external archive (fixture): drop what the restored ledger appended since
    # (the ANCHOR_GAP event) and replay the lost events; the chain is deterministic, so the hashes come back
    await led.conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable")
    await led.conn.execute("DELETE FROM change_ledger.events WHERE seq>$1", head["seq"])
    await led.conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable")
    for r in lost:
        await led.conn.execute("INSERT INTO change_ledger.events(tenant_id,company_id,change_id,event_type,payload) "
                               "VALUES($1,$2,$3,$4,$5::jsonb)", T, C, r["change_id"], r["event_type"], r["payload"])
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE seq=$1 AND hash=$2",
                                   anchored["seq"], anchored["head_hash"]) == 1
    # the checkpoint of the restored ledger covered the ANCHOR_GAP event that no longer exists: it does not match now
    await fails("CHECKPOINT_UNAVAILABLE", led.call("clt_dave", "release_hold", hold, '{"store_accepted":true}'))
    await led.checkpoint()                                        # a REAL read-back checkpoint of the replayed head
    ts = await led.call("clt_dave", "release_hold", hold, '{"store_accepted":true}')
    assert ts is not None and await hold_of(led, "base-1") is None


async def test_b4_two_person_release_needs_an_independent_witness_with_evidence(led):
    _, anchored, _ = await restored_ledger(led)
    hold, other = await hold_of(led, "base-1"), await hold_of(led, "base-2")
    good = {"class": "a", "reconciliation": "lost events accounted from the archive of the external sink",
            "ext_seq": anchored["seq"], "ext_head_hash": anchored["head_hash"]}
    await fails("permission denied", led.sql("clt_wrk", "SELECT change_ledger.anchor_gap_cosign('T1','C1',"
                                             f"'{hold}','{json.dumps(good)}'::jsonb)"))
    for bad in (None, {**good, "class": "c"}, {**good, "reconciliation": ""}, {**good, "ext_seq": 1},
                {**good, "ext_head_hash": "0" * 64}):
        await fails("COMPLETION_PROOF_MISSING", led.call("clt_erin", "anchor_gap_cosign", hold,
                                                         None if bad is None else json.dumps(bad)))
    cos = await led.call("clt_erin", "anchor_gap_cosign", hold, json.dumps(good))
    # the release names the cosign; evidence without one stays refused, a malformed id is SCHEMA_INVALID
    await fails("AUDIT_UNAVAILABLE", led.call("clt_dave", "release_hold", hold, '{"store_accepted":true}'))
    await fails("SCHEMA_INVALID", led.call("clt_dave", "release_hold", hold, '{"two_person_cosign":"x"}'))
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "release_hold", hold,
                                                    json.dumps({"two_person_cosign": str(uuid.uuid4())})))
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "release_hold", other,
                                                    json.dumps({"two_person_cosign": str(cos)})))   # another hold's
    # the same person cannot cosign and release (dave is operator and witness)
    own = await led.call("clt_dave", "anchor_gap_cosign", other, json.dumps(good))
    await fails("APPROVER_NOT_INDEPENDENT", led.call("clt_dave", "release_hold", other,
                                                     json.dumps({"two_person_cosign": str(own)})))
    assert await hold_of(led, "base-2") == other
    ts = await led.call("clt_dave", "release_hold", hold, json.dumps({"two_person_cosign": str(cos)}))
    assert ts is not None and await hold_of(led, "base-1") is None
    assert await event_count(led, "HOLD_RELEASED") == 1
    ev = json.loads(await led.conn.fetchval("SELECT payload FROM change_ledger.events WHERE event_type="
                                            "'HOLD_RELEASED'"))
    assert ev["two_person"] is True
    # a cosign is single-use
    await fails("COMPLETION_PROOF_MISSING", led.call("clt_dave", "release_hold", other,
                                                    json.dumps({"two_person_cosign": str(cos)})))
    assert await led.conn.fetchval("SELECT consumed_at IS NOT NULL FROM change_ledger.hold_cosigns WHERE "
                                   "cosign_id=$1", cos)


# ============================================================================ B5 lock order
def test_b5_the_header_documents_one_lock_order():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "see section B5 (added later)" not in text
    head = text.split("BEGIN;", 1)[0]
    assert "LOCK ORDER" in head and "CLAIM TOKEN BEFORE RECORD" in head and "CHAIN advisory lock" in head
    assert re.search(r"-- B4 |--  B4 ", head) and re.search(r"--  B5 ", head)


async def test_b5_a_sweep_never_holds_the_chain_while_it_waits_for_a_row_a_complete_call_holds(led):
    """Deterministic form of the inversion: a writer-side call holds the record row of the T9 item and is about to
    append (chain lock); the sweep has an earlier T6c item to process. Chain-then-row (old order) deadlocks here."""
    await add_base(led, "lo-x")
    await add_base(led, "lo-z")
    x, _, _ = await led.dispatched(request_id="lo1", base="lo-x")
    z, _, _, _ = await led.permitted(request_id="lo2", base="lo-z")
    await led.conn.execute("UPDATE change_ledger.call_deadlines SET hard_deadline_at=now()-interval '1 second' "
                           "WHERE change_id=$1", x)
    await led.conn.execute("UPDATE change_ledger.dispatch_permits SET expires_at=now()-interval '1 second' "
                           "WHERE change_id=$1 AND state='PERMITTED'", z)
    holder, runner = await led.db.connect(), await led.db.connect()
    try:
        tr = holder.transaction()
        await tr.start()
        await holder.execute("SELECT 1 FROM change_ledger.records WHERE change_id=$1 FOR UPDATE", x)
        pid = await runner.fetchval("SELECT pg_backend_pid()")
        task = asyncio.create_task(sweep(led, conn=runner))
        await wait_blocked(led, pid)
        # the holder now needs the chain lock (as complete / begin_apply do after their row locks)
        await holder.execute("SELECT change_ledger.append_event('T1','C1',NULL,'FIXTURE_PROBE','{}'::jsonb)")
        await tr.commit()
        got = await asyncio.wait_for(task, 30)
    finally:
        await holder.close()
        await runner.close()
    assert got["T6c"] == [str(z)] and got["T9"] == [str(x)] and got["FAILED"] == []
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True


async def test_b5_register_principal_and_bump_epoch_take_the_epoch_row_before_the_chain(led):
    await led.call("clt_dave", "bump_epoch", "principal:clt_mallory")
    holder, runner = await led.db.connect(), await led.db.connect()
    try:
        tr = holder.transaction()
        await tr.start()
        await holder.execute("UPDATE change_ledger.epochs SET value=value WHERE epoch_key='principal:clt_mallory'")
        pid = await runner.fetchval("SELECT pg_backend_pid()")
        task = asyncio.create_task(led.call("clt_dave", "register_principal", "clt_mallory", "person-clt_mallory",
                                            ["requester"], True, conn=runner))
        await wait_blocked(led, pid)
        await holder.execute("SELECT change_ledger.append_event('T1','C1',NULL,'FIXTURE_PROBE','{}'::jsonb)")
        await tr.commit()
        value = await asyncio.wait_for(task, 30)
    finally:
        await holder.close()
        await runner.close()
    assert value == 2
    types = [r["event_type"] for r in await led.conn.fetch(
        "SELECT event_type FROM change_ledger.events WHERE event_type IN ('PRINCIPAL_REGISTERED','EPOCH_BUMPED') "
        "ORDER BY seq DESC LIMIT 2")]
    assert types == ["EPOCH_BUMPED", "PRINCIPAL_REGISTERED"]
    # and under plain concurrency
    a, b = await led.db.connect(), await led.db.connect()
    try:
        for _ in range(10):
            res = await asyncio.gather(
                led.call("clt_dave", "bump_epoch", "principal:clt_mallory", conn=a),
                led.call("clt_dave", "register_principal", "clt_mallory", "person-clt_mallory", ["requester"], True,
                         conn=b), return_exceptions=True)
            assert not [r for r in res if isinstance(r, Exception)], res
    finally:
        await a.close()
        await b.close()
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True


async def test_b5_sweep_concurrent_with_complete_calls_and_a_begin_apply_replay_never_deadlocks(led):
    rounds = 20
    conns = [await led.db.connect() for _ in range(4)]
    try:
        for r in range(rounds):
            names = [f"s{r}-{i}" for i in range(3)]
            for name in names:
                await add_base(led, name)
            x1, t1, _ = await led.dispatched(request_id=f"x1-{r}", base=names[0])
            x2, t2, _ = await led.dispatched(request_id=f"x2-{r}", base=names[1])
            z, zt, zcall, _ = await led.permitted(request_id=f"z-{r}", base=names[2])
            comp1 = await led.evidence(x1, "COMPLETION_PROOF", {"class": "a", "result_returned": True},
                                       role="clt_wri", gen=t1["generation"])
            comp2 = await led.evidence(x2, "COMPLETION_PROOF", {"class": "a", "result_returned": True},
                                       role="clt_wri", gen=t2["generation"])
            await led.conn.execute("UPDATE change_ledger.call_deadlines SET hard_deadline_at=now()-interval "
                                   "'1 second' WHERE change_id = ANY($1)", [x1, x2])
            await led.conn.execute("UPDATE change_ledger.dispatch_permits SET expires_at=now()-interval '1 second' "
                                   "WHERE change_id=$1 AND state='PERMITTED'", z)
            res = await asyncio.gather(
                sweep(led, conn=conns[0]),
                led.call("clt_wri", "complete_signed", x1, t1["generation"], "SUCCESS", comp1, conn=conns[1]),
                led.call("clt_wri", "complete_signed", x2, t2["generation"], "SUCCESS", comp2, conn=conns[2]),
                led.call("clt_wri", "begin_apply", zt["token_id"], zcall, "host-1", "sess-1", conn=conns[3]),
                return_exceptions=True)
            for item in res:
                if isinstance(item, Exception):
                    assert not isinstance(item, asyncpg.DeadlockDetectedError), f"round {r}: {item!r}"
                    assert any(code in str(item) for code in EXPECTED_REFUSALS), f"round {r}: {item!r}"
            assert isinstance(res[0], dict) and res[0]["FAILED"] == [], f"round {r}: {res[0]!r}"
    finally:
        for cn in conns:
            await cn.close()
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True


# ============================================================================ B5 per-item isolation
async def test_b5_a_poisoned_item_is_recorded_and_does_not_starve_an_expired_t9_item(led):
    parent = await _failed_parent(led, base="base-3")
    rep = await _repair(led, parent, base="base-3")
    rtok = await led.claimed(rep, key="5" * 64)
    x, _, _ = await led.dispatched(request_id="t9", base="base-1")
    await led.conn.execute("UPDATE change_ledger.claim_tokens SET issued_at=now()-interval '10 minutes' "
                           "WHERE token_id=$1", rtok["token_id"])
    await led.conn.execute("UPDATE change_ledger.call_deadlines SET hard_deadline_at=now()-interval '1 second' "
                           "WHERE change_id=$1", x)
    await led.conn.execute("DELETE FROM change_ledger.target_locks WHERE owner_change_id=$1", rep)   # poison
    got = await sweep(led)
    assert got["T9"] == [str(x)] and got["T5x"] == []
    assert [(f["stage"], f["subject"]) for f in got["FAILED"]] == [("T5x", str(rep))]
    r = await led.rec(x)
    assert (r["execution_state"], r["call_ownership"]) == ("APPLY_UNKNOWN", "POSSIBLY_EXECUTING")
    # the failing item rolled back alone
    assert (await led.rec(rep))["authorization_state"] == "CLAIMED"
    assert await led.conn.fetchval("SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1",
                                   rtok["token_id"]) == "ISSUED"
    # a committed failure counter and a committed failure event, usable as an alert
    row = await led.conn.fetchrow("SELECT * FROM change_ledger.sweep_failures WHERE subject_id=$1", rep)
    assert (row["stage"], row["failures"], row["last_sqlstate"]) == ("T5x", 1, "P0001")
    assert "LOCK_BUSY" in row["last_error"]
    assert await event_count(led, "SWEEP_ITEM_FAILED", rep) == 1
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True
    again = await sweep(led)
    assert again["T9"] == [] and again["FAILED"] and again["changed"] == 0
    assert await led.conn.fetchval("SELECT failures FROM change_ledger.sweep_failures WHERE subject_id=$1", rep) == 2


async def test_b5_the_sweep_is_bounded_by_batch_size_and_healthy_items_come_before_failing_ones(led):
    ids = []
    for i in range(4):
        ids.append(await led.approved(request_id=f"bt{i}", base=f"base-{i + 1}"))
    await led.conn.execute("UPDATE change_ledger.records SET created_at=now()-interval '2 hours', "
                           "expires_at=now()-interval '1 minute' WHERE change_id = ANY($1)", ids)
    first = await sweep(led, batch_size=2)
    assert len(first["T3"]) == 2
    second = await sweep(led, batch_size=2)
    assert len(second["T3"]) == 2 and not set(first["T3"]) & set(second["T3"])
    assert (await sweep(led, batch_size=2))["T3"] == []
    for bad in ('{"batch_size":0}', '{"batch_size":501}', '{"batch_size":1.5}'):
        await fails("SCHEMA_INVALID", led.call("clt_wrk", "recover_sweep", bad))


# ============================================================================ B5 constants and overrides
async def test_b5_a_worker_cannot_pass_a_contract_constant_and_the_operator_policy_row_is_the_only_override(led):
    cid, tok, _ = await led.dispatched(request_id="v1", base="base-1")
    assert await led.complete(cid, tok["generation"], "SUCCESS") == "APPLIED"
    runs = await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_runs")
    for key in CONTRACT_KEYS:
        await fails("NOT_ENTITLED", led.call("clt_wrk", "recover_sweep", json.dumps({key: 1})))
    await fails("NOT_ENTITLED", led.call("clt_wrk", "recover_sweep", '{"verify_max_attempts":1}'))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_runs") == runs
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.sweep_counters WHERE subject_id=$1",
                                   cid) == 0
    # the ledger constant (bound 3) applies: the first due attempt is not the last
    got = await sweep(led, **FAST)
    assert got["VERIFY_DUE"] == [str(cid)] and got["VERIFY_EXHAUSTED"] == []
    # no worker / writer / requester / auditor can set the policy; the operator can, validated, as a ledger event
    for role in ("clt_wrk", "clt_wri", "clt_alice", "clt_aud"):
        await fails("permission denied", led.call(role, "set_sweep_policy", '{"verify_max_attempts":1}'))
    for bad in ('{"verify_max_attempts":0}', '{"verify_max_attempts":2.5}', '{"verify_max_attempts":99}',
                '{"claim_ttl_seconds":1}', '{"batch_size":5}', '{"nope":1}', '{"verify_max_attempts":"1"}', '[1]'):
        await fails("SCHEMA_INVALID", led.call("clt_dave", "set_sweep_policy", bad))
    merged = json.loads(await led.call("clt_dave", "set_sweep_policy", '{"verify_max_attempts":1}'))
    assert merged == {"verify_max_attempts": 1}
    ev = json.loads(await led.conn.fetchval("SELECT payload FROM change_ledger.events WHERE event_type="
                                            "'SWEEP_POLICY_SET'"))
    assert ev["params"] == {"verify_max_attempts": 1} and ev["previous"] == {} and ev["by"] == "clt_dave"
    got = await sweep(led, **FAST)
    assert got["VERIFY_EXHAUSTED"] == [str(cid)]                          # the policy row, not a parameter
    assert (await led.rec(cid))["verification_state"] == "FAILED_VERIFY"


async def test_b5_claim_and_permit_ttls_come_from_the_ledger_not_from_the_caller(led):
    app = await led.approved(request_id="ttl1", base="base-1")
    await led.claimed(app)
    assert (await sweep(led))["T5x"] == []                                  # 120 s constant: not elapsed
    await fails("NOT_ENTITLED", led.call("clt_wrk", "recover_sweep", '{"claim_ttl_seconds":0}'))
    await fails("NOT_ENTITLED", led.call("clt_wrk", "recover_sweep", '{"permit_ttl_seconds":0}'))
    assert (await led.rec(app))["authorization_state"] == "CLAIMED"
    await led.call("clt_dave", "set_sweep_policy", '{"claim_ttl_seconds":10}')
    await led.conn.execute("UPDATE change_ledger.claim_tokens SET issued_at=now()-interval '30 seconds'")
    assert (await sweep(led))["T5x"] == [str(app)]


async def test_b5_json_overrides_are_validated_as_schema_invalid_never_as_a_cast_error(led):
    bad_sets = ['{"deadline_seconds":1e12}', '{"deadline_seconds":-1}', '{"deadline_seconds":null}',
                '{"deadline_seconds":true}', '{"deadline_seconds":"abc"}', '{"deadline_seconds":[1]}',
                '{"t12_jitter_seconds":99999999}', '{"t12_interval_seconds":{"a":1}}', '{"t12_max_attempts":"x"}',
                '{"t12_max_attempts":-1}', '{"batch_size":1e400}', '{"nope":1}', '[1]', '"x"', '1', 'null']
    for bad in bad_sets:
        try:
            await led.call("clt_wrk", "recover_sweep", bad)
        except asyncpg.PostgresError as exc:
            assert "SCHEMA_INVALID" in str(exc), (bad, repr(exc))
            assert exc.sqlstate not in ("22P02", "22003"), (bad, exc.sqlstate)
        else:
            assert bad == "null", bad                                      # SQL NULL / JSON null means no overrides
    # the lock-busy parameters of complete_lock_busy use the same validator and fail before any lookup
    for bad in ('{"lock_busy_max_attempts":1e30}', '{"lock_busy_max_attempts":2.5}', '{"lock_busy_interval_seconds":"x"}'):
        await fails("SCHEMA_INVALID", led.call("clt_wri", "complete_lock_busy", uuid.uuid4(), 1, uuid.uuid4(), bad))
    await fails("SCHEMA_INVALID", led.call("clt_wrk", "recover_sweep", '{"deadline_seconds":1e12}'))
