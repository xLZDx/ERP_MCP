"""Focused PostgreSQL tests for db/phase2/011_event_hash_v2.sql: version 2 of the ledger event hash formula, finding B6
item (m) of docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md (the hash must also cover tenant_id, company_id, event_id and
recorded_at).

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database. Superuser access arranges only what no API can
produce (tampering with the immutable log by disabling its triggers, a ledger as it was before 011) and reads results.

Tests:
  d_formula_*      the stored hash is the documented v2 formula; each of the four new fields changes it
  d_tamper_*       a change of event_id / recorded_at / tenant / company is detected by verify_chain (bad_seq), where the
                   v1 formula was blind to it
  d_migration_*    rows that existed before 011 are rehashed in one ordered pass, keep every other column, the chain
                   continues, checkpoints are kept as v1 evidence and no longer authorize, a broken chain is refused
  d_chain_*        new events always chain with v2 (a caller-supplied version/hash is ignored), concurrent appends stay
                   gapless, re-applying 011 is a recorded no-op
The pg_dump / pg_restore round trip is test_change_ledger_dump_restore.py (it applies 011 through its FILES).
"""
import asyncio
import hashlib
import json
import uuid
from datetime import UTC

import asyncpg
import pytest
from _pg_harness import FILES, MIGRATIONS, fails, require_dsn, throwaway_db
from test_change_ledger_sql import BASES, C, DIGEST, ORG, T, L, _setup, exp

pytestmark = pytest.mark.integration

FILE_011 = "011_event_hash_v2.sql"


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


# ---------------------------------------------------------------------------------------------- python twins
def v1_hash(prev, r):
    """The retired v1 formula (prev, seq, change_id, event_type, payload)."""
    return hashlib.sha256(f"{prev or ''}:{r['seq']}:{r['change_id'] or ''}:{r['event_type']}:{r['payload']}"
                          .encode()).hexdigest()


def v2_hash(prev, r):
    """The documented v2 formula, written independently of the SQL function."""
    ts = r["recorded_at"].astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return hashlib.sha256((
        f"change-ledger-event|v2|{prev or ''}|{r['seq']}|{len(r['tenant_id'])}:{r['tenant_id']}|"
        f"{len(r['company_id'])}:{r['company_id']}|{r['event_id']}|{r['change_id'] or ''}|"
        f"{len(r['event_type'])}:{r['event_type']}|{ts}|{r['payload']}").encode()).hexdigest()


async def chain_rows(conn, t=T, c=C):
    return await conn.fetch("SELECT * FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 ORDER BY seq", t, c)


async def tamper(conn, *stmts):
    """The only way to alter the immutable log: a superuser switches the guard triggers off for the statements."""
    await conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable")
    await conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_chain")
    try:
        for s in stmts:
            await conn.execute(s)
    finally:
        await conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable")
        await conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_chain")


async def activity(led):
    """Real ledger traffic: a full approval path, a dispatched change and NULL-change_id events."""
    await led.dispatched(request_id="d-act")
    await led.call("clt_dave", "kill_switch", "OFF")
    await led.approved(request_id="d-act2", base="base-2")


async def aud_scope(led, t, c):
    await led.conn.execute("SELECT change_ledger.add_role_scope('clt_aud',$1,$2)", t, c)


async def put_identical_chain(conn, t, c, n=3):
    """n direct INSERTs of identical content (change_id NULL, same type/payload): the chain trigger does the rest."""
    for i in range(n):
        await conn.execute("INSERT INTO change_ledger.events(tenant_id,company_id,event_type,payload) "
                           "VALUES($1,$2,'D_PROBE',$3::jsonb)", t, c, json.dumps({"i": i}))


# ============================================================================ the formula
async def test_d_formula_stored_hash_is_the_documented_v2_formula_for_every_event(led):
    await activity(led)
    rows = await chain_rows(led.conn)
    assert len(rows) >= 15
    prev = None
    for r in rows:
        assert r["hash_version"] == 2
        assert r["hash"] == v2_hash(prev, r), r["seq"]
        assert r["prev_hash"] == prev
        prev = r["hash"]
    assert any(r["change_id"] is None for r in rows)                       # the NULL change_id branch is exercised
    assert await led.call("clt_aud", "verify_chain") == {"ok": True, "count": len(rows), "bad_seq": None}


