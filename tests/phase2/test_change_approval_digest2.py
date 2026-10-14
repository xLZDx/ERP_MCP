"""Focused tests for S12-APPROVAL-2 (db/phase2/009_approval_digest_2.sql, change/proposal.py ``approval_canonical_text``).

Contract: docs/phase2/S12_APPROVAL_DIGEST_2_SPEC.md. Cross-language equality: the canonical text produced by Python is
stored by the PostgreSQL ledger as given; the digest the ledger computes from the stored text must equal the digest
Python computes from the same text, for all four operation kinds (plus a repair), nulls, Unicode, decimal spellings,
field order, an altered budget, a changed target and stale versions. Negatives: payload substituted after approval,
replayed approval, a digest or approval of the old version SQL-1.

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it: skip NOT_RUN, or fail when
ERP_PHASE2_REQUIRE_PG=1. Every DB test has its own throwaway database with all migrations (001-009) applied and the
actors of test_change_ledger_sql._setup. Superuser access arranges state no API can produce and reads results.
"""
import hashlib
import json
import uuid
from decimal import Decimal

import _change_helpers as h
import asyncpg
import pytest
from _approval_envelope import ensure_envelope
from _pg_harness import FILES, MIGRATIONS, fails, require_dsn, throwaway_db
from test_change_ledger_sql import BASE, C, DEFAULT_GRANT, ORG, T, L, _setup, exp, sha

from business_ai_gateway.phase2 import change as ch
from business_ai_gateway.phase2.change import Scope, canonical_json

pytestmark = pytest.mark.integration

GRANT = DEFAULT_GRANT[(T, C)]
CLOSED_KEYS = {
    "digest_version", "change_id", "kind", "scope", "payload", "payload_digest", "target_ref", "target_version",
    "business_state_digest", "parent_change_id", "repair_for", "declared_target_class", "allowed_effects", "budget",
    "duplicate_override", "rule_table_version", "epoch_dependencies", "preview_digest", "approval_nonce", "expires_at",
}
KINDS = ["CREATE_DRAFT", "UPDATE_DRAFT", "POST", "UNPOST", "REPAIR"]
UNICODE_COMMENT = "Привет \"мир\" \\ слэш\nстрока\tтаб é ü 日本語 😀 à end"


@pytest.fixture
async def led():
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        await _setup(db.conn)
        yield L(db)


def text_sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Case:
    """One SQL change plus the Python proposal that describes it."""


async def make_case(led, kind, *, payload_over=None, amount="12.50", override=None, rid=None, issue_nonce=True):
    """Propose a change in SQL and build the matching ChangeProposal in Python; kind REPAIR = UNPOST with repair_for."""
    k = Case()
    k.cid, k.kind = uuid.uuid4(), ("UNPOST" if kind == "REPAIR" else kind)
    rid = rid or uuid.uuid4().hex
    draft = k.kind in ("CREATE_DRAFT", "UPDATE_DRAFT")
    k.expires = exp()
    k.parent = None if draft else await led.propose(request_id="par-" + rid)
    k.repair = str(k.parent) if kind == "REPAIR" else None
    over = dict(payload_over or {})
    if override is not None:
        over["duplicate_override"] = {"duplicate_of_change_or_ref": override[0], "justification": override[1]}
    if k.kind == "CREATE_DRAFT":
        raw = h.raw_create(request_id=rid, payload_over=over)
    elif k.kind == "UPDATE_DRAFT":
        raw = h.raw_create(kind="UPDATE_DRAFT", request_id=rid, target_ref="doc1", target_version="v3",
                           payload_over={**over, "expected_target_version": "v3"})
    else:
        raw = h.raw_post(k.kind, request_id=rid, parent_change_id=str(k.parent), target_ref="doc1",
                         target_version="v7")
    scope = Scope(T, C, ORG, BASE)
    first = h.proposal(raw, change_id=str(k.cid), scope=scope, expires_at=k.expires, epoch_dependencies=())
    await led.call("clt_alice", "propose", k.cid, k.kind, BASE, ORG, "clt_alice", rid, first.payload_digest,
                   first.target_ref, first.target_version, k.parent, k.expires,
                   None if k.repair is None else k.parent)
    deps = json.loads(await led.conn.fetchval("SELECT epoch_dependencies FROM change_ledger.records WHERE "
                                              "change_id=$1", k.cid))
    # principal entries are part of the stored change but not of the digest: they are passed on purpose
    k.prop = h.proposal(raw, change_id=str(k.cid), scope=scope, expires_at=k.expires,
                        epoch_dependencies=tuple(sorted(deps.items())))
    assert k.prop.payload_digest == first.payload_digest
    ov = k.prop.duplicate_override
    if draft:
        await led.call("clt_alice", "declare_business_key", k.cid, sha(str(k.cid)),
                       None if ov is None else ov.duplicate_of_change_or_ref, None if ov is None else ov.justification)
    await led.call("clt_alice", "declare_target_class", k.cid, "CLONE")
    k.counts = (draft, k.kind == "POST")
    await led.call("clt_alice", "declare_budget", k.cid, GRANT, "EUR", Decimal(amount), *k.counts)
    k.budget = {"grant_id": str(GRANT), "currency": "EUR", "amount": amount, "counts_create_update": k.counts[0],
                "counts_post": k.counts[1]}
    k.cls = await led.conn.fetchval("SELECT declared_target_class FROM change_ledger.records WHERE change_id=$1", k.cid)
    assert await led.call("clt_alice", "validate", k.cid) == "VALIDATED"
    k.nonce = await led.call("clt_bob", "issue_approval_nonce", k.cid) if issue_nonce else None
    return k


