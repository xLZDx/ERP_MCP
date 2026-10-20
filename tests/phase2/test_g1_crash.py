"""G1 crash / interruption tests for commit_cursor_page and ingest_observation.

Requires Docker and `ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1`; each test provisions and owns its
temporary PostgreSQL container. Without the opt-in or Docker: skip NOT_RUN, or fail when
`ERP_PHASE2_REQUIRE_PG=1`.

Two different failure classes, kept apart on purpose:

* BACKEND TERMINATION (no crash recovery): a second session runs pg_terminate_backend() on the
  session that has done partial work (or is blocked inside the API). Only that one backend dies;
  the postmaster keeps all other backends. Tests: test_terminate_*.
* CRASH-RECOVERY CYCLE: an ownership-checked `docker exec` into that test's fixture SIGKILLs
  the backend serving the transaction. The postmaster then terminates every backend, replays WAL
  and reinitialises ("all server processes terminated; reinitializing" in the container log, which
  the tests count before/after). The container itself is never stopped. Tests: test_sigkill_*.

After either failure: cursor, outbox and observations are all-or-nothing, data committed before
the failure survives, and replaying the same page / observation is idempotent (no duplicate and no
lost events).
"""
import asyncio
import uuid

import asyncpg
import pytest
from _pg_harness import (
    COMMIT,
    D1,
    INGEST,
    OBS_AT,
    admin_connect,
    call,
    cursor_and_job,
    disposable_cluster,
    ingest,
    page,
    owned_cluster_identity,
    owned_cluster_log_marks,
    owned_kill_backend,
    source_epoch,
    throwaway_db,
    wait_owned_cluster_recovered,
)

pytestmark = pytest.mark.integration

DEAD = (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, ConnectionError)


async def _outbox_ids(c):
    return [r[0] for r in await c.fetch(
        "SELECT event_id FROM living.outbox WHERE connection_id='conn' ORDER BY seq")]


async def _baseline(db):
    """Page 1 (e1) and observation OBS-OK are COMMITTED before the failure."""
    c = db.conn
    j, f = await cursor_and_job(c)
    ep = await source_epoch(c)
    assert await call(c, "living_worker", COMMIT, j, "w1", f, "p0", 0, ep, "p1",
                      await page(c, "e1")) == 1
    await ingest(c, "obj-ok", uuid.uuid4())
    return j, f, ep


async def _open_work(db, kind, j, f, ep, rev):
    """A session with an OPEN transaction that has already done the API's work (uncommitted)."""
    a = await db.connect()
    pid = await a.fetchval("SELECT pg_backend_pid()")
    tx = a.transaction()
    await tx.start()
    await a.execute("SET LOCAL ROLE living_worker")
    await a.fetchval("SELECT living.set_scope('A','s1',NULL)")
    if kind == "page":
        res = await a.fetchval(COMMIT, j, "w1", f, "p1", 1, ep, "p2", await page(a, "e2", "e3"))
        assert res == 2
    else:
        res = await a.fetchval(INGEST, "A", "s1", uuid.uuid4(), "obj-new", rev, "OBSERVED", D1,
                               None, OBS_AT, None)
        assert res is not None
    # partial work is visible inside the doomed transaction only
    if kind == "page":
        assert await _outbox_ids(a) == ["e1", "e2", "e3"]
    return a, tx, pid


async def _assert_dead(a, tx):
    with pytest.raises(DEAD):
        await tx.commit()
    a.terminate()


async def _assert_rolled_back(db, kind, rev):
    v = await db.connect()
    try:
        # committed-before-failure data survives
        assert tuple(await v.fetchrow("SELECT cursor_value,version FROM living.cursors")) \
            == ("p1", 1)
        assert await _outbox_ids(v) == ["e1"]
        assert await v.fetchval(
            "SELECT count(*) FROM living.observations WHERE object_id='obj-ok'") == 1
        # nothing of the interrupted transaction is visible: all-or-nothing
        assert await v.fetchval("SELECT count(*) FROM living.observations WHERE revision_id=$1",
                                rev) == 0
        assert await v.fetchval("SELECT count(*) FROM living.observations") == 1
    finally:
        await v.close()