async def test_d_formula_each_new_field_changes_the_hash_and_v1_cannot_see_any_of_them(led):
    await led.approved(request_id="d-f")
    r = (await chain_rows(led.conn))[2]
    args = [r["prev_hash"], r["seq"], r["tenant_id"], r["company_id"], r["event_id"], r["change_id"],
            r["event_type"], r["payload"], r["recorded_at"]]
    sql = "SELECT change_ledger.event_hash_v2($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9)"
    base = await led.conn.fetchval(sql, *args)
    assert base == r["hash"]                                                 # the SQL function is the stored value
    changed = {
        "tenant_id": (2, "T9"), "company_id": (3, "C9"), "event_id": (4, uuid.uuid4()),
        "recorded_at": (8, r["recorded_at"].replace(microsecond=(r["recorded_at"].microsecond + 1) % 1000000)),
    }
    for name, (idx, value) in changed.items():
        alt = list(args)
        alt[idx] = value
        assert await led.conn.fetchval(sql, *alt) != base, name
    # a pre-existing field still matters too (control: the comparison is not trivially unequal)
    alt = list(args)
    alt[1] = r["seq"] + 1
    assert await led.conn.fetchval(sql, *alt) != base
    # the retired v1 formula does not take any of the four fields: its value cannot move with them
    assert v1_hash(r["prev_hash"], r) == v1_hash(r["prev_hash"], {**dict(r), "tenant_id": "T9", "company_id": "C9",
                                                                       "event_id": uuid.uuid4()})
    # no ambiguity between neighbouring text fields: ('ab','c') and ('a','bc') hash differently
    a = await led.conn.fetchval(sql, None, 1, "ab", "c", r["event_id"], None, "X", "{}", r["recorded_at"])
    b = await led.conn.fetchval(sql, None, 1, "a", "bc", r["event_id"], None, "X", "{}", r["recorded_at"])
    assert a != b


async def test_d_formula_recorded_time_is_rendered_in_utc_whatever_the_session_time_zone(led):
    await led.approved(request_id="d-tz")
    r = (await chain_rows(led.conn))[1]
    sql = "SELECT change_ledger.event_hash_v2($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9)"
    args = [r["prev_hash"], r["seq"], r["tenant_id"], r["company_id"], r["event_id"], r["change_id"],
            r["event_type"], r["payload"], r["recorded_at"]]
    for zone in ("UTC", "Asia/Tokyo", "America/Los_Angeles"):
        await led.conn.execute(f"SET TimeZone TO '{zone}'")
        assert await led.conn.fetchval(sql, *args) == r["hash"], zone
    await led.conn.execute("RESET TimeZone")


# ============================================================================ tamper detection
@pytest.mark.parametrize("field,stmt", [
    ("event_id", "UPDATE change_ledger.events SET event_id=gen_random_uuid() WHERE seq=2"),
    ("recorded_at", "UPDATE change_ledger.events SET recorded_at=recorded_at+interval '1 second' WHERE seq=2"),
])
async def test_d_tamper_of_event_id_or_recorded_time_is_detected_at_that_row(led, field, stmt):
    await activity(led)
    n = await led.conn.fetchval("SELECT count(*) FROM change_ledger.events")
    before = (await chain_rows(led.conn))[1]
    assert await led.call("clt_aud", "verify_chain") == {"ok": True, "count": n, "bad_seq": None}
    await tamper(led.conn, stmt)
    after = (await chain_rows(led.conn))[1]
    assert after[field] != before[field]
    assert await led.call("clt_aud", "verify_chain") == {"ok": False, "count": 1, "bad_seq": 2}, field
    # the v1 formula would have accepted the tampered row (this is the blind spot B6m closes)
    assert v1_hash(before["prev_hash"], after) == v1_hash(before["prev_hash"], before)


