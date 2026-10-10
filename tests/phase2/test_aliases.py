"""R2-US-014 supplier alias resolver: TC040 exact scoped ref, TC041 same name two companies,
TC042 ambiguity queue; plus the human-resolution guards. Pure, deterministic, injected clock."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from business_ai_gateway.phase2._identity import stable_key
from business_ai_gateway.phase2.aliases import (
    ActorKind,
    AliasOutcome,
    AliasRecord,
    AliasResolver,
    AliasScope,
    Approver,
    Reference,
    ResolveQuery,
    SupplierEntity,
    normalize_name,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
A = AliasScope("t1", "companyA")
B = AliasScope("t1", "companyB")
OTHER_TENANT = AliasScope("t2", "companyA")
TAX = "tax_id"
HUMAN = Approver("alice@example.com", ActorKind.HUMAN)


def _res() -> AliasResolver:
    return AliasResolver(clock=lambda: NOW)


def _ent(eid: str, scope: AliasScope, name: str = "Acme Ltd", code: str = "AB-123") -> SupplierEntity:
    return SupplierEntity(eid, scope, name, (Reference(TAX, code),))


def _ambiguous(r: AliasResolver):
    assert r.add_entity(_ent("e1", A, "Acme", "X1")).ok
    r.add_entity(_ent("e2", A, "Acme Corp", "X2"))
    r.add_alias(AliasRecord("e1", A, "import", reference=Reference("erp_code", "S-9")))
    r.add_alias(AliasRecord("e2", A, "import", reference=Reference("erp_code", "S-9")))
    return r.resolve(A, ResolveQuery(reference=Reference("erp_code", "S-9")))


# ---- TC040 ------------------------------------------------------------------------------------
def test_tc040_exact_scoped_reference_resolves():
    r = _res()
    r.add_entity(_ent("e1", A))
    res = r.resolve(A, ResolveQuery(reference=Reference(TAX, "AB-123")))
    assert res.outcome is AliasOutcome.RESOLVED and res.entity_id == "e1" and res.ok


def test_tc040_reference_trimmed_only():
    r = _res()
    r.add_entity(_ent("e1", A))
    res = r.resolve(A, ResolveQuery(reference=Reference(" " + TAX, "  AB-123 ")))
    assert res.entity_id == "e1"


@pytest.mark.parametrize("value", ["AB-124", "ab-123", "AB-12", "AB-1234", "AB 123"])
def test_tc040_near_miss_reference_does_not_resolve(value):
    r = _res()
    r.add_entity(_ent("e1", A))
    res = r.resolve(A, ResolveQuery(reference=Reference(TAX, value)))
    assert res.outcome is AliasOutcome.NOT_FOUND and res.entity_id is None


def test_tc040_reference_namespace_is_part_of_identity():
    r = _res()
    r.add_entity(_ent("e1", A))
    res = r.resolve(A, ResolveQuery(reference=Reference("erp_code", "AB-123")))
    assert res.outcome is AliasOutcome.NOT_FOUND


def test_alias_reference_resolves_within_scope():
    r = _res()
    r.add_entity(_ent("e1", A))
    assert r.add_alias(AliasRecord("e1", A, "1c", reference=Reference("erp_code", "S-1"))).ok
    res = r.resolve(A, ResolveQuery(reference=Reference("erp_code", "S-1")))
    assert res.outcome is AliasOutcome.RESOLVED and res.entity_id == "e1"


def test_name_alone_never_resolves_but_may_suggest():
    r = _res()
    r.add_entity(_ent("e1", A, "Acme Ltd"))
    res = r.resolve(A, ResolveQuery(name="  ＡＣＭＥ LTD "))
    assert res.outcome is AliasOutcome.NOT_FOUND
    assert res.entity_id is None and res.suggestions == ("e1",)
    assert r.queue_items(A) == ()


def test_wrong_reference_with_matching_name_does_not_resolve():
    r = _res()
    r.add_entity(_ent("e1", A, "Acme Ltd"))
    res = r.resolve(A, ResolveQuery(reference=Reference(TAX, "ZZ"), name="Acme Ltd"))
    assert res.outcome is AliasOutcome.NOT_FOUND and res.suggestions == ("e1",)


# ---- TC041 ------------------------------------------------------------------------------------
def test_tc041_same_name_two_companies_stay_two_entities():
    r = _res()
    r.add_entity(_ent("a1", A, "Acme Ltd", "AB-123"))
    r.add_entity(_ent("b1", B, "Acme Ltd", "AB-123"))
    ra = r.resolve(A, ResolveQuery(reference=Reference(TAX, "AB-123")))
    rb = r.resolve(B, ResolveQuery(reference=Reference(TAX, "AB-123")))
    assert (ra.entity_id, rb.entity_id) == ("a1", "b1")
    assert r.queue_items(A) == () and r.queue_items(B) == ()


def test_tc041_cross_company_resolve_is_not_found():
    r = _res()
    r.add_entity(_ent("a1", A))
    assert r.resolve(B, ResolveQuery(reference=Reference(TAX, "AB-123"))).outcome is AliasOutcome.NOT_FOUND
    assert r.resolve(OTHER_TENANT, ResolveQuery(reference=Reference(TAX, "AB-123"))).outcome \
        is AliasOutcome.NOT_FOUND


def test_tc041_cross_company_name_never_suggested_or_ambiguous():
    r = _res()
    r.add_entity(_ent("a1", A, "Acme Ltd", "1"))
    r.add_entity(_ent("b1", B, "Acme Ltd", "2"))
    res = r.resolve(A, ResolveQuery(name="acme ltd"))
    assert res.outcome is AliasOutcome.NOT_FOUND and res.suggestions == ("a1",)
    assert r.queue_items(A) == () and r.queue_items(B) == ()


def test_alias_in_other_scope_is_rejected_and_does_not_leak():
    r = _res()
    r.add_entity(_ent("a1", A))
    out = r.add_alias(AliasRecord("a1", B, "x", reference=Reference("erp_code", "S-1")))
    # entity ids are scope-keyed: another scope's entity is simply unknown (no oracle)
    assert out.outcome is AliasOutcome.REJECTED_INPUT and out.code == "ENTITY_UNKNOWN"
    assert r.resolve(B, ResolveQuery(reference=Reference("erp_code", "S-1"))).outcome \
        is AliasOutcome.NOT_FOUND


@pytest.mark.parametrize("scope", [AliasScope("", "c"), AliasScope("t", "  "), None])
def test_invalid_scope_is_scope_violation(scope):
    r = _res()
    r.add_entity(_ent("a1", A))
    assert r.resolve(scope, ResolveQuery(reference=Reference(TAX, "AB-123"))).outcome \
        is AliasOutcome.SCOPE_VIOLATION
    assert r.add_entity(_ent("z", scope)).outcome is AliasOutcome.SCOPE_VIOLATION


def test_duplicate_entity_id_rejected_only_within_scope():
    r = _res()
    assert r.add_entity(_ent("a1", A)).ok
    assert r.add_entity(_ent("a1", A)).outcome is AliasOutcome.REJECTED_DUPLICATE
    # M10: the same id in another company/tenant is NOT refused, so no cross-scope oracle
    assert r.add_entity(_ent("a1", B, code="Z")).ok
    assert r.add_entity(_ent("a1", OTHER_TENANT, code="Y")).ok
    assert r.resolve(B, ResolveQuery(reference=Reference(TAX, "Z"))).entity_id == "a1"
    assert r.resolve(A, ResolveQuery(reference=Reference(TAX, "Z"))).outcome is AliasOutcome.NOT_FOUND


def test_no_raw_input_echoed_in_codes():
    r = _res()
    secret = "SECRET-<script>-123"
    r.add_entity(_ent("a1", A))
    outs = [
        (r.resolve(A, ResolveQuery(reference=Reference(TAX, secret))), "NO_EXACT_REFERENCE"),
        (r.resolve(A, ResolveQuery(reference=Reference(secret, " "))), "REFERENCE_INVALID"),
        (r.resolve(AliasScope(secret, ""), ResolveQuery()), "SCOPE_INVALID"),
        (r.add_entity(SupplierEntity("a1", A, secret)), "ENTITY_EXISTS"),
        (r.add_alias(AliasRecord(secret, A, "p", alias_text=secret)), "ENTITY_UNKNOWN"),
    ]
    for o, code in outs:
        assert o.code == code and secret not in o.code
    d = r.resolve_ambiguity(A, secret, secret, Approver(secret, ActorKind.AUTOMATION), secret)
    assert d.code == "ITEM_UNKNOWN"
    res = _ambiguous(r)
    d2 = r.resolve_ambiguity(A, res.queue_item_id, "e1", Approver(secret, ActorKind.AUTOMATION),
                             secret)
    assert d2.code == "APPROVER_NOT_HUMAN"
    d3 = r.resolve_ambiguity(A, res.queue_item_id, secret, HUMAN, "why")
    assert d3.code == "CHOICE_NOT_CANDIDATE"


def test_empty_resolve_query_is_not_found_without_queue():
    r = _res()
    r.add_entity(_ent("e1", A))
    res = r.resolve(A, ResolveQuery())
    assert res.outcome is AliasOutcome.NOT_FOUND and res.code == "NO_EXACT_REFERENCE"
    assert res.suggestions == () and r.queue_items(A) == ()


def test_two_entities_with_colliding_primary_reference_are_ambiguous():
    r = _res()
    r.add_entity(_ent("e1", A, "One", "SAME"))
    r.add_entity(_ent("e2", A, "Two", "SAME"))
    res = r.resolve(A, ResolveQuery(reference=Reference(TAX, "SAME")))
    assert res.outcome is AliasOutcome.AMBIGUOUS and res.entity_id is None
    assert res.candidate_ids == ("e1", "e2") and len(r.queue_items(A)) == 1


# ---- M7 invisible / homoglyph identities --------------------------------------------------------
@pytest.mark.parametrize("junk", ["\u200b", "\u2800", "\u3164", "\u115f", "\u1160", "\uffa0",
                                  "\xa0", "\u3000", "\t", "\n", "\u2028", "\u2029", "\ufeff"])
def test_invisible_strings_are_blank(junk):
    assert normalize_name(junk) == "" and normalize_name(" " + junk + " ") == ""
    assert normalize_name("al" + junk + "ice") == ""
    assert not AliasScope("t1", junk).valid() and not AliasScope(junk, "c").valid()
    assert not Reference(TAX, junk).valid() and not Reference(junk, "v").valid()
    r = _res()
    assert r.add_entity(_ent("e", AliasScope("t1", junk))).outcome is AliasOutcome.SCOPE_VIOLATION
    assert r.add_entity(SupplierEntity("e", A, junk)).code == "ENTITY_INVALID"


def test_zero_width_approver_is_refused_not_confused_with_plain():
    r = _res()
    res = _ambiguous(r)
    for ident in ("al\u200bice", "\u200b", "\u2800", "ali\u3164ce"):
        out = r.resolve_ambiguity(A, res.queue_item_id, "e1", Approver(ident, ActorKind.HUMAN), "x")
        assert out.outcome is AliasOutcome.REJECTED_APPROVER
    assert r.queue_items(A)[0].decision is None


def test_scope_normalisation_matches_taxonomy_nfkc_casefold():
    r = _res()
    r.add_entity(_ent("a1", A))
    same = AliasScope("  T1 ", "ＣＯＭＰＡＮＹa")
    assert r.resolve(same, ResolveQuery(reference=Reference(TAX, "AB-123"))).entity_id == "a1"


# ---- m6/m7 type robustness ----------------------------------------------------------------------
def test_wrong_types_give_fixed_codes_never_exceptions():
    r = _res()
    r.add_entity(_ent("e1", A))
    assert r.add_entity(None).code == "ENTITY_INVALID"
    assert r.add_alias(None).code == "ALIAS_INVALID"
    assert r.add_entity(SupplierEntity(["x"], A, "N")).code == "ENTITY_INVALID"
    assert r.add_entity(SupplierEntity("e9", A, "N", "notrefs")).code == "ENTITY_INVALID"
    assert r.add_entity(SupplierEntity("e9", A, "N", [Reference(TAX, "L1")])).ok  # list coerced
    assert r.resolve(A, ResolveQuery(reference=Reference(TAX, "L1"))).entity_id == "e9"
    assert r.resolve(A, None).code == "QUERY_INVALID"
    assert r.resolve(A, ResolveQuery(reference="x")).code == "REFERENCE_INVALID"
    assert r.add_alias(AliasRecord(["x"], A, "p", alias_text="n")).code == "ENTITY_UNKNOWN"
    assert r.queue_items(None) == ()
    assert r.resolve_ambiguity(None, "i", "e1", HUMAN, "x").outcome is AliasOutcome.SCOPE_VIOLATION
    assert r.resolve_ambiguity(A, ["i"], "e1", HUMAN, "x").code == "ITEM_UNKNOWN"


# ---- TC042 ------------------------------------------------------------------------------------
def test_tc042_two_candidates_ambiguous_one_queue_item_nothing_merged():
    r = _res()
    res = _ambiguous(r)
    assert res.outcome is AliasOutcome.AMBIGUOUS and not res.ok
    assert res.entity_id is None and res.candidate_ids == ("e1", "e2")
    items = r.queue_items(A)
    assert len(items) == 1 and items[0].item_id == res.queue_item_id
    assert items[0].candidate_ids == ("e1", "e2") and items[0].decision is None
    # nothing merged: both entities and their own references remain
    assert r.resolve(A, ResolveQuery(reference=Reference(TAX, "X1"))).entity_id == "e1"
    assert r.resolve(A, ResolveQuery(reference=Reference(TAX, "X2"))).entity_id == "e2"


def test_tc042_repeat_resolve_does_not_duplicate_queue_item():
    r = _res()
    first = _ambiguous(r)
    second = r.resolve(A, ResolveQuery(reference=Reference("erp_code", "S-9")))
    assert second.queue_item_id == first.queue_item_id
    assert len(r.queue_items(A)) == 1


def test_tc042_same_name_in_scope_is_ambiguous_not_resolved():
    r = _res()
    r.add_entity(_ent("e1", A, "Acme", "1"))
    r.add_entity(_ent("e2", A, "ACME", "2"))
    res = r.resolve(A, ResolveQuery(name="acme"))
    assert res.outcome is AliasOutcome.AMBIGUOUS and res.candidate_ids == ("e1", "e2")
    assert len(r.queue_items(A)) == 1


def test_queue_items_are_scope_separated():
    r = _res()
    for scope, p in ((A, "a"), (B, "b")):
        r.add_entity(_ent(p + "1", scope, "Acme", p + "1"))
        r.add_entity(_ent(p + "2", scope, "Acme", p + "2"))
    ra = r.resolve(A, ResolveQuery(name="acme"))
    rb = r.resolve(B, ResolveQuery(name="acme"))
    assert ra.queue_item_id != rb.queue_item_id
    assert ra.candidate_ids == ("a1", "a2") and rb.candidate_ids == ("b1", "b2")
    assert [i.item_id for i in r.queue_items(A)] == [ra.queue_item_id]
    assert [i.item_id for i in r.queue_items(B)] == [rb.queue_item_id]
    assert r.queue_items(OTHER_TENANT) == ()


def test_approver_cannot_decide_another_scopes_item():
    r = _res()
    res = _ambiguous(r)  # item lives in scope A
    for foreign in (B, OTHER_TENANT):
        out = r.resolve_ambiguity(foreign, res.queue_item_id, "e1", HUMAN, "x")
        assert out.outcome is AliasOutcome.UNKNOWN_ITEM and out.code == "ITEM_UNKNOWN"
    assert r.queue_items(A)[0].decision is None
    assert r.resolve_ambiguity(A, res.queue_item_id, "e1", HUMAN, "x").ok


def test_item_id_encoding_is_unambiguous_and_control_chars_are_refused():
    assert stable_key("a\x1fb", "c") != stable_key("a", "b\x1fc")
    assert stable_key("ab", "c") != stable_key("a", "bc")
    r = _res()
    # an id that would only collide through a separator character cannot even be registered
    assert r.add_entity(_ent("x\x1fy", A)).code == "ENTITY_INVALID"
    assert r.add_entity(_ent("x", AliasScope("t\x1f1", "c"))).outcome is AliasOutcome.SCOPE_VIOLATION


# ---- human resolution -------------------------------------------------------------------------
def test_human_resolution_happy_path_records_who_when_and_merges_nothing():
    r = _res()
    res = _ambiguous(r)
    out = r.resolve_ambiguity(A, res.queue_item_id, "e2", HUMAN, "  same legal entity per contract ")
    assert out.outcome is AliasOutcome.DECIDED and out.ok and not out.replay
    d = out.decision
    assert (d.chosen_entity_id, d.approver, d.reason, d.decided_at) == (
        "e2", "alice@example.com", "same legal entity per contract", NOW)
    assert r.queue_items(A)[0].decision == d
    # no merge / no alias rewrite: ambiguity persists, other scope untouched
    again = r.resolve(A, ResolveQuery(reference=Reference("erp_code", "S-9")))
    assert again.outcome is AliasOutcome.AMBIGUOUS
    assert r.resolve(B, ResolveQuery(reference=Reference("erp_code", "S-9"))).outcome \
        is AliasOutcome.NOT_FOUND


def test_automation_actor_refused():
    r = _res()
    res = _ambiguous(r)
    out = r.resolve_ambiguity(A, res.queue_item_id, "e1", Approver("bot", ActorKind.AUTOMATION), "x")
    assert out.outcome is AliasOutcome.REJECTED_APPROVER
    assert r.queue_items(A)[0].decision is None


@pytest.mark.parametrize("identity", ["", "   ", "\xa0"])
def test_blank_approver_refused(identity):
    r = _res()
    res = _ambiguous(r)
    out = r.resolve_ambiguity(A, res.queue_item_id, "e1", Approver(identity, ActorKind.HUMAN), "x")
    assert out.outcome is AliasOutcome.REJECTED_APPROVER
    assert r.queue_items(A)[0].decision is None


def test_non_approver_object_refused():
    r = _res()
    res = _ambiguous(r)
    assert r.resolve_ambiguity(A, res.queue_item_id, "e1", "alice", "x").outcome \
        is AliasOutcome.REJECTED_APPROVER


def test_blank_reason_refused():
    r = _res()
    res = _ambiguous(r)
    for reason in ("  ", "\u200b", None):
        assert r.resolve_ambiguity(A, res.queue_item_id, "e1", HUMAN, reason).outcome \
            is AliasOutcome.REJECTED_INPUT
    assert r.queue_items(A)[0].decision is None


def test_choice_must_be_a_candidate():
    r = _res()
    res = _ambiguous(r)
    r.add_entity(_ent("e3", B, "Other", "Q"))
    assert r.resolve_ambiguity(A, res.queue_item_id, "e3", HUMAN, "x").outcome \
        is AliasOutcome.REJECTED_CHOICE
    assert r.queue_items(A)[0].decision is None


def test_unknown_queue_item_refused():
    assert _res().resolve_ambiguity(A, "RQ-nope", "e1", HUMAN, "x").outcome is AliasOutcome.UNKNOWN_ITEM


def test_clock_is_called_once_per_recorded_decision_only():
    calls = []

    def clock():
        calls.append(1)
        return NOW

    r = AliasResolver(clock=clock)
    res = _ambiguous(r)
    r.resolve_ambiguity(A, res.queue_item_id, "e1", HUMAN, "first")
    r.resolve_ambiguity(A, res.queue_item_id, "e1", HUMAN, "again")
    r.resolve_ambiguity(A, res.queue_item_id, "e2", HUMAN, "conflict")
    assert len(calls) == 1


def test_same_decision_is_idempotent_keeps_first_record_and_hides_first_approver():
    r = _res()  # the clock is a callable that never runs out
    res = _ambiguous(r)
    first = r.resolve_ambiguity(A, res.queue_item_id, "e1", HUMAN, "first")
    second = r.resolve_ambiguity(A, res.queue_item_id, "e1", Approver("bob", ActorKind.HUMAN), "later")
    assert second.outcome is AliasOutcome.DECIDED and second.replay is True
    assert second.decision.chosen_entity_id == "e1" and second.decision.decided_at == NOW
    # the replay must not reveal who decided first; the stored record is untouched
    assert second.decision.approver == "" and second.decision.reason == ""
    assert "alice" not in repr(second)
    assert r.queue_items(A)[0].decision == first.decision
    assert first.decision.approver == "alice@example.com"


def test_conflicting_second_decision_refused_and_first_kept():
    r = _res()
    res = _ambiguous(r)
    first = r.resolve_ambiguity(A, res.queue_item_id, "e1", HUMAN, "first")
    second = r.resolve_ambiguity(A, res.queue_item_id, "e2", HUMAN, "changed mind")
    assert second.outcome is AliasOutcome.REJECTED_CONFLICT and second.decision is None
    assert r.queue_items(A)[0].decision == first.decision


# ---- hardening: exact types, 1C empty reference, hostile objects -------------------------------
class _LyingStr(str):
    def __iter__(self):
        return iter("e1")

    def __len__(self):
        return 2

    def strip(self, chars=None):
        return "e1"

    def __eq__(self, other):
        return True

    __hash__ = str.__hash__


EMPTY_REF = "00000000-0000-0000-0000-000000000000"


def test_reference_with_str_subclass_parts_is_invalid():
    assert not Reference(_LyingStr("tax\u200bid"), "v").valid()
    assert not Reference(TAX, _LyingStr("v\u200b1")).valid()


def test_add_entity_and_alias_refuse_str_subclass_ids():
    r = _res()
    assert r.add_entity(_ent(_LyingStr("e\u200b1"), A)).outcome is AliasOutcome.REJECTED_INPUT
    assert r.add_entity(_ent("e1", A)).ok
    res = r.add_alias(AliasRecord(_LyingStr("e1"), A, "import", alias_text="x"))
    assert res.outcome is AliasOutcome.REJECTED_INPUT


def test_resolve_ambiguity_refuses_lying_eq_choice_and_item_id():
    r = _res()
    res = _ambiguous(r)
    bad = r.resolve_ambiguity(A, res.queue_item_id, _LyingStr("zzz"), HUMAN, "why")
    assert bad.outcome is AliasOutcome.REJECTED_CHOICE
    bad_item = r.resolve_ambiguity(A, _LyingStr(res.queue_item_id), "e1", HUMAN, "why")
    assert bad_item.outcome is AliasOutcome.UNKNOWN_ITEM
    assert r.queue_items(A)[0].decision is None


@pytest.mark.parametrize("empty", [EMPTY_REF, "{" + EMPTY_REF + "}", EMPTY_REF.replace("-", "")])
def test_1c_empty_reference_is_never_a_valid_reference(empty):
    assert not Reference("1c_ref", empty).valid()
    r = _res()
    ent = SupplierEntity("e1", A, "Acme", (Reference("1c_ref", empty),))
    assert r.add_entity(ent).outcome is AliasOutcome.REJECTED_INPUT
    assert r.add_entity(_ent("e2", A)).ok
    res = r.add_alias(AliasRecord("e2", A, "import", reference=Reference("1c_ref", empty)))
    assert res.outcome is AliasOutcome.REJECTED_INPUT
    found = r.resolve(A, ResolveQuery(reference=Reference("1c_ref", empty)))
    assert found.outcome is AliasOutcome.REJECTED_INPUT and found.entity_id is None


def test_hostile_scope_objects_never_raise():
    r = _res()
    r.add_entity(_ent("e1", A))
    blank = object.__new__(AliasScope)
    res = r.resolve(blank, ResolveQuery(reference=Reference(TAX, "AB-123")))
    assert res.outcome is AliasOutcome.SCOPE_VIOLATION and res.entity_id is None
    assert r.queue_items(blank) == ()
    assert r.resolve_ambiguity(blank, "x", "e1", HUMAN, "why").outcome is AliasOutcome.SCOPE_VIOLATION
    assert r.add_entity(SupplierEntity("e9", blank, "N")).outcome is AliasOutcome.SCOPE_VIOLATION
    assert r.add_alias(AliasRecord("e1", blank, "p", alias_text="x")).outcome is AliasOutcome.SCOPE_VIOLATION
    half = object.__new__(AliasScope)
    object.__setattr__(half, "tenant_id", "t1")
    assert r.resolve(half, ResolveQuery()).outcome is AliasOutcome.SCOPE_VIOLATION
