"""G1 review-2 integration tests: B1 page replay, B2 outbox fence, B3 knowledge horizon,
M1 attestation trust, M2 scope revocation. Needs ERP_PHASE2_TEST_DSN (see the hardening module).
Fixtures and helpers are reused from test_g1_postgres_integration_hardening.py.
"""
# ruff: noqa: F811, F401
import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from test_g1_postgres_integration_hardening import (  # (env is an imported pytest fixture)
    D1,
    FUTURE,
    INGEST,
    OBS_AT,
    _seed_outbox,
    attest,
    call,
    env,
    ev_digest,
    fails,
    ingest,
    scope,
)

pytestmark = pytest.mark.integration

COMMIT = "SELECT living.commit_cursor_page('A','s1','conn',$1,'w',$2,$3,$4,0,$5,$6::jsonb)"
KNOWN = "SELECT object_id,revision_id FROM living.as_known_at('A','s1',$1) ORDER BY object_id"


async def _event(c, eid, n=1):
    body = json.dumps({"event_id": eid, "n": n})
    dg = await c.fetchval("SELECT encode(sha256(convert_to($1::jsonb::text,'UTF8')),'hex')", body)
    return {"event_id": eid, "n": n, "digest": dg}


# ---- B1 ----
async def test_b1_page_replay_identical_ok_changed_batch_conflicts(env):
    c = env.conn
    await call(c, "living_worker", "SELECT living.create_cursor('A','s1','conn','p0')")
    j = uuid.uuid4()
    await call(c, "living_worker", "SELECT living.enqueue_job('A','s1',$1,'k',$2,'i1','{}'::jsonb)", j, D1)
    f = await call(c, "living_worker", "SELECT living.acquire_job('A','s1',$1,'w',60)", j)
    e1, e2 = await _event(c, "e1"), await _event(c, "e2", 2)
    page = json.dumps([e1])
    assert await call(c, "living_worker", COMMIT, j, f, "p0", 0, "p1", page) == 1
    assert await call(c, "living_worker", COMMIT, j, f, "p0", 0, "p1", page) == 1  # identical replay
    for bad in ("[]", json.dumps([e2]), json.dumps([e1, e2])):
        await fails("CONFLICTING_PAGE_REPLAY", call(c, "living_worker", COMMIT, j, f, "p0", 0, "p1", bad))
    assert await c.fetchrow("SELECT cursor_value,version FROM living.cursors") == ("p1", 1)
    assert await c.fetchval("SELECT count(*) FROM living.outbox") == 1
    assert await c.fetchval("SELECT event_id FROM living.outbox") == "e1"


# ---- B2 ----
async def test_b2_claim_generation_fences_reclaim_by_same_name(env):
    c = env.conn
    await c.fetchval("SELECT living.add_role_scope('living_publisher','A','s1')")
    await _seed_outbox(c, 1)
    assert await c.fetchval(
        "SELECT to_regprocedure('living.claim_outbox(text,text,text,integer,integer,integer)')") is None
    claim = "SELECT claim_generation FROM living.claim_outbox('A','s1',1,60,5)"
    fin = "SELECT living.finish_outbox('A','s1','conn','e0',$1,true,5)"
    async with scope(c, "living_publisher"):
        g1 = (await c.fetch(claim))[0]["claim_generation"]
    await c.execute("UPDATE living.outbox SET lease_until=clock_timestamp()-interval '1 second'")
    async with scope(c, "living_publisher"):
        g2 = (await c.fetch(claim))[0]["claim_generation"]
    assert (g1, g2) == (1, 2)
    await fails("STALE_OUTBOX_LEASE", call(c, "living_publisher", fin, g1))  # same identity, old claim
    assert await c.fetchval("SELECT status FROM living.outbox") == "PENDING"
    other = "pub_b_" + uuid.uuid4().hex[:8]  # a different authenticated identity, same duty role
    await c.execute(f"CREATE ROLE {other} NOLOGIN IN ROLE living_publisher")
    try:
        await fails("STALE_OUTBOX_LEASE", call(c, other, fin, g2))
        await call(c, "living_publisher", fin, g2)
        assert await c.fetchval("SELECT status FROM living.outbox") == "DELIVERED"
    finally:
        await c.execute(f"DROP ROLE {other}")