@pytest.mark.parametrize("a_scope,b_scope,field", [
    (("TA", "CA"), ("TB", "CA"), "tenant_id"),
    (("TA", "CA"), ("TA", "CB"), "company_id"),
])
async def test_d_tamper_of_tenant_or_company_is_detected_when_a_chain_is_transplanted(led, a_scope, b_scope, field):
    """Two scopes with identical event content: under v1 their chains are byte-for-byte the same hashes, so one chain
    could be relabelled as the other. Under v2 the relabelled chain does not verify."""
    for t, c in (a_scope, b_scope):
        await aud_scope(led, t, c)
        await put_identical_chain(led.conn, t, c)
    a_rows, b_rows = await chain_rows(led.conn, *a_scope), await chain_rows(led.conn, *b_scope)
    prev_a = prev_b = None
    for ra, rb in zip(a_rows, b_rows):                                       # v1 cannot tell the two chains apart
        prev_a, prev_b = v1_hash(prev_a, ra), v1_hash(prev_b, rb)
        assert prev_a == prev_b
    assert [r["hash"] for r in a_rows] != [r["hash"] for r in b_rows]        # v2 can
    for t, c in (a_scope, b_scope):
        assert await led.call("clt_aud", "verify_chain", t=t, c=c) == {"ok": True, "count": 3, "bad_seq": None}
    bt, bc = b_scope
    await tamper(
        led.conn, "DELETE FROM change_ledger.events WHERE tenant_id='%s' AND company_id='%s'" % (bt, bc),
        "INSERT INTO change_ledger.events(tenant_id,company_id,event_id,change_id,seq,event_type,payload,prev_hash,"
        "hash,recorded_at,hash_version) SELECT '%s','%s',gen_random_uuid(),change_id,seq,event_type,payload,prev_hash,"
        "hash,recorded_at,hash_version FROM change_ledger.events WHERE tenant_id='%s' AND company_id='%s'"
        % (bt, bc, a_scope[0], a_scope[1]))
    assert await led.call("clt_aud", "verify_chain", t=bt, c=bc) == {"ok": False, "count": 0, "bad_seq": 1}, field
    assert await led.call("clt_aud", "verify_chain", t=a_scope[0], c=a_scope[1]) == \
        {"ok": True, "count": 3, "bad_seq": None}                            # the source chain is untouched


async def test_d_tamper_of_hash_version_is_detected(led):
    await activity(led)
    await tamper(led.conn, "UPDATE change_ledger.events SET hash_version=1 WHERE seq=3")
    assert await led.call("clt_aud", "verify_chain") == {"ok": False, "count": 2, "bad_seq": 3}


async def test_d_tamper_with_an_unknown_hash_version_is_refused_by_the_constraint(led):
    await activity(led)
    with pytest.raises(asyncpg.CheckViolationError):
        await tamper(led.conn, "UPDATE change_ledger.events SET hash_version=3 WHERE seq=3")


# ============================================================================ the migration
async def apply_files(conn, names):
    for name in names:
        raw = (MIGRATIONS / name).read_bytes()
        await conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
        await conn.execute(raw.decode("utf-8"))


EVENT_COLS = ("tenant_id, company_id, event_id, change_id, seq, event_type, payload::text AS payload, recorded_at")


async def old_world(db):
    """001-010 only: a ledger whose events are v1 and whose checkpoints are anchored on v1 heads."""
    db.conn = await db.connect()
    assert FILES[-1] == FILE_011 and len(FILES) == 11
    await apply_files(db.conn, FILES[:-1])
    await _setup(db.conn)
    return L(db)