async def _replay_and_check(db, kind, j, f, ep, rev):
    c = await db.connect()
    try:
        if kind == "page":
            pg = await page(c, "e2", "e3")
            for _ in range(3):  # first applies, the next two are idempotent replays
                assert await call(c, "living_worker", COMMIT, j, "w1", f, "p1", 1, ep, "p2",
                                  pg) == 2
            assert await _outbox_ids(c) == ["e1", "e2", "e3"]  # no duplicate, none lost
            assert tuple(await c.fetchrow("SELECT cursor_value,version FROM living.cursors")) \
                == ("p2", 2)
            with pytest.raises(asyncpg.PostgresError, match="STALE_CURSOR_OR_SCOPE"):
                await call(c, "living_worker", COMMIT, j, "w1", f, "p0", 0, ep, "p1",
                           await page(c, "e1"))
            assert await _outbox_ids(c) == ["e1", "e2", "e3"]
        else:
            oid = uuid.uuid4()
            ids = {await ingest(c, "obj-new", rev, obs_id=oid) for _ in range(3)}
            assert ids == {oid}
            assert await c.fetchval(
                "SELECT count(*) FROM living.observations WHERE revision_id=$1", rev) == 1
            assert await c.fetchval("SELECT count(*) FROM living.observations") == 2
    finally:
        await c.close()


async def _terminate_backend_after_partial_work(dsn, container_name, owner_token, kind):
    """BACKEND TERMINATION (not a crash-recovery cycle): pg_terminate_backend on a session whose
    open transaction already ran commit_cursor_page / ingest_observation."""
    async with throwaway_db(dsn) as db:
        j, f, ep = await _baseline(db)
        rev = uuid.uuid4()
        a, tx, pid = await _open_work(db, kind, j, f, ep, rev)
        marks = owned_cluster_log_marks(container_name, owner_token)
        admin = await admin_connect(dsn)
        try:
            assert await admin.fetchval("SELECT pg_terminate_backend($1)", pid) is True
        finally:
            await admin.close()
        await _assert_dead(a, tx)
        assert owned_cluster_log_marks(container_name, owner_token) == marks, "a plain termination must not cause crash recovery"
        await _assert_rolled_back(db, kind, rev)
        await _replay_and_check(db, kind, j, f, ep, rev)


async def _terminate_backend_blocked_inside_commit_cursor_page(dsn):
    """BACKEND TERMINATION (not a crash-recovery cycle): the session is terminated while it waits
    on the source row lock INSIDE commit_cursor_page (lock held by another transaction)."""
    async with throwaway_db(dsn) as db:
        j, f, ep = await _baseline(db)
        holder = await db.connect()
        a = await db.connect()
        pid = await a.fetchval("SELECT pg_backend_pid()")
        pg = await page(a, "e2", "e3")

        async def blocked_call():
            async with a.transaction():
                await a.execute("SET LOCAL ROLE living_worker")
                await a.fetchval("SELECT living.set_scope('A','s1',NULL)")
                return await a.fetchval(COMMIT, j, "w1", f, "p1", 1, ep, "p2", pg)

        hold_tx = holder.transaction()
        await hold_tx.start()
        try:
            await holder.fetchval("SELECT 1 FROM living.sources WHERE tenant_id='A' AND "
                                  "source_id='s1' FOR UPDATE")
            task = asyncio.create_task(blocked_call())
            admin = await admin_connect(dsn)
            try:
                for _ in range(100):
                    if await admin.fetchval("SELECT wait_event_type FROM pg_stat_activity "
                                            "WHERE pid=$1", pid) == "Lock":
                        break
                    await asyncio.sleep(0.1)
                else:
                    raise AssertionError("session never blocked on the source lock")
                assert await admin.fetchval("SELECT pg_terminate_backend($1)", pid) is True
            finally:
                await admin.close()
            with pytest.raises(DEAD):
                await asyncio.wait_for(task, 20)
        finally:
            await hold_tx.rollback()
            await holder.close()
            a.terminate()
        await _assert_rolled_back(db, "page", uuid.uuid4())
        await _replay_and_check(db, "page", j, f, ep, uuid.uuid4())