def text_of(k, **over):
    args = dict(approval_nonce=k.nonce, repair_for=k.repair, declared_target_class=k.cls, budget=k.budget)
    args.update(over)
    return ch.approval_canonical_text(k.prop, **args)


async def store(led, k, text):
    return await led.call("clt_alice", "store_approval_text", k.cid, k.nonce, text)


async def stored_sha(led, k):
    return await led.conn.fetchval(
        "SELECT encode(sha256(convert_to(canonical_text,'UTF8')),'hex') FROM change_ledger.approval_envelopes "
        "WHERE change_id=$1 AND approval_nonce=$2", k.cid, k.nonce)


async def assert_equal_and_approvable(led, k, text):
    """The Python digest, the digest of the bytes PostgreSQL stored and the ledger's approval_digest are one value."""
    py = ch.approval_digest(k.prop, approval_nonce=k.nonce, repair_for=k.repair, declared_target_class=k.cls,
                            budget=k.budget)
    assert py == ch.digest_of_canonical_text(text) == text_sha(text)
    assert await store(led, k, text) == py
    assert await stored_sha(led, k) == py
    assert await led.conn.fetchval("SELECT canonical_text FROM change_ledger.approval_envelopes WHERE change_id=$1",
                                   k.cid) == text                       # stored as given, byte for byte
    st = await led.status(k.cid)
    assert st["approval_digest"] == py and st["approval_digest_version"] == "S12-APPROVAL-2"
    assert st["approval_nonce"] == k.nonce
    assert await led.call("clt_bob", "read_approval_text", k.cid) == text
    await led.call("clt_bob", "approve", k.cid, k.nonce, py)
    done = await led.status(k.cid)
    assert done["authorization"] == "APPROVED" and done["approved_digest"] == py
    assert done["approved_digest_version"] == "S12-APPROVAL-2"
    return py


# ============================================================================ offline (no database)
def test_the_canonical_text_has_exactly_the_closed_field_list_and_is_stable():
    p = h.proposal(h.raw_post("POST"))
    text = ch.approval_canonical_text(p, approval_nonce="n1")
    obj = json.loads(text)
    assert set(obj) == CLOSED_KEYS and obj["digest_version"] == "S12-APPROVAL-2" == ch.APPROVAL_DIGEST_VERSION
    assert obj["payload"] is None and obj["budget"] is None and obj["repair_for"] is None
    assert obj["declared_target_class"] is None and obj["duplicate_override"] is None and obj["approval_nonce"] == "n1"
    assert canonical_json(obj) == text                                   # re-serialization is the identity
    assert text.isascii() and ": " not in text and ", " not in text
    assert ch.approval_digest(p, approval_nonce="n1") == hashlib.sha256(text.encode()).hexdigest()
    # a draft carries its full canonical payload and the override as its own field
    d = h.proposal(h.raw_create(payload_over={"duplicate_override": {"duplicate_of_change_or_ref": "c0",
                                                                      "justification": "same invoice"}}))
    dobj = json.loads(ch.approval_canonical_text(d))
    assert dobj["payload"]["lines"][0]["amount"] == "21" and dobj["duplicate_override"]["justification"] == "same invoice"
    assert dobj["epoch_dependencies"] == [["approver", 2], ["requester", 1]]