async def test_d_migration_rehashes_existing_rows_and_the_chain_continues():
    dsn = require_dsn()
    async with throwaway_db(dsn, migrate=False, seed=False) as db:
        old = await old_world(db)
        conn = db.conn
        assert await conn.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_schema="
                                   "'change_ledger' AND table_name='events' AND column_name='hash_version'") == 0
        await activity(old)
        pending, ptok, _ = await old.applying(request_id="d-pend", base="base-3")     # needs a checkpoint after APPLYING
        await old.checkpoint()
        old_head = await old.call("clt_aud", "ledger_head")
        n = await conn.fetchval("SELECT count(*) FROM change_ledger.events")
        pre_verify = await old.call("clt_aud", "verify_chain")
        assert pre_verify == {"ok": True, "count": n, "bad_seq": None}
        pre = await conn.fetch(f"SELECT {EVENT_COLS}, hash AS h1 FROM change_ledger.events ORDER BY tenant_id, "
                               "company_id, seq")
        prev_ok = None
        for r in pre:                                                          # the old chain really is v1
            assert r["h1"] == v1_hash(prev_ok if r["seq"] > 1 else None, r)
            prev_ok = r["h1"]
        pre_cp = await conn.fetch("SELECT * FROM change_ledger.checkpoints ORDER BY seq")
        pre_funcs = {r[0] for r in await conn.fetch("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON "
                                                    "n.oid=p.pronamespace WHERE n.nspname='change_ledger'")}

        await apply_files(conn, [FILE_011])

        # ---- every row is rehashed to v2, nothing else about it moved
        post = await conn.fetch(f"SELECT {EVENT_COLS}, hash, prev_hash, hash_version FROM change_ledger.events "
                                "ORDER BY tenant_id, company_id, seq")
        assert len(post) == len(pre) == n
        for a, b in zip(pre, post):
            for col in ("tenant_id", "company_id", "event_id", "change_id", "seq", "event_type", "payload",
                        "recorded_at"):
                assert a[col] == b[col], (col, a["seq"])
        prev = None
        for r in post:
            if r["seq"] == 1:
                prev = None
            assert r["hash_version"] == 2 and r["prev_hash"] == prev
            assert r["hash"] == v2_hash(prev, r), r["seq"]
            prev = r["hash"]
        assert {r["h1"] for r in pre}.isdisjoint({r["hash"] for r in post})
        # ---- rows that existed before 011 verify after it, with the same count
        assert await old.call("clt_aud", "verify_chain") == pre_verify
        head = await old.call("clt_aud", "ledger_head")
        assert head["seq"] == old_head["seq"] and head["head_hash"] != old_head["head_hash"]
        # ---- new events continue the chain from the rehashed head, formula v2
        await old.approved(request_id="d-after", base="base-4")
        new = [r for r in await chain_rows(conn) if r["seq"] > head["seq"]]
        assert len(new) >= 3 and new[0]["prev_hash"] == head["head_hash"]
        assert all(r["hash_version"] == 2 for r in new)
        assert await old.call("clt_aud", "verify_chain") == {"ok": True, "count": head["seq"] + len(new),
                                                             "bad_seq": None}
        # ---- the guard is back: immutable again, trigger state restored to the default, nothing left behind
        assert await conn.fetchval("SELECT tgenabled::text FROM pg_trigger WHERE tgname='events_immutable' AND "
                                   "tgrelid='change_ledger.events'::regclass") == "O"
        await fails("IMMUTABLE_LEDGER", conn.execute("UPDATE change_ledger.events SET payload='{}'::jsonb"))
        funcs = {r[0] for r in await conn.fetch("SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON "
                                                "n.oid=p.pronamespace WHERE n.nspname='change_ledger'")}
        assert funcs - pre_funcs == {"event_hash_v2"}                          # no maintenance function remains
        assert await conn.fetchval("SELECT column_default FROM information_schema.columns WHERE table_schema="
                                   "'change_ledger' AND table_name='events' AND column_name='hash_version'") == "2"

        # ---- checkpoints: byte-identical signed v1 evidence, labelled v1, no longer an anchor of the ledger
        post_cp = await conn.fetch("SELECT * FROM change_ledger.checkpoints ORDER BY seq")
        assert len(post_cp) == len(pre_cp) >= 2
        assert post_cp[-1]["head_hash"] == old_head["head_hash"]
        for a, b in zip(pre_cp, post_cp):
            assert {k: v for k, v in dict(b).items() if k != "hash_version"} == dict(a)   # signed row untouched
            assert b["hash_version"] == 1
        assert await conn.fetchval("SELECT count(*) FROM change_ledger.events e JOIN change_ledger.checkpoints k ON "
                                   "e.tenant_id=k.tenant_id AND e.company_id=k.company_id AND e.seq=k.ledger_seq AND "
                                   "e.hash=k.head_hash") == 0
        await fails("CHECKPOINT_UNAVAILABLE", old.call("clt_wrk", "issue_permit", pending, ptok["generation"]))
        await old.checkpoint()                                                # a checkpoint of the v2 head is accepted
        assert await conn.fetchval("SELECT hash_version FROM change_ledger.checkpoints ORDER BY seq DESC LIMIT 1") == 2
        permit = await old.call("clt_wrk", "issue_permit", pending, ptok["generation"])
        assert permit["generation"] == ptok["generation"]
        # ---- anchors: the v2 head matches, the v1 head of the same seq is an ANCHOR_GAP (it was never re-issued)
        v2_head = await old.call("clt_aud", "ledger_head")
        assert (await old.call("clt_wrk", "check_anchor", v2_head["seq"], v2_head["head_hash"]))["ok"] is True
        gap = await old.call("clt_wrk", "check_anchor", old_head["seq"], old_head["head_hash"])
        assert gap["ok"] is False and gap["holds_opened"] >= 1


