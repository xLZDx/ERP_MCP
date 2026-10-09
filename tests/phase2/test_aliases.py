"""R2-US-014 supplier alias resolver: TC040 exact scoped ref, TC041 same name two companies,
TC042 ambiguity queue; plus the human-resolution guards. Pure, deterministic, injected clock."""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

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
    assert r.queue_items() == ()


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
    assert r.queue_items() == ()


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
    assert r.queue_items() == ()


def test_alias_in_other_scope_is_rejected_and_does_not_leak():
    r = _res()
    r.add_entity(_ent("a1", A))
    out = r.add_alias(AliasRecord("a1", B, "x", reference=Reference("erp_code", "S-1")))
    assert out.outcome is AliasOutcome.SCOPE_VIOLATION
    assert r.resolve(B, ResolveQuery(reference=Reference("erp_code", "S-1"))).outcome \
        is AliasOutcome.NOT_FOUND


@pytest.mark.parametrize("scope", [AliasScope("", "c"), AliasScope("t", "  "), None])
def test_invalid_scope_is_scope_violation(scope):
    r = _res()
    r.add_entity(_ent("a1", A))
    assert r.resolve(scope, ResolveQuery(reference=Reference(TAX, "AB-123"))).outcome \
        is AliasOutcome.SCOPE_VIOLATION
    assert r.add_entity(_ent("z", scope)).outcome is AliasOutcome.SCOPE_VIOLATION


def test_duplicate_entity_id_rejected():
    r = _res()
    r.add_entity(_ent("a1", A))
    assert r.add_entity(_ent("a1", B)).outcome is AliasOutcome.REJECTED_DUPLICATE


def test_no_raw_input_echoed_in_codes():
    r = _res()
    secret = "SECRET-<script>-123"
    r.add_entity(_ent("a1", A))
    outs = [
        r.resolve(A, ResolveQuery(reference=Reference(TAX, secret))),
        r.resolve(A, ResolveQuery(reference=Reference(secret, " "))),
        r.resolve(AliasScope(secret, ""), ResolveQuery()),
        r.add_entity(SupplierEntity("a1", A, secret)),
        r.add_alias(AliasRecord(secret, A, "p", alias_text=secret)),
    ]
    for o in outs:
        assert secret not in o.code and o.code == o.code.upper()
    d = r.resolve_ambiguity(secret, secret, Approver(secret, ActorKind.AUTOMATION), secret)
    assert secret not in d.code


# ---- TC042 ------------------------------------------------------------------------------------
def test_tc042_two_candidates_ambiguous_one_queue_item_nothing_merged():
    r = _res()
    res = _ambiguous(r)
    assert res.outcome is AliasOutcome.AMBIGUOUS and not res.ok
    assert res.entity_id is None and res.candidate_ids == ("e1", "e2")
    items = r.queue_items()
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
    assert len(r.queue_items()) == 1


def test_tc042_same_name_in_scope_is_ambiguous_not_resolved():
    r = _res()
    r.add_entity(_ent("e1", A, "Acme", "1"))
    r.add_entity(_ent("e2", A, "ACME", "2"))
    res = r.resolve(A, ResolveQuery(name="acme"))
    assert res.outcome is AliasOutcome.AMBIGUOUS and res.candidate_ids == ("e1", "e2")
    assert len(r.queue_items()) == 1


def test_queue_items_are_scope_separated():
    r = _res()
    for scope, p in ((A, "a"), (B, "b")):
        r.add_entity(_ent(p + "1", scope, "Acme", p + "1"))
        r.add_entity(_ent(p + "2", scope, "Acme", p + "2"))
    ra = r.resolve(A, ResolveQuery(name="acme"))
    rb = r.resolve(B, ResolveQuery(name="acme"))
    assert ra.queue_item_id != rb.queue_item_id
    assert ra.candidate_ids == ("a1", "a2") and rb.candidate_ids == ("b1", "b2")