def test_the_digest_changes_with_every_extra_field_and_ignores_principal_epoch_entries():
    p = h.proposal()
    base = ch.approval_digest(p)
    budget = {"grant_id": "g", "currency": "EUR", "amount": "5", "counts_create_update": True, "counts_post": False}
    variants = {
        "nonce": ch.approval_digest(p, approval_nonce="n"), "repair": ch.approval_digest(p, repair_for="r"),
        "class": ch.approval_digest(p, declared_target_class="CLONE"), "budget": ch.approval_digest(p, budget=budget),
        "budget2": ch.approval_digest(p, budget={**budget, "amount": "6"}),
        "budget3": ch.approval_digest(p, budget={**budget, "counts_post": True}),
    }
    assert len(set(variants.values()) | {base}) == len(variants) + 1
    # decimal spellings of the budget amount are one value; principal epoch entries are outside the digest
    assert ch.approval_digest(p, budget={**budget, "amount": "5.00"}) == variants["budget"] == \
        ch.approval_digest(p, budget={**budget, "amount": Decimal("5.0")})
    with_principal = h.proposal(epoch_dependencies=(("approver", 2), ("principal:x", 9), ("requester", 1)))
    assert ch.approval_digest(with_principal) == base
    for bad in ({"grant_id": "g"}, {**budget, "amount": 5.0}, {**budget, "counts_post": 1}):
        with pytest.raises(ValueError):
            ch.approval_digest(p, budget=bad)
    with pytest.raises(ValueError):
        ch.approval_canonical_text(p, approval_nonce=5)  # type: ignore[arg-type]


# ============================================================================ cross-language equality
TRICKY = [
    {"b": 1, "a": [True, False, None, 0, -5, 12345678901234567890], "": "", "é": "key"},
    {"s": "\"\\/\b\f\n\r\t\x01\x1f\x7f\x80\xa0 é Ж 日本 😀 ￿   \U0010ffff"},
    {"z": {"y": {"x": []}}, "kéy": {}, "日": 1, "😀": 2, "A": 3, "a": 4},
    "plain", [], {}, 0, [[1, [2, [3]]], {"a": {"b": None}}],
]


async def test_the_sql_serializer_equals_the_python_canonical_json_for_tricky_values(led):
    for value in TRICKY:
        loose = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False)       # not canonical on purpose
        assert await led.conn.fetchval("SELECT change_ledger.canon_json($1::jsonb)", loose) == canonical_json(value)
        shuffled = json.dumps(value, ensure_ascii=True, separators=(", ", ": "))
        assert await led.conn.fetchval("SELECT change_ledger.canon_json($1::jsonb)", shuffled) == canonical_json(value)
    await fails("SCHEMA_INVALID", led.conn.fetchval("SELECT change_ledger.canon_json('1.5'::jsonb)"))   # no floats
    await fails("SCHEMA_INVALID", led.conn.fetchval("SELECT change_ledger.canon_json('[0.0]'::jsonb)"))


@pytest.mark.parametrize("kind", KINDS)
async def test_python_and_postgres_digests_are_equal_for_every_operation_kind(led, kind):
    k = await make_case(led, kind)
    text = text_of(k)
    obj = json.loads(text)
    assert set(obj) == CLOSED_KEYS and obj["kind"] == k.kind and obj["repair_for"] == k.repair
    assert (obj["payload"] is None) == (k.kind in ("POST", "UNPOST")) and obj["budget"]["amount"] == "12.5"
    assert obj["declared_target_class"] == "DISPOSABLE_CLONE" and obj["approval_nonce"] == k.nonce
    assert obj["allowed_effects"] == (list(ch.derive_allowed_effects(ch.ChangeKind.POST)) if kind == "POST" else [])
    assert all(not key.startswith("principal:") for key, _ in obj["epoch_dependencies"]) and obj["epoch_dependencies"]
    await assert_equal_and_approvable(led, k, text)