# ---- B3 ----
async def test_b3_unsettled_horizon_is_rejected_and_answers_never_change(env):
    a, b = env.conn, await env.connect()
    try:
        await ingest(a, "o0", uuid.uuid4())
        await asyncio.sleep(0.05)
        await ingest(a, "o0b", uuid.uuid4())
        k_early = await a.fetchval("SELECT min(recorded_at) FROM living.observations")
        tx = a.transaction()
        await tx.start()
        await a.execute("SET LOCAL ROLE living_worker")
        await a.fetchval("SELECT living.set_scope('A','s1',NULL)")
        await a.fetchval(INGEST, uuid.uuid4(), "o1", uuid.uuid4(), D1, None, OBS_AT, None, "{}")
        await asyncio.sleep(0.2)
        k_mid = await b.fetchval("SELECT clock_timestamp()")
        async with scope(b, "living_worker"):
            before_early = [r["object_id"] for r in await b.fetch(KNOWN, k_early)]
            assert before_early == ["o0"]
        async with scope(b, "living_worker"):
            await fails("KNOWLEDGE_HORIZON_NOT_SETTLED", b.fetch(KNOWN, k_mid))
        async with scope(b, "living_worker"):
            await fails("KNOWLEDGE_HORIZON_NOT_SETTLED", b.fetch(
                "SELECT * FROM living.as_effective_at('A','s1',$1,$2)", k_mid, k_mid))
        async with scope(b, "living_worker"):
            horizon = await b.fetchval("SELECT living.knowledge_horizon('A','s1')")
        assert horizon < k_mid
        await tx.commit()
        async with scope(b, "living_worker"):
            assert [r["object_id"] for r in await b.fetch(KNOWN, k_early)] == before_early
            assert [r["object_id"] for r in await b.fetch(KNOWN, k_mid)] == ["o0", "o0b", "o1"]
            await fails("KNOWLEDGE_HORIZON_NOT_SETTLED", b.fetch(
                KNOWN, datetime.now(UTC) + timedelta(hours=1)))  # the future is never settled
        async with b.transaction(isolation="repeatable_read"):
            await b.execute("SET LOCAL ROLE living_worker")
            await b.fetchval("SELECT living.set_scope('A','s1',NULL)")
            await fails("KNOWLEDGE_HORIZON_NOT_SETTLED", b.fetch(KNOWN, k_early))
    finally:
        await b.close()


# ---- M1 ----
async def _promotable(c, evidence="ev1"):
    rev = uuid.uuid4()
    await ingest(c, "o1", rev)
    return rev


PROMOTE = "SELECT living.promote_head('A','s1','m1',0,$1,$2,$3)"


