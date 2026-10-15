"""Self-contained PostgreSQL test of change_ledger.ed25519_verify (db/phase2/014_ed25519_verify.sql).

The function-definition part of migration 014 (the text inside its EXECUTE dollar-quoted body, cut before the wiring
block) is applied to a BARE throwaway database that only has the schema change_ledger, then every answer is compared
with the pure-Python reference verifier (business_ai_gateway.phase2.ed25519), which is also the signer of the vectors.
Needs ERP_PHASE2_TEST_DSN (a superuser DSN of a disposable cluster); skipped otherwise. NON-GATING PROTOTYPE.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import time
import uuid
from pathlib import Path

import asyncpg
import pytest

from business_ai_gateway.phase2 import ed25519

_MIGRATION = Path(__file__).resolve().parents[2] / "db" / "phase2" / "014_ed25519_verify.sql"
_L = 2**252 + 27742317777372353535851937790883648493
_P = 2**255 - 19

# RFC 8032 section 7.1 TEST 1..3: (name, seed, public key, message, signature) -- hex
_RFC = [
    (
        "TEST 1",
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
        "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "TEST 2",
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da08"
        "5ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "TEST 3",
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18"
        "ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
]


def _definitions_sql() -> str:
    text = _MIGRATION.read_text(encoding="utf-8")
    tag = "$body$"
    start = text.index(tag) + len(tag)
    end = text.rindex(tag + ";")
    body = text[start:end]
    cut = re.search(r"^-- ====.*wiring", body, re.MULTILINE)
    assert cut is not None, "wiring block header not found in 014"
    return body[: cut.start()]


class _Db:
    def __init__(self, loop, conn):
        self.loop, self.conn = loop, conn

    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def verify(self, pub, msg, sig):
        return self.run(
            self.conn.fetchval("SELECT change_ledger.ed25519_verify($1::bytea,$2::bytea,$3::bytea)", pub, msg, sig)
        )


@pytest.fixture(scope="module")
def db():
    dsn = os.environ.get("ERP_PHASE2_TEST_DSN")
    if not dsn:
        pytest.skip("NOT_RUN: ERP_PHASE2_TEST_DSN is not set")
    loop = asyncio.new_event_loop()
    name = "ed25519_sql_" + uuid.uuid4().hex[:12]
    admin = loop.run_until_complete(asyncpg.connect(dsn, timeout=10))
    loop.run_until_complete(admin.execute(f'CREATE DATABASE "{name}"'))
    conn = loop.run_until_complete(asyncpg.connect(dsn, timeout=10, database=name))
    try:
        loop.run_until_complete(conn.execute("CREATE SCHEMA change_ledger"))
        loop.run_until_complete(conn.execute(_definitions_sql()))
        yield _Db(loop, conn)
    finally:
        loop.run_until_complete(conn.close())
        loop.run_until_complete(admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        loop.run_until_complete(admin.close())
        loop.close()


def _agree(db, pub, msg, sig, expected):
    ref = ed25519.verify(pub, msg, sig)
    got = db.verify(pub, msg, sig)
    assert ref is expected, "reference verifier disagrees with the expectation"
    assert got is expected, f"SQL verifier returned {got!r}, expected {expected!r}"


@pytest.mark.parametrize("name,seed,pub,msg,sig", _RFC, ids=[v[0] for v in _RFC])
def test_rfc8032_vectors_verify_true(db, name, seed, pub, msg, sig):
    seed_b, pub_b, msg_b, sig_b = map(bytes.fromhex, (seed, pub, msg, sig))
    assert ed25519.sign(seed_b, msg_b) == sig_b  # the vector is the signer's output too
    _agree(db, pub_b, msg_b, sig_b, True)


def _t2():
    _, _, pub, msg, sig = _RFC[1]
    return bytes.fromhex(pub), bytes.fromhex(msg), bytes.fromhex(sig)


def test_random_signatures_verify_true(db):
    rng = random.Random(20261015)
    for _ in range(30):
        seed = rng.randbytes(32)
        msg = rng.randbytes(rng.randrange(0, 200))
        pub = ed25519.public_key_from_seed(seed)
        sig = ed25519.sign(seed, msg)
        _agree(db, pub, msg, sig, True)


def test_flipped_message_bit_false(db):
    pub, msg, sig = _t2()
    _agree(db, pub, bytes([msg[0] ^ 1]), sig, False)


@pytest.mark.parametrize("idx", [0, 31, 32, 63])
def test_flipped_signature_bit_false(db, idx):
    pub, msg, sig = _t2()
    bad = bytearray(sig)
    bad[idx] ^= 0x01
    _agree(db, pub, msg, bytes(bad), False)


def test_wrong_key_false(db):
    _, msg, sig = _t2()
    _agree(db, bytes.fromhex(_RFC[0][2]), msg, sig, False)


def test_s_ge_l_false(db):
    pub, msg, sig = _t2()
    s = int.from_bytes(sig[32:], "little")
    _agree(db, pub, msg, sig[:32] + (s + _L).to_bytes(32, "little"), False)
    _agree(db, pub, msg, sig[:32] + _L.to_bytes(32, "little"), False)


def test_truncated_extended_signature_false(db):
    pub, msg, sig = _t2()
    _agree(db, pub, msg, sig[:63], False)
    _agree(db, pub, msg, b"", False)
    _agree(db, pub, msg, sig + b"\x00", False)


def test_bad_key_lengths_false(db):
    pub, msg, sig = _t2()
    _agree(db, pub[:31], msg, sig, False)
    _agree(db, pub + b"\x00", msg, sig, False)
    _agree(db, b"", msg, sig, False)


def test_non_canonical_and_undecodable_points_false(db):
    pub, msg, sig = _t2()
    noncanon = _P.to_bytes(32, "little")  # y = p, a non-canonical encoding of y = 0
    _agree(db, noncanon, msg, sig, False)
    _agree(db, pub, msg, noncanon + sig[32:], False)
    _agree(db, (2).to_bytes(32, "little"), msg, sig, False)  # y = 2 has no x on the curve
    # y = 1 is the neutral point; sign bit set on x = 0 is invalid (x2 == 0 with sign 1)
    _agree(db, (1 | (1 << 255)).to_bytes(32, "little"), msg, sig, False)


_SMALL_ORDER = [
    "0100000000000000000000000000000000000000000000000000000000000000",  # order 1 (neutral)
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",  # order 2
    "0000000000000000000000000000000000000000000000000000000000000000",  # order 4
    "0000000000000000000000000000000000000000000000000000000000000080",  # order 4
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",  # order 8
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",  # order 8
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",  # order 8
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",  # order 8
]


def test_neutral_key_forgery_false(db):
    neutral = bytes.fromhex(_SMALL_ORDER[0])
    for msg in (b"", b"transfer 1000000", b"any other message"):
        _agree(db, neutral, msg, neutral + bytes(32), False)


def test_small_order_points_rejected_as_key_and_as_r(db):
    pub, msg, sig = _t2()
    for hx in _SMALL_ORDER:
        point = bytes.fromhex(hx)
        _agree(db, point, msg, sig, False)
        _agree(db, pub, msg, point + sig[32:], False)
        _agree(db, point, msg, point + bytes(32), False)


def test_is_small_order_helper(db):
    q = "SELECT change_ledger.ed25519_is_small_order($1::bytea)"
    for hx in _SMALL_ORDER:
        assert db.run(db.conn.fetchval(q, bytes.fromhex(hx))) is True
        assert ed25519.is_small_order(bytes.fromhex(hx)) is True
    base = ed25519.public_key_from_seed(bytes(32))
    pub, _, _ = _t2()
    for b in (base, pub, b"\x02" + bytes(31)):  # regular key, regular key, undecodable
        assert db.run(db.conn.fetchval(q, b)) is False
        assert ed25519.is_small_order(b) is False
    assert db.run(db.conn.fetchval(q, None)) is False


def test_null_arguments_return_false(db):
    pub, msg, sig = _t2()
    q = "SELECT change_ledger.ed25519_verify($1::bytea,$2::bytea,$3::bytea)"
    for args in ((None, msg, sig), (pub, None, sig), (pub, msg, None), (None, None, None)):
        assert db.run(db.conn.fetchval(q, *args)) is False


def test_function_is_immutable_and_not_strict(db):
    row = db.run(
        db.conn.fetchrow(
            "SELECT provolatile::text AS provolatile, proisstrict FROM pg_proc WHERE oid = 'change_ledger.ed25519_verify(bytea,bytea,bytea)'::regprocedure"
        )
    )
    assert row["provolatile"] == "i" and row["proisstrict"] is False


def test_time_per_verify_bare_and_hardened(db):
    """Print the per-call time once; the hardened variant adds the 011 wiring's per-function search_path setting."""
    pub, msg, sig = _t2()

    def avg(n):
        t0 = time.perf_counter()
        for _ in range(n):
            assert db.verify(pub, msg, sig) is True
        return (time.perf_counter() - t0) / n

    bare = avg(5)
    db.run(
        db.conn.execute(
            """DO $x$ DECLARE f record; BEGIN
            FOR f IN SELECT p.oid::regprocedure AS sig FROM pg_catalog.pg_proc p
              JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='change_ledger' LOOP
              EXECUTE format('ALTER FUNCTION %s SECURITY DEFINER SET search_path = pg_catalog, pg_temp', f.sig);
            END LOOP; END $x$"""
        )
    )
    hardened = avg(5)
    assert db.verify(pub, msg, sig) is True
    print(f"\nED25519_SQL_TIMING per verify: bare={bare * 1000:.1f} ms, hardened search_path={hardened * 1000:.1f} ms")