async def test_nulls_unicode_decimal_spellings_and_override_are_equal_across_languages(led):
    # nulls: a draft has no target, no parent, no repair and a null business_state_digest
    c1 = await make_case(led, "CREATE_DRAFT", payload_over={"comment": ""})
    o1 = json.loads(text_of(c1))
    assert (o1["target_ref"], o1["target_version"], o1["parent_change_id"], o1["repair_for"],
            o1["business_state_digest"], o1["duplicate_override"]) == (None,) * 6
    await assert_equal_and_approvable(led, c1, text_of(c1))
    # Unicode (Cyrillic, CJK, an astral character, quote, backslash, control characters) and an override pair
    c2 = await make_case(led, "CREATE_DRAFT", override=("c-0", UNICODE_COMMENT[:80]),
                         payload_over={"comment": UNICODE_COMMENT, "counterparty_ref": "контрагент-日本-😀"})
    t2 = text_of(c2)
    assert t2.isascii() and "\\ud83d\\ude00" in t2           # ASCII-only output, astral character as a surrogate pair
    assert json.loads(t2)["duplicate_override"]["justification"] == UNICODE_COMMENT[:80]
    await assert_equal_and_approvable(led, c2, t2)
    # decimal normalization: spelled payload decimals and budget amounts are the same canonical text
    for i, (spelled, canon) in enumerate([("12.50", "12.5"), ("100.00", "100"), ("0", "0"), ("0.10", "0.1"),
                                          ("123456.89", "123456.89"), ("7", "7")]):
        k = await make_case(led, "CREATE_DRAFT", amount=spelled, rid=f"dec-{i}",
                            payload_over={"supplier_document_number": f"N-{i}"})
        k.budget = {**k.budget, "amount": canon}                       # the canonical spelling is what is digested
        assert ch.approval_digest(k.prop, approval_nonce=k.nonce, repair_for=None, declared_target_class=k.cls,
                                  budget={**k.budget, "amount": spelled}) == \
            ch.approval_digest(k.prop, approval_nonce=k.nonce, repair_for=None, declared_target_class=k.cls,
                               budget=k.budget)
        await assert_equal_and_approvable(led, k, text_of(k))
    spelled_payload = h.raw_create(payload_over={"supplier_document_number": "N-s"})
    spelled_payload["payload"]["lines"][0].update(price="10.500", amount="21.000")
    assert json.loads(ch.approval_canonical_text(h.proposal(spelled_payload)))["payload"]["lines"][0]["price"] == "10.5"


async def test_field_order_and_formatting_do_not_change_the_digest_and_non_canonical_text_is_refused(led):
    k = await make_case(led, "CREATE_DRAFT")
    text = text_of(k)
    obj = json.loads(text)
    reordered = dict(reversed(list(obj.items())))
    reordered["payload"] = dict(reversed(list(obj["payload"].items())))
    assert canonical_json(reordered) == text and ch.digest_of_canonical_text(canonical_json(reordered)) == \
        ch.digest_of_canonical_text(text)
    assert await led.conn.fetchval("SELECT change_ledger.canon_json($1::jsonb)",
                                   json.dumps(reordered, ensure_ascii=False, indent=1)) == text
    # the ledger hashes the stored bytes: a reordered / spaced / non-ASCII spelling of the same object is not stored
    for loose in (json.dumps(reordered), json.dumps(obj, indent=1), json.dumps(obj, sort_keys=True), text + " ",
                  "[]", "not json", ""):
        await fails("SCHEMA_INVALID", store(led, k, loose))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.approval_envelopes") == 0
    await assert_equal_and_approvable(led, k, text)