async def test_d_migration_refuses_a_chain_that_is_already_broken_and_changes_nothing():
    dsn = require_dsn()
    async with throwaway_db(dsn, migrate=False, seed=False) as db:
        old = await old_world(db)
        conn = db.conn
        await activity(old)
        await conn.execute("ALTER TABLE change_ledger.events DISABLE TRIGGER events_immutable")
        await conn.execute("UPDATE change_ledger.events SET payload='{\"forged\":1}'::jsonb WHERE seq=4")
        await conn.execute("ALTER TABLE change_ledger.events ENABLE TRIGGER events_immutable")
        assert (await old.call("clt_aud", "verify_chain"))["bad_seq"] == 4
        raw = (MIGRATIONS / FILE_011).read_bytes()
        await conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
        with pytest.raises(asyncpg.PostgresError) as exc:
            await conn.execute(raw.decode("utf-8"))
        assert "EVENT_CHAIN_BROKEN_BEFORE_REHASH" in str(exc.value) and "seq=4" in str(exc.value)
        await conn.execute("ROLLBACK")
        # the whole migration rolled back: no column, no function, trigger still enabled, old rows untouched
        assert await conn.fetchval("SELECT count(*) FROM information_schema.columns WHERE table_schema="
                                   "'change_ledger' AND column_name='hash_version'") == 0
        assert await conn.fetchval("SELECT count(*) FROM pg_proc WHERE proname='event_hash_v2'") == 0
        assert await conn.fetchval("SELECT tgenabled::text FROM pg_trigger WHERE tgname='events_immutable' AND "
                                   "tgrelid='change_ledger.events'::regclass") == "O"
        assert (await old.call("clt_aud", "verify_chain"))["bad_seq"] == 4


# ============================================================================ chaining after the migration
async def test_d_chain_a_caller_supplied_version_or_hash_is_ignored_on_insert(led):
    await led.approved(request_id="d-ins")
    await led.conn.execute("INSERT INTO change_ledger.events(tenant_id,company_id,event_type,hash,hash_version,"
                           "prev_hash,seq) VALUES($1,$2,'D_FORGED',repeat('a',64),1,repeat('b',64),999)", T, C)
    last = (await chain_rows(led.conn))[-1]
    assert last["event_type"] == "D_FORGED" and last["hash_version"] == 2 and last["hash"] != "a" * 64
    assert last["seq"] == (await chain_rows(led.conn))[-2]["seq"] + 1
    assert last["hash"] == v2_hash(last["prev_hash"], last)
    n = await led.conn.fetchval("SELECT count(*) FROM change_ledger.events")
    assert await led.call("clt_aud", "verify_chain") == {"ok": True, "count": n, "bad_seq": None}


async def test_d_chain_concurrent_appends_stay_one_gapless_v2_chain(led):
    conns = [await led.db.connect() for _ in range(4)]
    try:
        async def worker(k):
            for j in range(4):
                i = k * 4 + j
                await led.call("clt_alice", "propose", uuid.uuid4(), "CREATE_DRAFT", BASES[i % 8], ORG, "clt_alice",
                               f"d-conc-{i}", DIGEST, f"d{i}", "v1", None, exp(), None, conn=conns[k])
        await asyncio.gather(*[worker(k) for k in range(4)])
    finally:
        for x in conns:
            await x.close()
    rows = await chain_rows(led.conn)
    assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1)) and len(rows) >= 16
    assert {r["hash_version"] for r in rows} == {2}
    prev = None
    for r in rows:
        assert r["prev_hash"] == prev and r["hash"] == v2_hash(prev, r)
        prev = r["hash"]
    assert await led.call("clt_aud", "verify_chain") == {"ok": True, "count": len(rows), "bad_seq": None}