# ---- human resolution -------------------------------------------------------------------------
def test_human_resolution_happy_path_records_who_when_and_merges_nothing():
    r = _res()
    res = _ambiguous(r)
    out = r.resolve_ambiguity(res.queue_item_id, "e2", HUMAN, "  same legal entity per contract ")
    assert out.outcome is AliasOutcome.DECIDED and out.ok and not out.replay
    d = out.decision
    assert (d.chosen_entity_id, d.approver, d.reason, d.decided_at) == (
        "e2", "alice@example.com", "same legal entity per contract", NOW)
    assert r.queue_items()[0].decision == d
    # no merge / no alias rewrite: ambiguity persists, other scope untouched
    again = r.resolve(A, ResolveQuery(reference=Reference("erp_code", "S-9")))
    assert again.outcome is AliasOutcome.AMBIGUOUS
    assert r.resolve(B, ResolveQuery(reference=Reference("erp_code", "S-9"))).outcome \
        is AliasOutcome.NOT_FOUND


def test_automation_actor_refused():
    r = _res()
    res = _ambiguous(r)
    out = r.resolve_ambiguity(res.queue_item_id, "e1", Approver("bot", ActorKind.AUTOMATION), "x")
    assert out.outcome is AliasOutcome.REJECTED_APPROVER
    assert r.queue_items()[0].decision is None


@pytest.mark.parametrize("identity", ["", "   ", " "])
def test_blank_approver_refused(identity):
    r = _res()
    res = _ambiguous(r)
    out = r.resolve_ambiguity(res.queue_item_id, "e1", Approver(identity, ActorKind.HUMAN), "x")
    assert out.outcome is AliasOutcome.REJECTED_APPROVER
    assert r.queue_items()[0].decision is None


def test_non_approver_object_refused():
    r = _res()
    res = _ambiguous(r)
    assert r.resolve_ambiguity(res.queue_item_id, "e1", "alice", "x").outcome \
        is AliasOutcome.REJECTED_APPROVER


def test_blank_reason_refused():
    r = _res()
    res = _ambiguous(r)
    assert r.resolve_ambiguity(res.queue_item_id, "e1", HUMAN, "  ").outcome \
        is AliasOutcome.REJECTED_INPUT
    assert r.queue_items()[0].decision is None


def test_choice_must_be_a_candidate():
    r = _res()
    res = _ambiguous(r)
    r.add_entity(_ent("e3", B, "Other", "Q"))
    assert r.resolve_ambiguity(res.queue_item_id, "e3", HUMAN, "x").outcome \
        is AliasOutcome.REJECTED_CHOICE
    assert r.queue_items()[0].decision is None


def test_unknown_queue_item_refused():
    assert _res().resolve_ambiguity("RQ-nope", "e1", HUMAN, "x").outcome is AliasOutcome.UNKNOWN_ITEM


def test_same_decision_is_idempotent_and_keeps_first_record():
    ticks = iter([NOW, datetime(2026, 10, 10, tzinfo=UTC)])
    r = AliasResolver(clock=lambda: next(ticks))
    res = _ambiguous(r)
    first = r.resolve_ambiguity(res.queue_item_id, "e1", HUMAN, "first")
    second = r.resolve_ambiguity(res.queue_item_id, "e1", Approver("bob", ActorKind.HUMAN), "later")
    assert second.outcome is AliasOutcome.DECIDED and second.replay is True
    assert second.decision == first.decision and second.decision.decided_at == NOW


def test_conflicting_second_decision_refused_and_first_kept():
    r = _res()
    res = _ambiguous(r)
    first = r.resolve_ambiguity(res.queue_item_id, "e1", HUMAN, "first")
    second = r.resolve_ambiguity(res.queue_item_id, "e2", HUMAN, "changed mind")
    assert second.outcome is AliasOutcome.REJECTED_CONFLICT and second.decision is None
    assert r.queue_items()[0].decision == first.decision