# ============================================================================ the stored text must equal the ledger state
async def test_altered_budget_changed_target_repair_and_stale_version_are_refused(led):
    k = await make_case(led, "REPAIR")
    good = text_of(k)
    assert ch.approval_digest(k.prop, approval_nonce=k.nonce, repair_for=k.repair, declared_target_class=k.cls,
                              budget={**k.budget, "amount": "13"}) != ch.digest_of_canonical_text(good)
    other_parent = str(uuid.uuid4())
    bad = {
        "altered budget amount": text_of(k, budget={**k.budget, "amount": "13"}),
        "altered budget counts": text_of(k, budget={**k.budget, "counts_post": not k.budget["counts_post"]}),
        "no budget": text_of(k, budget=None),
        "repair link dropped": text_of(k, repair_for=None),
        "repair link changed": text_of(k, repair_for=other_parent),
        "declared class": text_of(k, declared_target_class="PROD"),
        "other nonce": text_of(k, approval_nonce="x" * 64),
        "no nonce": text_of(k, approval_nonce=None),
    }
    for name, tampered in bad.items():
        await fails("DIGEST_MISMATCH", store(led, k, tampered))
    obj = json.loads(good)
    for name, patch in {
        "changed target ref": {"target_ref": "doc-other"}, "changed target version": {"target_version": "v8"},
        "changed parent": {"parent_change_id": other_parent}, "changed kind": {"kind": "POST"},
        "changed scope": {"scope": {**obj["scope"], "organization": "org-2"}},
        "changed expiry": {"expires_at": "2099-01-01T00:00:00.000000Z"},
        "changed effects": {"allowed_effects": ["X"]}, "changed rule table": {"rule_table_version": "S99"},
        "changed epochs": {"epoch_dependencies": [["target:base-1", 999]]},
        "old digest version SQL-1": {"digest_version": "S12-APPROVAL-SQL-1"},
        "old digest version 1": {"digest_version": "S12-APPROVAL-1"},
        "extra key": {"extra": 1}, "changed payload digest": {"payload_digest": "f" * 64},
    }.items():
        await fails("DIGEST_MISMATCH", store(led, k, canonical_json({**obj, **patch})))
    for name, patch in {"no key": {"preview_digest": "short"}, "bad state": {"business_state_digest": "zz"},
                        "payload type": {"payload": [1]}}.items():
        await fails("SCHEMA_INVALID", store(led, k, canonical_json({**obj, **patch})))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.approval_envelopes") == 0
    await assert_equal_and_approvable(led, k, good)


async def test_a_payload_that_does_not_recompute_to_its_digest_is_refused_at_store(led):
    k = await make_case(led, "CREATE_DRAFT")
    obj = json.loads(text_of(k))
    obj["payload"]["comment"] = "substituted before approval"          # payload_digest still names the original
    await fails("DIGEST_MISMATCH", store(led, k, canonical_json(obj)))
    # a null payload on a draft is now refused earlier, by the operation-specific payload rule (was DIGEST_MISMATCH)
    await fails("SCHEMA_INVALID", store(led, k, canonical_json({**json.loads(text_of(k)), "payload": None})))
    await assert_equal_and_approvable(led, k, text_of(k))


@pytest.mark.parametrize("kind", ["CREATE_DRAFT", "UPDATE_DRAFT"])
async def test_a_draft_envelope_must_carry_a_payload_object(led, kind):
    k = await make_case(led, kind)
    obj = json.loads(text_of(k))
    for bad in (None, [], "x", 1):
        await fails("SCHEMA_INVALID", store(led, k, canonical_json({**obj, "payload": bad})))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.approval_envelopes") == 0
    await assert_equal_and_approvable(led, k, text_of(k))


@pytest.mark.parametrize("kind", ["POST", "UNPOST", "REPAIR"])
async def test_a_post_or_unpost_envelope_must_carry_json_null_not_an_object(led, kind):
    k = await make_case(led, kind)
    obj = json.loads(text_of(k))
    assert obj["payload"] is None
    # {} would recompute to the same payload_digest, so only the payload rule refuses it
    for bad in ({}, {"comment": "smuggled"}, [], "x"):
        await fails("SCHEMA_INVALID", store(led, k, canonical_json({**obj, "payload": bad})))
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.approval_envelopes") == 0
    await assert_equal_and_approvable(led, k, text_of(k))


