"""Focused PostgreSQL tests for db/phase2/015_ed25519_signatures.sql: real Ed25519 signatures replace the keyed-hash
stand-in for evidence, checkpoints and permit signatures (simulation program P1b-2).

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every test has its own throwaway database with all migrations applied and the actors of
test_change_ledger_sql._setup, whose verifier keys are synthetic Ed25519 public keys (lane TEST, seed = sha256 of the key
id, see _ed25519_fixtures). A "session" is a login role assumed with SET LOCAL SESSION AUTHORIZATION (as in
test_change_hardening_c_sql); a superuser session is the legacy-fixture exemption of the stand-in rule.

Item -> tests:
  G1 storage and dispatcher   g1_storage_*, g1_signature_ok_*
  G2 the three check sites    g2_evidence_*, g2_checkpoint_*, g2_permit_*   (same error codes as the old checks)
  G3 registration rule        g3_register_*                                  (Ed25519 only; stand-in superuser-only)
  G4 legacy rows keep working g4_legacy_*
  G5 verification count       g5_verify_count_*                              (one verification per signature)
"""
import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from _ed25519_fixtures import pub_hex, sign_hex
from _pg_harness import fails, require_dsn, throwaway_db
from test_change_hardening_c_sql import login, sess
from test_change_ledger_sql import C, T, L, _setup, sha

pytestmark = pytest.mark.integration

CHK = "vk-chk"
LEGACY_MATERIAL = "L" * 32          # a keyed-hash stand-in secret: not 64 lowercase hex characters


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


# ---------------------------------------------------------------------------------------------- helpers
async def ev_args(led, cid, tok, call_id, *, binding_of=None):
    """record_evidence arguments after (t, c) without the signature; also returns the bound text and a second text.

    `binding_of` re-binds the record to another content (to get a valid signature over a DIFFERENT payload)."""
    content = {"nonce": uuid.uuid4().hex, "matches": True}
    at = datetime.now(UTC) + timedelta(seconds=1)
    ch = await led.conn.fetchval("SELECT change_ledger.canonical_content_hash($1::jsonb)", json.dumps(content))
    bind = await led.conn.fetchval("SELECT change_ledger.evidence_binding($1,$2,$3,$4,$5,$6)",
                                   cid, "FIELD", ch, at, tok["generation"], call_id)
    other = await led.conn.fetchval("SELECT change_ledger.evidence_binding($1,$2,$3,$4,$5,$6)",
                                    cid, "FIELD", sha("another content"), at, tok["generation"], call_id)
    return (cid, "FIELD", ch, at, json.dumps(content), "vk-wrk", bind), bind, other, (tok["generation"], call_id)


async def put_ev(led, head, sig, tail):
    return await led.call("clt_wrk", "record_evidence", *head, sig, *tail)


async def cp_parts(led):
    if await led.conn.fetchval("SELECT count(*) FROM change_ledger.events") == 0:
        await led.applying()                    # an empty ledger has no head hash to checkpoint
    head = await led.head()
    signed_at = datetime.now(UTC)
    payload = await led.conn.fetchval("SELECT change_ledger.checkpoint_payload($1,$2,$3,$4,$5,$6,$7,$8)",
                                      T, C, head["seq"], head["head_hash"], signed_at, CHK, "REAL", "sink-1")
    return head, signed_at, payload


async def put_cp(led, head, signed_at, sig):
    return await led.call("clt_chk", "record_checkpoint", head["seq"], head["head_hash"], "REAL", "sink-1", CHK, sig,
                          signed_at, True)


async def verify_calls(conn):
    """Cumulative number of executions of change_ledger.ed25519_verify (track_functions = 'pl')."""
    try:
        await conn.execute("SELECT pg_stat_force_next_flush()")
    except asyncpg.PostgresError:
        await asyncio.sleep(1.5)
    await conn.execute("SELECT pg_stat_clear_snapshot()")
    return await conn.fetchval("SELECT coalesce((SELECT calls FROM pg_stat_user_functions WHERE schemaname='change_ledger' "
                               "AND funcname='ed25519_verify'),0)")