async def test_d_chain_replay_does_not_add_events_and_the_head_only_moves_forward(led):
    cid = await led.validated(request_id="d-rep")
    nonce = await led.call("clt_bob", "issue_approval_nonce", cid)
    dg = await led.approval_digest(cid)
    a1 = await led.call("clt_bob", "approve", cid, nonce, dg)
    head1 = await led.call("clt_aud", "ledger_head")
    assert await led.call("clt_bob", "approve", cid, nonce, dg) == a1             # idempotent replay
    assert await led.call("clt_aud", "ledger_head") == head1                       # no event, same head
    await led.claimed(cid)
    head2 = await led.call("clt_aud", "ledger_head")
    assert head2["seq"] > head1["seq"] and head2["head_hash"] != head1["head_hash"]
    row = await led.conn.fetchrow("SELECT * FROM change_ledger.events WHERE seq=$1 AND tenant_id=$2 AND company_id=$3",
                                  head1["seq"] + 1, T, C)
    assert row["prev_hash"] == head1["head_hash"]


async def test_d_chain_replaying_lost_events_reproduces_the_hashes_only_with_their_id_and_time(led):
    """B6m consequence for restores: the archive must carry event_id and recorded_at. A replay of the same content with
    fresh ids/times builds a valid chain, but NOT the anchored one (under v1 it would have collided with it)."""
    await led.approved(request_id="d-rp")
    lost = (await chain_rows(led.conn))[3:]
    kept = (await chain_rows(led.conn))[:3]
    assert len(lost) >= 2
    await tamper(led.conn, "DELETE FROM change_ledger.events WHERE seq>3")
    for r in lost:                                                            # verbatim replay: same hashes
        await led.conn.execute("INSERT INTO change_ledger.events(tenant_id,company_id,event_id,recorded_at,change_id,"
                               "event_type,payload) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)", T, C, r["event_id"],
                               r["recorded_at"], r["change_id"], r["event_type"], r["payload"])
    assert [r["hash"] for r in await chain_rows(led.conn)] == [r["hash"] for r in kept + lost]
    await tamper(led.conn, "DELETE FROM change_ledger.events WHERE seq>3")
    for r in lost:                                                            # same content, fresh id and time
        await led.conn.execute("INSERT INTO change_ledger.events(tenant_id,company_id,change_id,event_type,payload) "
                               "VALUES($1,$2,$3,$4,$5::jsonb)", T, C, r["change_id"], r["event_type"], r["payload"])
    again = await chain_rows(led.conn)
    assert again[3]["hash"] != lost[0]["hash"] and len(again) == len(kept + lost)
    assert await led.call("clt_aud", "verify_chain") == {"ok": True, "count": len(again), "bad_seq": None}


async def test_d_chain_reapplying_011_is_a_recorded_no_op(led):
    await led.approved(request_id="d-re")
    before = [(r["seq"], r["hash"]) for r in await chain_rows(led.conn)]
    raw = (MIGRATIONS / FILE_011).read_bytes()
    await led.conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
    await led.conn.execute(raw.decode("utf-8"))
    assert [(r["seq"], r["hash"]) for r in await chain_rows(led.conn)] == before
    assert (await led.call("clt_aud", "verify_chain"))["ok"] is True


async def test_d_chain_the_formula_function_is_executable_by_the_auditor_only(led):
    sig = "change_ledger.event_hash_v2(text,bigint,text,text,uuid,uuid,text,jsonb,timestamptz)"
    for role, want in (("auditor_role", True), ("requester_role", False), ("approver_role", False),
                       ("operator_role", False), ("writer_role", False), ("worker_role", False)):
        assert await led.conn.fetchval("SELECT has_function_privilege($1,$2::regprocedure,'EXECUTE')",
                                       role, sig) is want, role
    assert await led.conn.fetchval("SELECT prosecdef FROM pg_proc WHERE proname='event_hash_v2'") is True