async def test_stale_preview_after_the_text_is_stored_is_refused_at_approve_and_a_new_nonce_is_required(led):
    k = await make_case(led, "CREATE_DRAFT")
    dg = await store(led, k, text_of(k))
    # the declared budget changes after the preview was shown: the stored text is stale
    assert await led.call("clt_alice", "declare_budget", k.cid, GRANT, "EUR", Decimal("20"), True, False) == "PROPOSED"
    assert await led.call("clt_alice", "validate", k.cid) == "VALIDATED"
    await fails("DIGEST_MISMATCH", led.call("clt_bob", "approve", k.cid, k.nonce, dg))
    assert (await led.rec(k.cid))["authorization_state"] == "NONE"
    k.budget = {**k.budget, "amount": "20"}
    k.nonce = await led.call("clt_bob", "issue_approval_nonce", k.cid)
    dg2 = await store(led, k, text_of(k))
    assert dg2 != dg
    await fails("DIGEST_MISMATCH", led.call("clt_bob", "approve", k.cid, k.nonce, dg))        # the old digest
    await led.call("clt_bob", "approve", k.cid, k.nonce, dg2)
    # the target changes after the preview as well: approval refused until a new proposal
    k2 = await make_case(led, "POST")
    dg3 = await store(led, k2, text_of(k2))
    await led.conn.execute("UPDATE change_ledger.records SET target_version='v8' WHERE change_id=$1", k2.cid)
    await fails("DIGEST_MISMATCH", led.call("clt_bob", "approve", k2.cid, k2.nonce, dg3))


# ============================================================================ immutability, access, replay
async def test_the_stored_text_is_immutable_and_unreadable_for_runtime_roles(led):
    k = await make_case(led, "CREATE_DRAFT")
    text = text_of(k)
    dg = await store(led, k, text)
    assert await store(led, k, text) == dg                                  # the same text is a replay
    other = json.loads(text)
    other["preview_digest"] = "d" * 64
    await fails("FORBIDDEN_TRANSITION", store(led, k, canonical_json(other)))       # never replaced
    for sql in ("UPDATE change_ledger.approval_envelopes SET canonical_text='x'",
                "DELETE FROM change_ledger.approval_envelopes", "TRUNCATE change_ledger.approval_envelopes"):
        await fails("IMMUTABLE_LEDGER", led.conn.execute(sql))
    for role in ("clt_alice", "clt_bob", "clt_aud", "clt_wri", "clt_dave"):
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await led.sql(role, "SELECT canonical_text FROM change_ledger.approval_envelopes")
    assert await led.call("clt_alice", "read_approval_text", k.cid) == text
    with pytest.raises(asyncpg.InsufficientPrivilegeError):                                 # not for auditors at all
        await led.call("clt_aud", "read_approval_text", k.cid)
    await fails("CHANGE_NOT_FOUND", led.call("clt_mallory", "read_approval_text", k.cid))
    await fails("NOT_ENTITLED", led.call("clt_mallory", "store_approval_text", k.cid, k.nonce, text))
    with pytest.raises(asyncpg.InsufficientPrivilegeError):                                 # approvers cannot store
        await led.call("clt_bob", "store_approval_text", k.cid, k.nonce, text)
    # events carry digests only
    ev = await led.conn.fetchval("SELECT payload::text FROM change_ledger.events WHERE change_id=$1 AND "
                                 "event_type='APPROVAL_TEXT_STORED'", k.cid)
    assert dg in ev and "Привет" not in ev and "fixture" not in ev and "supplier" not in ev
    # a nonce that was not issued for this change, or no longer ISSUED, cannot receive a text
    other_change = await make_case(led, "CREATE_DRAFT")
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_alice", "store_approval_text", other_change.cid, k.nonce, text))
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_alice", "store_approval_text", k.cid, "bogus", text))


async def test_a_replayed_approval_cannot_authorize_a_second_time_or_another_change(led):
    a = await make_case(led, "CREATE_DRAFT")
    b = await make_case(led, "CREATE_DRAFT")
    da = await store(led, a, text_of(a))
    db_ = await store(led, b, text_of(b))
    # another change's digest, and a's (nonce, digest) on b, do not authorize b
    await fails("DIGEST_MISMATCH", led.call("clt_bob", "approve", b.cid, b.nonce, da))
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_bob", "approve", b.cid, a.nonce, da))
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_bob", "approve", a.cid, b.nonce, db_))
    aid = await led.call("clt_bob", "approve", a.cid, a.nonce, da)
    assert await led.call("clt_bob", "approve", a.cid, a.nonce, da) == aid          # an idempotent replay, no new row
    assert await led.conn.fetchval("SELECT count(*) FROM change_ledger.approvals WHERE change_id=$1", a.cid) == 1
    await fails("FORBIDDEN_TRANSITION", led.call("clt_carol", "approve", a.cid, a.nonce, da))
    # after the approval is revoked, the consumed (nonce, digest) pair authorizes nothing
    assert await led.call("clt_dave", "revoke_change", a.cid, "SESSION_REVOKED") == "REVOKED"
    await fails("APPROVAL_NONCE_INVALID", led.call("clt_bob", "approve", a.cid, a.nonce, da))
    await fails("APPROVAL_VOIDED", led.claimed(a.cid))
    # a fresh nonce needs a fresh text and a fresh digest (the nonce is inside the digest)
    a.nonce = await led.call("clt_bob", "issue_approval_nonce", a.cid)
    await fails("DIGEST_MISMATCH", led.call("clt_bob", "approve", a.cid, a.nonce, da))
    da2 = await store(led, a, text_of(a))
    assert da2 != da
    await led.call("clt_bob", "approve", a.cid, a.nonce, da2)