async def counted(led, coro):
    """Run `coro`, return (its result or the PostgresError, number of Ed25519 verifications it caused)."""
    before = await verify_calls(led.conn)
    try:
        got = await coro
    except asyncpg.PostgresError as e:
        got = e
    return got, await verify_calls(led.conn) - before


# ============================================================================ G1 storage and dispatcher
async def test_g1_storage_new_rows_are_ed25519_and_the_check_constraint_guards_the_material(led):
    c = led.conn
    rows = await c.fetch("SELECT key_id, key_algorithm, length(key_material) n FROM change_ledger.verifier_keys ORDER BY 1")
    assert [(r["key_id"], r["key_algorithm"], r["n"]) for r in rows] == [
        ("vk-chk", "ED25519", 64), ("vk-wri", "ED25519", 64), ("vk-wrk", "ED25519", 64)]
    assert await c.fetchval("SELECT column_default FROM information_schema.columns WHERE table_schema='change_ledger' "
                            "AND table_name='verifier_keys' AND column_name='key_algorithm'") == "'ED25519'::text"
    # an Ed25519 row must hold a 64 lowercase hex public key, even for the table owner / a superuser
    for bad in ("x" * 32, "A" * 64, "a" * 63, "a" * 65):
        with pytest.raises(asyncpg.CheckViolationError):
            await c.execute("INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material) "
                            "VALUES($1,$2,'vk-bad','clt_wrk',$3)", T, C, bad)
    with pytest.raises(asyncpg.CheckViolationError):
        await c.execute("INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material,"
                        "key_algorithm) VALUES($1,$2,'vk-bad','clt_wrk',$3,'RSA')", T, C, LEGACY_MATERIAL)
    # a legacy row is arranged by stating the algorithm explicitly
    await c.execute("INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material,"
                    "key_algorithm) VALUES($1,$2,'vk-old','clt_wrk',$3,'KEYED_HASH_STANDIN')", T, C, LEGACY_MATERIAL)
    # the auditor sees the algorithm but never the key material
    got = await led.sql("clt_aud", "SELECT key_id, key_algorithm FROM change_ledger.verifier_keys ORDER BY 1")
    assert [(r[0], r[1]) for r in got][-1] == ("vk-wrk", "ED25519")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await led.sql("clt_aud", "SELECT key_material FROM change_ledger.verifier_keys")
    # the dispatcher is an internal: no runtime role can call it
    for role in ("clt_wrk", "clt_chk", "clt_dave", "clt_aud"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.sql(role, "SELECT change_ledger.signature_ok('ED25519','a','b','c')")


async def test_g1_signature_ok_dispatches_by_algorithm_and_fails_closed(led):
    c = led.conn
    pub, msg = pub_hex("vk-wrk"), "binding text"
    good = sign_hex("vk-wrk", msg)

    async def ok(alg, mat, payload, sig):
        return await c.fetchval("SELECT change_ledger.signature_ok($1,$2,$3,$4)", alg, mat, payload, sig)

    assert await ok("ED25519", pub, msg, good) is True
    assert await ok("ED25519", pub, msg + "!", good) is False                    # a different payload
    assert await ok("ED25519", pub_hex("vk-wri"), msg, good) is False           # another registered key
    assert await ok("ED25519", pub, msg, sign_hex("vk-wri", msg)) is False      # a signature by another key
    # malformed inputs are false (and never reach the verifier, see g5)
    for sig in ("", "zz", good[:-2], good + "00", good.upper(), "f" * 64, "f" * 128):
        assert await ok("ED25519", pub, msg, sig) is False, sig[:16]
    assert await ok("ED25519", pub.upper(), msg, good) is False
    assert await ok("ED25519", pub[:-2], msg, good) is False
    # NULLs and unknown algorithms fail closed
    for args in ((None, pub, msg, good), ("ED25519", None, msg, good), ("ED25519", pub, None, good),
                 ("ED25519", pub, msg, None), ("RSA", pub, msg, good), ("ed25519", pub, msg, good)):
        assert await ok(*args) is False, args
    # the legacy algorithm keeps the old comparison, and no algorithm accepts the other one's signature
    kh = await c.fetchval("SELECT change_ledger.keyed_signature($1,$2)", LEGACY_MATERIAL, msg)
    assert await ok("KEYED_HASH_STANDIN", LEGACY_MATERIAL, msg, kh) is True
    assert await ok("KEYED_HASH_STANDIN", LEGACY_MATERIAL, msg + "!", kh) is False
    assert await ok("KEYED_HASH_STANDIN", LEGACY_MATERIAL, msg, good) is False
    assert await ok("ED25519", pub, msg, sha(f"{pub}:{msg}")) is False          # a keyed hash is not an Ed25519 signature


# ============================================================================ G2 the three check sites
async def test_g2_evidence_signature_is_refused_with_the_old_code_unless_ed25519_valid(led):
    cid, tok, call_id = await led.applying()
    head, bind, other, tail = await ev_args(led, cid, tok, call_id)
    refused = [
        ("zz", "malformed (not hex)"), ("f" * 64, "a 64-hex string (the old stand-in length)"),
        ("f" * 128, "well formed, wrong"), (sign_hex("vk-wrk", bind).upper(), "valid bytes in upper case"),
        (sign_hex("vk-wri", bind), "signature by another registered key"),
        (sign_hex("vk-unregistered", bind), "signature by an unregistered key"),
        (sign_hex("vk-wrk", other), "valid signature over a different payload"),
        (sha(f"{pub_hex('vk-wrk')}:{bind}"), "the old keyed-hash signature of the same key"),
    ]
    for sig, _why in refused:
        await fails("EVIDENCE_UNSIGNED", put_ev(led, head, sig, tail))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.evidence_records") == 0
    eid = await put_ev(led, head, sign_hex("vk-wrk", bind), tail)
    assert await put_ev(led, head, sign_hex("vk-wrk", bind), tail) == eid          # a valid replay is idempotent
    row = await led.conn.fetchrow("SELECT signer_key_id, length(signature) n FROM change_ledger.evidence_records")
    assert (row["signer_key_id"], row["n"]) == ("vk-wrk", 128)


async def test_g2_checkpoint_signature_is_refused_with_the_old_code_unless_ed25519_valid(led):
    head, signed_at, payload = await cp_parts(led)
    for sig in ("zz", "f" * 64, "f" * 128, sign_hex(CHK, payload).upper(), sign_hex("vk-wrk", payload),
                sign_hex(CHK, payload + "x"), sha(f"{pub_hex(CHK)}:{payload}")):
        await fails("CHECKPOINT_UNAVAILABLE", put_cp(led, head, signed_at, sig))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.checkpoints") == 0
    seq = await put_cp(led, head, signed_at, sign_hex(CHK, payload))
    assert seq >= 1
    row = await led.conn.fetchrow("SELECT signer_key_id, length(signature) n, verified FROM change_ledger.checkpoints")
    assert (row["signer_key_id"], row["n"], row["verified"]) == (CHK, 128, True)


async def test_g2_permit_signature_is_refused_with_the_old_code_unless_ed25519_valid(led):
    cid, tok, call_id, permit = await led.permitted()
    payload = "change-ledger-permit|v1|" + permit["permit_digest"]
    gen = tok["generation"]

    async def attach(sig):
        return await led.call("clt_chk", "attach_permit_signature", cid, gen, CHK, sig)

    for sig in ("zz", "f" * 64, "f" * 128, sign_hex(CHK, payload).upper(), sign_hex("vk-wrk", payload),
                sign_hex(CHK, "change-ledger-permit|v1|" + sha("other digest")), sha(f"{pub_hex(CHK)}:{payload}")):
        await fails("CHECKPOINT_UNAVAILABLE", attach(sig))
    assert await led.conn.fetchval("SELECT signature FROM change_ledger.dispatch_permits WHERE change_id=$1", cid) is None
    await attach(sign_hex(CHK, payload))
    assert await led.conn.fetchval("SELECT signature FROM change_ledger.dispatch_permits WHERE change_id=$1",
                                   cid) == sign_hex(CHK, payload)


# ============================================================================ G3 registration rule
async def test_g3_register_new_keys_accept_only_ed25519_for_a_normal_session(led):
    a = await login(led, "clt_login_a", "clt_dave", "clt_erin")
    b = await login(led, "clt_login_b", "clt_erin")
    new = pub_hex("vk-new")
    n_keys = await led.conn.fetchval("SELECT count(*) FROM change_ledger.verifier_keys")
    # direct call: the stand-in is refused at once (before any two-person question); a valid Ed25519 key is a
    # widening, so a single operator still gets TWO_PERSON_REQUIRED (the 010 rule is untouched)
    await fails("SCHEMA_INVALID", sess(led, a, "clt_dave", "register_verifier_key", "vk-new", "clt_wrk", LEGACY_MATERIAL))
    await fails("TWO_PERSON_REQUIRED", sess(led, a, "clt_dave", "register_verifier_key", "vk-new", "clt_wrk", new))
    # 64 hex characters that are not a curve point can never verify anything: refused for everybody, superuser too
    await fails("SCHEMA_INVALID", sess(led, a, "clt_dave", "register_verifier_key", "vk-new", "clt_wrk", "f" * 64))
    await fails("SCHEMA_INVALID", led.call("clt_dave", "register_verifier_key", "vk-new", "clt_wrk", "f" * 64))
    # the two-person road refuses the stand-in at proposal time and accepts an Ed25519 key
    await fails("SCHEMA_INVALID", sess(led, a, "clt_dave", "propose_registry_change", "VERIFIER_KEY",
                                       json.dumps({"key_id": "vk-new", "role_name": "clt_wrk",
                                                   "key_material": LEGACY_MATERIAL})))
    params = json.dumps({"key_id": "vk-new", "role_name": "clt_wrk", "key_material": new})
    cid = await sess(led, a, "clt_dave", "propose_registry_change", "VERIFIER_KEY", params)
    dg = await led.conn.fetchval("SELECT params_digest FROM change_ledger.registry_changes WHERE change_id=$1", cid)
    await sess(led, b, "clt_erin", "approve_registry_change", cid, dg)
    row = await led.conn.fetchrow("SELECT key_algorithm, key_material, role_name, status FROM change_ledger.verifier_keys "
                                  "WHERE key_id='vk-new'")
    assert (row["key_algorithm"], row["key_material"], row["role_name"], row["status"]) == (
        "ED25519", new, "clt_wrk", "ACTIVE")
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.verifier_keys") == n_keys + 1
    ev = await led.conn.fetchval("SELECT payload FROM change_ledger.events WHERE event_type='VERIFIER_KEY_REGISTERED' "
                                 "ORDER BY seq DESC LIMIT 1")
    ev = json.loads(ev) if isinstance(ev, str) else ev
    assert ev["algorithm"] == "ED25519" and ev["key_id"] == "vk-new" and new not in json.dumps(ev)
    # the new key signs: evidence by a worker is accepted under it (key id vk-new, role clt_wrk)
    cid2, tok, call_id = await led.applying(request_id="g3")
    head, bind, _, tail = await ev_args(led, cid2, tok, call_id)
    head = (*head[:5], "vk-new", head[6])
    await put_ev(led, head, sign_hex("vk-new", bind), tail)
    # a proposal made by a superuser (legacy fixture) cannot be APPLIED by a normal session: the core checks again
    legacy = json.dumps({"key_id": "vk-old", "role_name": "clt_wrk", "key_material": LEGACY_MATERIAL})
    cid3 = await led.call("clt_dave", "propose_registry_change", "VERIFIER_KEY", legacy)
    dg3 = await led.conn.fetchval("SELECT params_digest FROM change_ledger.registry_changes WHERE change_id=$1", cid3)
    await fails("SCHEMA_INVALID", sess(led, b, "clt_erin", "approve_registry_change", cid3, dg3))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.verifier_keys WHERE key_id='vk-old'") == 0


async def test_g3_register_a_superuser_session_may_still_arrange_a_legacy_key(led):
    out = await led.dual("VERIFIER_KEY", {"key_id": "vk-old", "role_name": "clt_wrk", "key_material": LEGACY_MATERIAL})
    assert out["kind"] == "VERIFIER_KEY"
    assert await led.conn.fetchval("SELECT key_algorithm FROM change_ledger.verifier_keys WHERE key_id='vk-old'") \
        == "KEYED_HASH_STANDIN"
    # a normal session cannot even repeat that exact legacy key (named limit of 015)
    a = await login(led, "clt_login_a", "clt_dave")
    await fails("SCHEMA_INVALID", sess(led, a, "clt_dave", "register_verifier_key", "vk-old", "clt_wrk", LEGACY_MATERIAL))
    # revocation still narrows, for every algorithm
    await led.call("clt_dave", "revoke_verifier_key", "vk-old")
    assert await led.conn.fetchval("SELECT status FROM change_ledger.verifier_keys WHERE key_id='vk-old'") == "REVOKED"


# ============================================================================ G4 legacy rows keep working
async def test_g4_legacy_stand_in_row_still_verifies_and_is_not_confused_with_ed25519(led):
    await led.conn.execute("INSERT INTO change_ledger.verifier_keys(tenant_id,company_id,key_id,role_name,key_material,"
                           "key_algorithm) VALUES($1,$2,'vk-old','clt_wrk',$3,'KEYED_HASH_STANDIN')", T, C, LEGACY_MATERIAL)
    cid, tok, call_id = await led.applying()
    head, bind, other, tail = await ev_args(led, cid, tok, call_id)
    head = (*head[:5], "vk-old", head[6])
    await fails("EVIDENCE_UNSIGNED", put_ev(led, head, sign_hex("vk-old", bind), tail))      # Ed25519 over a stand-in row
    await fails("EVIDENCE_UNSIGNED", put_ev(led, head, sha(f"{LEGACY_MATERIAL}:{other}"), tail))
    eid = await put_ev(led, head, sha(f"{LEGACY_MATERIAL}:{bind}"), tail)                    # the old comparison
    assert eid is not None
    # and an Ed25519 row refuses the keyed hash of its own public key (algorithm confusion)
    head2, bind2, _, tail2 = await ev_args(led, cid, tok, call_id)
    await fails("EVIDENCE_UNSIGNED", put_ev(led, head2, sha(f"{pub_hex('vk-wrk')}:{bind2}"), tail2))


# ============================================================================ G5 one verification per signature
async def test_g5_verify_count_per_ledger_call_is_one_and_zero_for_malformed(led):
    await led.conn.execute("SET track_functions = 'pl'")
    cid, tok, call_id, permit = await led.permitted()           # includes record_checkpoint calls, not measured below
    head, bind, other, tail = await ev_args(led, cid, tok, call_id)
    payload = "change-ledger-permit|v1|" + permit["permit_digest"]

    # record_evidence: malformed 0, well formed but wrong 1, valid 1
    _, n = await counted(led, put_ev(led, head, "zz", tail))
    assert n == 0
    _, n = await counted(led, put_ev(led, head, sign_hex("vk-wrk", other), tail))
    assert n == 1
    got, n = await counted(led, put_ev(led, head, sign_hex("vk-wrk", bind), tail))
    assert isinstance(got, uuid.UUID) and n == 1
    # record_checkpoint
    h, signed_at, cp_payload = await cp_parts(led)
    _, n = await counted(led, put_cp(led, h, signed_at, "f" * 64))
    assert n == 0
    got, n = await counted(led, put_cp(led, h, signed_at, sign_hex(CHK, cp_payload)))
    assert isinstance(got, int) and n == 1
    # attach_permit_signature
    got, n = await counted(led, led.call("clt_chk", "attach_permit_signature", cid, tok["generation"], CHK,
                                         sign_hex(CHK, payload)))
    assert not isinstance(got, Exception) and n == 1
    # register_verifier_key (exact repeat of an Ed25519 key): decompresses the key, never verifies a signature
    _, n = await counted(led, led.call("clt_dave", "register_verifier_key", "vk-wrk", "clt_wrk", pub_hex("vk-wrk")))
    assert n == 0
    # the typed paths (complete_signed, verify_signed, resolve_unknown_signed, witness_cosign_signed) take evidence ids
    # that record_evidence already verified: the per-call count of the whole flow is the number of evidence records
    before = await verify_calls(led.conn)
    await led.evidence(cid, "OBSERVATION", {"effect_present": True})
    assert await verify_calls(led.conn) - before == 1