async def test_m1_absent_forged_expired_revoked_untrusted_evidence_cannot_promote(env):
    c = env.conn
    await call(c, "living_promoter", "SELECT living.create_head('A','s1','m1')")
    rev = await _promotable(c)

    async def must_fail(code, evidence):
        await fails(code, call(c, "living_promoter", PROMOTE, rev, uuid.uuid4(), evidence))
        assert await c.fetchval("SELECT version FROM living.accepted_heads") == 0

    await must_fail("EVIDENCE_NOT_FOUND", "absent")
    # forged: digest not bound to this revision (rejected at record time ...)
    await fails("EVIDENCE_DIGEST_MISMATCH", attest(c, rev, evidence="forged", bound_to="f" * 64))
    # ... and when the owner inserts a forged row directly (wrong digest / NULL digest+expiry)
    ins = ("INSERT INTO living.attestations(tenant_id,source_id,attestation_id,revision_id,"
           "proposer_subject,observer_subject,evidence_ref,evidence_digest,expires_at)"
           " VALUES('A','s1',$1,$2,'prop','living_worker',$3,$4,$5)")
    await c.execute(ins, uuid.uuid4(), rev, "forged-row", "e" * 64, FUTURE)
    await must_fail("EVIDENCE_DIGEST_MISMATCH", "forged-row")
    await c.execute(ins, uuid.uuid4(), rev, "null-row", None, None)
    await must_fail("EVIDENCE_EXPIRED", "null-row")
    # expired
    await fails("EVIDENCE_EXPIRED", attest(c, rev, evidence="old", expires=datetime(2020, 1, 1, tzinfo=UTC)))
    await c.execute(ins, uuid.uuid4(), rev, "past-row", ev_digest(D1, "past-row"),
                    datetime(2020, 1, 1, tzinfo=UTC))
    await must_fail("EVIDENCE_EXPIRED", "past-row")
    soon = datetime.now(UTC) + timedelta(seconds=1.5)
    await attest(c, rev, evidence="soon", expires=soon)
    await asyncio.sleep(2)
    await must_fail("EVIDENCE_EXPIRED", "soon")
    # REJECT decision
    await attest(c, rev, evidence="rej", decision="REJECT")
    await must_fail("EVIDENCE_NOT_APPROVED", "rej")
    # revoked (also immutable otherwise)
    att = uuid.uuid4()
    await attest(c, rev, evidence="rev", att=att)
    await call(c, "living_worker", "SELECT living.revoke_attestation('A','s1',$1)", att)
    await must_fail("EVIDENCE_REVOKED", "rev")
    await fails("IMMUTABLE_LEDGER", c.execute(
        "UPDATE living.attestations SET revoked_at=NULL WHERE attestation_id=$1", att))
    await fails("IMMUTABLE_LEDGER", c.execute("UPDATE living.attestations SET decision='APPROVE'"))
    # trust removed after recording / expired trust / untrusted recorder
    await attest(c, rev, evidence="trust")
    await c.execute("SELECT living.set_trusted_reviewer('living_worker','A','s1',false,$1)", FUTURE)
    await must_fail("REVIEWER_NOT_TRUSTED", "trust")
    await fails("REVIEWER_NOT_TRUSTED", attest(c, rev, evidence="late"))
    await c.execute("SELECT living.set_trusted_reviewer('living_worker','A','s1',true,$1)",
                    datetime(2020, 1, 1, tzinfo=UTC))
    await must_fail("REVIEWER_NOT_TRUSTED", "trust")
    # runtime roles cannot manage the trust list
    await fails("permission denied", call(
        c, "living_worker", "SELECT living.set_trusted_reviewer('living_worker','A','s1',true,$1)", FUTURE))
    await fails("permission denied", call(c, "living_worker", "SELECT * FROM living.trusted_reviewers"))
    # positive control: trust restored, valid evidence promotes
    await c.execute("SELECT living.set_trusted_reviewer('living_worker','A','s1',true,$1)", FUTURE)
    await attest(c, rev, evidence="good")
    assert await call(c, "living_promoter", PROMOTE, rev, uuid.uuid4(), "good") == 1


# ---- M2 ----
async def test_m2_role_scope_change_bumps_epoch_and_old_context_cannot_commit(env):
    c, o = env.conn, await env.connect()
    try:
        await call(c, "living_worker", "SELECT living.create_cursor('A','s1','conn','p0')")
        j = uuid.uuid4()
        await call(c, "living_worker", "SELECT living.enqueue_job('A','s1',$1,'k',$2,'i1','{}'::jsonb)", j, D1)
        f = await call(c, "living_worker", "SELECT living.acquire_job('A','s1',$1,'w',60)", j)
        epoch = lambda: o.fetchval("SELECT scope_epoch FROM living.sources")
        e0 = await epoch()
        # a pure INSERT (widening) does not bump
        await o.fetchval("SELECT living.add_role_scope('living_reader','A','s1')")
        assert await epoch() == e0
        tx = c.transaction()  # context authorised at epoch e0 ...
        await tx.start()
        await c.execute("SET LOCAL ROLE living_worker")
        await c.fetchval("SELECT living.set_scope('A','s1',NULL)")
        await o.execute("DELETE FROM living.role_scope WHERE role_name='living_reader'")  # ... revoked here
        assert await epoch() == e0 + 1
        await fails("SCOPE_REVOKED", c.fetchval(COMMIT, j, f, "p0", 0, "p1", "[]"))
        await tx.rollback()
        assert await c.fetchrow("SELECT cursor_value,version FROM living.cursors") == ("p0", 0)
        await o.execute("UPDATE living.role_scope SET company_id=NULL WHERE role_name='living_promoter'")
        assert await epoch() == e0 + 2
        await o.execute("TRUNCATE living.role_scope")
        assert await epoch() == e0 + 3
        await fails("SCOPE_NOT_GRANTED", call(c, "living_worker", "SELECT 1"))  # grants are gone
    finally:
        await o.close()