async def test_payload_substituted_after_approval_is_refused_before_dispatch_and_tampered_state_blocks_the_claim(led):
    k = await make_case(led, "CREATE_DRAFT")
    await assert_equal_and_approvable(led, k, text_of(k))
    # the ledger-held binding fields are re-checked against the approved envelope at claim
    await led.conn.execute("UPDATE change_ledger.records SET target_version='v9' WHERE change_id=$1", k.cid)
    await fails("DIGEST_MISMATCH", led.claimed(k.cid))
    await led.conn.execute("UPDATE change_ledger.records SET target_version=NULL WHERE change_id=$1", k.cid)
    await led.conn.execute("UPDATE change_ledger.records SET payload_digest=$2 WHERE change_id=$1", k.cid, "f" * 64)
    await fails("DIGEST_MISMATCH", led.claimed(k.cid))
    await led.conn.execute("UPDATE change_ledger.records SET payload_digest=$2 WHERE change_id=$1", k.cid,
                           k.prop.payload_digest)
    tok = await led.claimed(k.cid)
    await led.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "host-1", "sess-1")
    gen = tok["generation"]
    payload = ch.payload_to_dict(k.prop.payload)
    assert await led.call("clt_wri", "verify_dispatch_payload", k.cid, gen, canonical_json(payload)) is True
    assert await led.call("clt_wri", "verify_dispatch_payload", k.cid, gen,
                          json.dumps(dict(reversed(list(payload.items()))), indent=2)) is True     # same payload
    for name, substituted in {
        "comment": {**payload, "comment": "substituted"},
        "line amount": {**payload, "lines": [{**payload["lines"][0], "amount": "2100"}]},
        "counterparty": {**payload, "counterparty_ref": "cp-evil"},
        "dropped key": {x: v for x, v in payload.items() if x != "comment"},
        "empty": {},
    }.items():
        await fails("DIGEST_MISMATCH", led.call("clt_wri", "verify_dispatch_payload", k.cid, gen,
                                                canonical_json(substituted)))
    await fails("DIGEST_MISMATCH", led.call("clt_wri", "verify_dispatch_payload", k.cid, gen, None))
    await fails("SCHEMA_INVALID", led.call("clt_wri", "verify_dispatch_payload", k.cid, gen, "not json"))
    await fails("SCHEMA_INVALID", led.call("clt_wri", "verify_dispatch_payload", k.cid, gen, "[1]"))
    await fails("TICKET_SUPERSEDED", led.call("clt_wri", "verify_dispatch_payload", k.cid, gen + 1, "{}"))
    with pytest.raises(asyncpg.InsufficientPrivilegeError):                  # the worker is not a dispatcher
        await led.call("clt_wrk", "verify_dispatch_payload", k.cid, gen, "{}")
    # the permit path recomputes the payload digest from the stored envelope as well
    await led.checkpoint()
    await led.conn.execute("UPDATE change_ledger.records SET target_ref='doc-swapped' WHERE change_id=$1", k.cid)
    await fails("DIGEST_MISMATCH", led.call("clt_wrk", "issue_permit", k.cid, gen))