async def _sigkill_backend_crash_recovery(dsn, container_name, owner_token, kind):
    """CRASH-RECOVERY CYCLE: SIGKILL of the postgres backend serving the open transaction (via
    docker exec); the postmaster restarts all backends and replays WAL. The container stays up.
    Another session proves the cycle happened (its connection dies) and the log mark increments."""
    async with throwaway_db(dsn) as db:
        j, f, ep = await _baseline(db)
        rev = uuid.uuid4()
        a, tx, pid = await _open_work(db, kind, j, f, ep, rev)
        bystander = await db.connect()  # a healthy session must be taken down by the cycle too
        assert await bystander.fetchval("SELECT 1") == 1
        marks = owned_cluster_log_marks(container_name, owner_token)
        owned_kill_backend(container_name, owner_token, pid, "KILL")
        await _assert_dead(a, tx)
        with pytest.raises(DEAD):
            for _ in range(100):  # the bystander dies when the postmaster reinitialises
                await bystander.fetchval("SELECT 1")
                await asyncio.sleep(0.1)
        bystander.terminate()
        await wait_owned_cluster_recovered(dsn, container_name, owner_token)
        assert owned_cluster_log_marks(container_name, owner_token) == marks + 1, "no crash-recovery cycle was observed"
        await _assert_rolled_back(db, kind, rev)
        await _replay_and_check(db, kind, j, f, ep, rev)


async def _record_cluster_identity(dsn, name, token, record_property):
    record_property("g1_container_name", name)
    record_property("g1_container_id", owned_cluster_identity(name, token))
    conn = await admin_connect(dsn)
    try:
        system_id = await conn.fetchval("SELECT system_identifier FROM pg_control_system()")
    finally:
        await conn.close()
    record_property("g1_postgresql_system_identifier", str(system_id))


@pytest.mark.parametrize("kind", ["page", "ingest"])
async def test_terminate_backend_after_partial_work(kind, record_property):
    async with disposable_cluster() as (dsn, name, token):
        await _record_cluster_identity(dsn, name, token, record_property)
        await _terminate_backend_after_partial_work(dsn, name, token, kind)


async def test_terminate_backend_blocked_inside_commit_cursor_page(record_property):
    async with disposable_cluster() as (dsn, name, token):
        await _record_cluster_identity(dsn, name, token, record_property)
        await _terminate_backend_blocked_inside_commit_cursor_page(dsn)


@pytest.mark.parametrize("kind", ["page", "ingest"])
async def test_sigkill_backend_crash_recovery(kind, record_property):
    async with disposable_cluster() as (dsn, name, token):
        await _record_cluster_identity(dsn, name, token, record_property)
        await _sigkill_backend_crash_recovery(dsn, name, token, kind)


async def test_terminate_backend_during_observed_explicit_commit(record_property):
    """G1 acceptance: observer proves COMMIT is blocked inside a deferred trigger before kill."""
    async with disposable_cluster() as (dsn, container_name, owner_token):
        await _record_cluster_identity(dsn, container_name, owner_token, record_property)
        await _observed_commit_case(dsn, record_property)