async def test_a_payloadless_kind_verifies_the_empty_payload_only(led):
    k = await make_case(led, "POST")
    await assert_equal_and_approvable(led, k, text_of(k))
    await led.conn.execute("UPDATE change_ledger.records SET authorization_state='CLAIMED', execution_state='APPLYING', "
                           "claim_generation=1 WHERE change_id=$1", k.cid)          # arranged: POST claims need a verified parent
    for ok in (None, "{}", "null"):
        assert await led.call("clt_wri", "verify_dispatch_payload", k.cid, 1, ok) is True
    await fails("DIGEST_MISMATCH", led.call("clt_wri", "verify_dispatch_payload", k.cid, 1, '{"a":"b"}'))


# ============================================================================ version gate for S12-APPROVAL-SQL-1
async def apply_files(conn, names):
    for name in names:
        raw = (MIGRATIONS / name).read_bytes()
        await conn.execute("SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest())
        await conn.execute(raw.decode("utf-8"))


async def test_approvals_of_the_old_version_cannot_authorize_anything_after_009(led):
    # the version label is closed
    with pytest.raises(asyncpg.CheckViolationError):
        await led.conn.execute("INSERT INTO change_ledger.approvals(change_id,approver,nonce,digest,decision,"
                               "digest_version) VALUES($1,'x','n',repeat('a',64),'APPROVE','S12-APPROVAL-1')",
                               uuid.uuid4())
    dsn = require_dsn()
    async with throwaway_db(dsn, migrate=False, seed=False) as db:
        db.conn = await db.connect()
        assert FILES[8] == "009_approval_digest_2.sql" and len(FILES) == 13   # 010 to 013 follow 009
        await apply_files(db.conn, FILES[:8])                       # the world before 009: SQL-1 digests
        await _setup(db.conn)
        old = L(db)

        async def legacy_approved(rid, base):
            cid = await old.validated(request_id=rid, base=base)
            nonce = await old.call("clt_bob", "issue_approval_nonce", cid)
            dg = (await old.status(cid))["approval_digest"]
            await old.call("clt_bob", "approve", cid, nonce, dg)
            return cid, dg

        unclaimed, dg_u = await legacy_approved("legacy-u", "base-1")
        claimed, _ = await legacy_approved("legacy-c", "base-2")
        tok = await old.claimed(claimed)
        pending = await old.validated(request_id="legacy-p", base="base-3")
        n_p = await old.call("clt_bob", "issue_approval_nonce", pending)
        dg_p = (await old.status(pending))["approval_digest"]       # a SQL-1 digest of a still unapproved change
        assert len(dg_p) == 64
        await apply_files(db.conn, FILES[8:])                        # migration 009

        v = await db.conn.fetch("SELECT change_id, digest, digest_version FROM change_ledger.approvals")
        assert {r["digest_version"] for r in v} == {"S12-APPROVAL-SQL-1"} and len(v) == 2
        assert (await old.rec(unclaimed))["authorization_state"] == "VOIDED"           # retired by the migration
        assert await db.conn.fetchval("SELECT count(*) FROM change_ledger.events WHERE event_type="
                                      "'APPROVAL_VERSION_RETIRED'") == 1
        st = await old.status(unclaimed)
        assert st["approved_digest"] == dg_u and st["approved_digest_version"] == "S12-APPROVAL-SQL-1"
        assert st["approval_digest"] is None                                       # no version-2 text exists
        await fails("APPROVAL_VOIDED", old.claimed(unclaimed))
        # a claim that was made under the old approval cannot start: begin_apply refuses it
        await fails("APPROVAL_VOIDED", old.call("clt_alice", "begin_apply", tok["token_id"], uuid.uuid4(), "h", "s"))
        assert (await old.rec(claimed))["execution_state"] == "NOT_STARTED"
        # the old digest of a pending change authorizes nothing; its version-2 digest does
        await ensure_envelope(old, pending)
        await fails("DIGEST_MISMATCH", old.call("clt_bob", "approve", pending, n_p, dg_p))
        await fails("DIGEST_MISMATCH", old.call("clt_bob", "approve", pending, n_p, dg_u))
        dg2 = (await old.status(pending))["approval_digest"]
        assert dg2 not in (dg_p, dg_u)
        await old.call("clt_bob", "approve", pending, n_p, dg2)
        assert await db.conn.fetchval("SELECT digest_version FROM change_ledger.approvals WHERE change_id=$1",
                                      pending) == "S12-APPROVAL-2"
        assert (await old.call("clt_aud", "verify_chain"))["ok"] is True