async def _observed_commit_case(dsn, record_property):
    async with throwaway_db(dsn) as db:
        j, f, ep = await _baseline(db)
        admin = await admin_connect(dsn, database=db.name)
        holder = await admin_connect(dsn, database=db.name)
        target = await admin_connect(dsn, database=db.name)
        try:
            await admin.execute("""
                CREATE TABLE public.g1_commit_probe (marker text PRIMARY KEY);
                CREATE FUNCTION public.g1_wait_at_commit() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  PERFORM pg_advisory_xact_lock(724001, 91);
                  RETURN NEW;
                END $$;
                CREATE CONSTRAINT TRIGGER g1_commit_probe_deferred
                  AFTER INSERT ON public.g1_commit_probe DEFERRABLE INITIALLY DEFERRED
                  FOR EACH ROW EXECUTE FUNCTION public.g1_wait_at_commit();
                GRANT INSERT ON public.g1_commit_probe TO living_worker;
            """)
            # Session lock keeps the deferred trigger waiting until the separate observer proves
            # the target's explicit COMMIT is executing and waiting for this advisory lock.
            await holder.fetchval("SELECT pg_advisory_lock(724001, 91)")
            pid = await target.fetchval("SELECT pg_backend_pid()")
            tx = target.transaction()
            await tx.start()
            await target.execute("SET LOCAL application_name='g1-explicit-commit'")
            await target.execute("SET LOCAL ROLE living_worker")
            await target.fetchval("SELECT living.set_scope('A','s1',NULL)")
            assert await target.fetchval(
                COMMIT, j, "w1", f, "p1", 1, ep, "p2", await page(target, "e2", "e3")) == 2
            await target.execute("INSERT INTO public.g1_commit_probe VALUES('same-transaction')")
            commit_task = asyncio.create_task(tx.commit())
            try:
                observed = False
                last_observer = None
                for _ in range(150):
                    row = await admin.fetchrow(
                        "SELECT state, query, wait_event_type, wait_event FROM pg_stat_activity "
                        "WHERE pid=$1", pid)
                    last_observer = row
                    if (row and row["state"] == "active"
                            and row["query"].strip().rstrip(";").strip().upper() == "COMMIT"
                            and row["wait_event_type"] == "Lock" and row["wait_event"] == "advisory"):
                        lock = await admin.fetchval(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid=$1 AND locktype='advisory' "
                            "AND NOT granted)", pid)
                        if lock:
                            observed = True
                            record_property("g1_commit_backend_pid", str(pid))
                            record_property("g1_commit_observer_state", row["state"])
                            record_property("g1_commit_observer_query", row["query"])
                            record_property("g1_commit_observer_wait_event_type", row["wait_event_type"])
                            record_property("g1_commit_observer_wait_event", row["wait_event"])
                            record_property("g1_commit_advisory_lock_ungranted", "true")
                            break
                    await asyncio.sleep(0.1)
                if not observed:
                    record_property("g1_commit_backend_pid", str(pid))
                    record_property("g1_commit_observer_state",
                                    last_observer["state"] if last_observer else "backend_absent")
                    record_property("g1_commit_observer_query",
                                    last_observer["query"] if last_observer else "")
                    record_property("g1_commit_observer_wait_event_type",
                                    last_observer["wait_event_type"] if last_observer else "")
                    record_property("g1_commit_observer_wait_event",
                                    last_observer["wait_event"] if last_observer else "")
                    pytest.skip("NOT_RUN: observer could not establish target backend executing "
                                "explicit COMMIT while waiting on deferred-trigger advisory lock")
                assert await admin.fetchval("SELECT pg_terminate_backend($1)", pid) is True
                with pytest.raises(DEAD):
                    await asyncio.wait_for(commit_task, 20)
            finally:
                if not commit_task.done():
                    commit_task.cancel()
                    try:
                        await commit_task
                    except asyncio.CancelledError:
                        pass
                    except DEAD:
                        pass
                await holder.fetchval("SELECT pg_advisory_unlock(724001, 91)")
            target.terminate()
            assert await admin.fetchval("SELECT count(*) FROM public.g1_commit_probe") == 0
        finally:
            target.terminate()
            await holder.close()
            await admin.close()
        # The baseline survives and the page plus its deferred marker are wholly rolled back.
        v = await db.connect()
        try:
            assert tuple(await v.fetchrow("SELECT cursor_value,version FROM living.cursors")) == ("p1", 1)
            assert await _outbox_ids(v) == ["e1"]
            assert await v.fetchval(
                "SELECT count(*) FROM living.observations WHERE object_id='obj-ok'") == 1
            assert await v.fetchval("SELECT count(*) FROM public.g1_commit_probe") == 0
        finally:
            await v.close()
        # Same-input replay is safe and produces exactly one event per page item.
        c = await db.connect()
        try:
            pg = await page(c, "e2", "e3")
            for _ in range(3):
                assert await call(c, "living_worker", COMMIT, j, "w1", f, "p1", 1, ep, "p2", pg) == 2
            assert await _outbox_ids(c) == ["e1", "e2", "e3"]
            assert tuple(await c.fetchrow("SELECT cursor_value,version FROM living.cursors")) == ("p2", 2)
        finally:
            await c.close()
