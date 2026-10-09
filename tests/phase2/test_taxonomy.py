"""R2-US-013 taxonomy/LDM candidates: TC037 / TC038 / TC039 (behavioural, deterministic)."""
from __future__ import annotations

import pytest

from business_ai_gateway.phase2.taxonomy import (
    Actor,
    EdgeKind,
    ProducerKind,
    Status,
    TaxonomyStore,
    TaxOutcome,
    TaxScope,
)

S1 = TaxScope("tenant-a", "company-1")
S2 = TaxScope("tenant-a", "company-2")
ALICE = Actor(ProducerKind.HUMAN, "alice")
BOB = Actor(ProducerKind.HUMAN, "bob")
CAROL = Actor(ProducerKind.HUMAN, "carol")
LLM = Actor(ProducerKind.LLM, "gpt-x")
AUTO = Actor(ProducerKind.AUTOMATION, "crawler")
RULE = Actor(ProducerKind.RULE, "rule-7", policy_ref="policy/auto-accept-1")


def _store(scope: TaxScope = S1, producer: Actor = ALICE):
    st = TaxonomyStore()
    a = st.propose_concept(scope, "Invoice", producer, 0.9).concept
    b = st.propose_concept(scope, "Document", producer, 0.9).concept
    r = st.propose_edge(scope, EdgeKind.IS_A, a.concept_id, b.concept_id, "invoice is a document",
                        producer, 0.8)
    assert r.ok
    return st, a, b, r.edge


# ---------------------------------------------------------------- TC037
def test_tc037_candidate_has_scope_provenance_confidence():
    _, a, _, e = _store()
    assert e.status is Status.CANDIDATE and e.version == 1
    assert e.scope == S1 and e.producer == ALICE and e.confidence == 0.8
    assert e.edge_id.startswith("e_")
    assert a.status is Status.CANDIDATE and a.scope == S1


@pytest.mark.parametrize("scope", [
    None, TaxScope("", "c"), TaxScope("t", ""), TaxScope("  ", "c"), TaxScope("t", "  "),
])
def test_tc037_missing_or_blank_scope_rejected(scope):
    st, a, b, _ = _store()
    r = st.propose_edge(scope, EdgeKind.PART_OF, a.concept_id, b.concept_id, "d", ALICE, 0.5)
    assert r.outcome is TaxOutcome.REJECTED_SCOPE and r.edge is None
    assert st.propose_concept(scope, "X", ALICE, 0.5).outcome is TaxOutcome.REJECTED_SCOPE
    assert st.edges_in_scope(scope) == ()


@pytest.mark.parametrize("conf", [-0.01, 1.01, float("nan"), "0.5", None, True])
def test_tc037_confidence_out_of_range_rejected(conf):
    st, a, b, _ = _store()
    r = st.propose_edge(S1, EdgeKind.PART_OF, a.concept_id, b.concept_id, "d", ALICE, conf)
    assert r.outcome is TaxOutcome.REJECTED_INPUT
    assert st.propose_concept(S1, "Y", ALICE, conf).outcome is TaxOutcome.REJECTED_INPUT
    assert len(st.edges_in_scope(S1)) == 1


def test_tc037_confidence_boundaries_accepted():
    st, a, b, _ = _store()
    assert st.propose_edge(S1, EdgeKind.PART_OF, a.concept_id, b.concept_id, "d", ALICE, 0.0).ok
    assert st.propose_edge(S1, EdgeKind.REFERENCES, a.concept_id, b.concept_id, "d", ALICE, 1).ok


def test_tc037_wrong_scope_query_returns_nothing():
    st, _, _, e = _store()
    assert st.edges_in_scope(S2) == ()
    assert st.versions(S2, e.edge_id) == ()
    assert st.get_version(S2, e.edge_id, 1) is None
    assert st.edges_in_scope(S1) == (e,)


def test_tc037_edge_cannot_link_concepts_from_another_scope():
    st, a, b, _ = _store()
    r = st.propose_edge(S2, EdgeKind.IS_A, a.concept_id, b.concept_id, "d", ALICE, 0.5)
    assert r.outcome is TaxOutcome.REJECTED_SCOPE and r.code == "CONCEPT_NOT_IN_SCOPE"
    assert st.edges_in_scope(S2) == ()


def test_tc037_wrong_scope_cannot_accept():
    st, _, _, e = _store()
    r = st.accept(S2, e.edge_id, BOB, "ev-1", 1)
    assert r.outcome is TaxOutcome.NOT_FOUND
    assert st.versions(S1, e.edge_id)[-1].status is Status.CANDIDATE


def test_tc037_llm_producer_can_propose_but_stays_candidate():
    st, a, b, _ = _store()
    r = st.propose_edge(S1, EdgeKind.DEPENDS_ON, a.concept_id, b.concept_id, "d", LLM, 0.4)
    assert r.ok and r.edge.status is Status.CANDIDATE and r.edge.producer.kind is ProducerKind.LLM


def test_duplicate_proposal_does_not_change_head():
    st, a, b, e = _store()
    r = st.propose_edge(S1, EdgeKind.IS_A, a.concept_id, b.concept_id, "other", BOB, 0.1)
    assert r.outcome is TaxOutcome.DUPLICATE
    assert st.versions(S1, e.edge_id) == (e,)


# ---------------------------------------------------------------- TC038
def test_accept_by_independent_human_succeeds():
    st, _, _, e = _store()
    r = st.accept(S1, e.edge_id, BOB, "ticket-42", 1)
    assert r.ok and r.edge.status is Status.ACCEPTED and r.edge.version == 2
    assert r.edge.decided_by == "bob" and r.edge.evidence_ref == "ticket-42"


def test_accept_by_rule_with_policy_succeeds():
    st, _, _, e = _store()
    assert st.accept(S1, e.edge_id, RULE, "ev", 1).ok


def test_rule_without_policy_refused():
    st, _, _, e = _store()
    r = st.accept(S1, e.edge_id, Actor(ProducerKind.RULE, "rule-7", policy_ref=" "), "ev", 1)
    assert r.outcome is TaxOutcome.REJECTED_ACTOR_KIND and r.code == "RULE_POLICY_REQUIRED"
    assert len(st.versions(S1, e.edge_id)) == 1


@pytest.mark.parametrize("actor", [LLM, AUTO])
def test_tc038_llm_and_automation_cannot_accept(actor):
    st, _, _, e = _store()
    r = st.accept(S1, e.edge_id, actor, "ev", 1)
    assert r.outcome is TaxOutcome.REJECTED_ACTOR_KIND and r.code == "ACTOR_CANNOT_ACCEPT"
    vs = st.versions(S1, e.edge_id)
    assert len(vs) == 1 and vs[0].status is Status.CANDIDATE and vs[0].version == 1


@pytest.mark.parametrize("actor", [LLM, AUTO])
def test_tc038_llm_and_automation_cannot_reject(actor):
    st, _, _, e = _store()
    r = st.reject(S1, e.edge_id, actor, "ev", 1)
    assert r.outcome is TaxOutcome.REJECTED_ACTOR_KIND
    assert len(st.versions(S1, e.edge_id)) == 1


def test_tc038_non_enum_kind_cannot_accept():
    st, _, _, e = _store()
    fake = Actor("HUMAN-ish", "zed")  # type: ignore[arg-type]
    assert st.accept(S1, e.edge_id, fake, "ev", 1).outcome is TaxOutcome.REJECTED_INPUT
    assert len(st.versions(S1, e.edge_id)) == 1


@pytest.mark.parametrize("approver_id", ["alice", "ALICE", "  alice  ", "Ａlice", "ＡＬＩＣＥ"])
def test_tc038_self_approval_refused_incl_normalisation(approver_id):
    st, _, _, e = _store()
    r = st.accept(S1, e.edge_id, Actor(ProducerKind.HUMAN, approver_id), "ev", 1)
    assert r.outcome is TaxOutcome.REJECTED_SELF_APPROVAL
    assert len(st.versions(S1, e.edge_id)) == 1


def test_tc038_previous_proposer_cannot_approve_after_supersede():
    st, _, _, e = _store()  # alice proposes
    r = st.supersede_semantics(S1, e.edge_id, "new meaning", BOB, 0.7, 1)  # bob proposes v2
    assert r.ok
    # alice (original proposer) and bob (current proposer) both refused; carol ok
    assert st.accept(S1, e.edge_id, ALICE, "ev", 2).outcome is TaxOutcome.REJECTED_SELF_APPROVAL
    assert st.accept(S1, e.edge_id, BOB, "ev", 2).outcome is TaxOutcome.REJECTED_SELF_APPROVAL
    assert st.accept(S1, e.edge_id, CAROL, "ev", 2).ok


@pytest.mark.parametrize("ev", ["", "   ", None])
def test_tc038_blank_evidence_refused(ev):
    st, _, _, e = _store()
    r = st.accept(S1, e.edge_id, BOB, ev, 1)
    assert r.outcome is TaxOutcome.REJECTED_EVIDENCE
    assert len(st.versions(S1, e.edge_id)) == 1


@pytest.mark.parametrize("expected", [0, 2, -1, "1", None])
def test_tc038_stale_expected_version_refused(expected):
    st, _, _, e = _store()
    r = st.accept(S1, e.edge_id, BOB, "ev", expected)
    assert r.outcome is TaxOutcome.REJECTED_CAS
    assert len(st.versions(S1, e.edge_id)) == 1


def test_accept_twice_second_refused():
    st, _, _, e = _store()
    assert st.accept(S1, e.edge_id, BOB, "ev", 1).ok
    assert st.accept(S1, e.edge_id, CAROL, "ev", 2).outcome is TaxOutcome.REJECTED_STATE


def test_reject_then_cannot_accept_without_new_proposal():
    st, a, b, e = _store()
    r = st.reject(S1, e.edge_id, BOB, "ev-no", 1)
    assert r.ok and r.edge.status is Status.REJECTED
    assert st.accept(S1, e.edge_id, CAROL, "ev", 2).outcome is TaxOutcome.REJECTED_STATE
    assert st.supersede_semantics(S1, e.edge_id, "x", CAROL, 0.5, 2).outcome \
        is TaxOutcome.REJECTED_STATE
    # a new proposal re-opens it as a new version, still bound by independence
    p = st.propose_edge(S1, EdgeKind.IS_A, a.concept_id, b.concept_id, "retry", CAROL, 0.6)
    assert p.ok and p.edge.version == 3 and p.edge.status is Status.CANDIDATE
    assert st.accept(S1, e.edge_id, CAROL, "ev", 3).outcome is TaxOutcome.REJECTED_SELF_APPROVAL
    assert st.accept(S1, e.edge_id, ALICE, "ev", 3).outcome is TaxOutcome.REJECTED_SELF_APPROVAL
    assert st.accept(S1, e.edge_id, BOB, "ev", 3).ok


def test_reject_requires_evidence_and_cas():
    st, _, _, e = _store()
    assert st.reject(S1, e.edge_id, BOB, " ", 1).outcome is TaxOutcome.REJECTED_EVIDENCE
    assert st.reject(S1, e.edge_id, BOB, "ev", 5).outcome is TaxOutcome.REJECTED_CAS
    assert len(st.versions(S1, e.edge_id)) == 1


def test_unknown_edge_not_found():
    st, _, _, _ = _store()
    assert st.accept(S1, "e_nope", BOB, "ev", 1).outcome is TaxOutcome.NOT_FOUND


# ---------------------------------------------------------------- TC039
def test_tc039_supersede_creates_new_version_old_unchanged():
    st, _, _, e = _store()
    acc = st.accept(S1, e.edge_id, BOB, "ev", 1).edge
    r = st.supersede_semantics(S1, e.edge_id, "narrower meaning", CAROL, 0.6, acc.version)
    assert r.ok
    n = r.edge
    assert n.edge_id == e.edge_id and n.version == 3 and n.status is Status.CANDIDATE
    assert n.definition == "narrower meaning" and n.decided_by == "" and n.evidence_ref == ""
    # old versions still readable, byte-identical, links intact
    assert st.get_version(S1, e.edge_id, 1) == e
    assert st.get_version(S1, e.edge_id, 2) == acc
    assert acc.definition == "invoice is a document" and acc.status is Status.ACCEPTED
    assert (acc.source_id, acc.target_id) == (e.source_id, e.target_id) == (n.source_id, n.target_id)
    assert [v.version for v in st.versions(S1, e.edge_id)] == [1, 2, 3]
    assert st.edges_in_scope(S1) == (n,)


def test_tc039_supersede_cas_and_input_guards():
    st, _, _, e = _store()
    assert st.supersede_semantics(S1, e.edge_id, "x", BOB, 0.5, 9).outcome is TaxOutcome.REJECTED_CAS
    assert st.supersede_semantics(S1, e.edge_id, " ", BOB, 0.5, 1).outcome \
        is TaxOutcome.REJECTED_INPUT
    assert st.supersede_semantics(S1, e.edge_id, "x", BOB, 2.0, 1).outcome \
        is TaxOutcome.REJECTED_INPUT
    assert st.supersede_semantics(S2, e.edge_id, "x", BOB, 0.5, 1).outcome is TaxOutcome.NOT_FOUND
    assert len(st.versions(S1, e.edge_id)) == 1


def test_tc039_ids_stable_across_versions_and_deterministic():
    st1, _, _, e1 = _store()
    _, _, _, e2 = _store()
    assert e1.edge_id == e2.edge_id
    st1.supersede_semantics(S1, e1.edge_id, "v2", BOB, 0.5, 1)
    assert {v.edge_id for v in st1.versions(S1, e1.edge_id)} == {e1.edge_id}


def test_tc039_llm_supersede_stays_candidate_and_cannot_self_accept():
    st, _, _, e = _store()
    r = st.supersede_semantics(S1, e.edge_id, "llm meaning", LLM, 0.3, 1)
    assert r.ok and r.edge.status is Status.CANDIDATE
    assert st.accept(S1, e.edge_id, LLM, "ev", 2).outcome is TaxOutcome.REJECTED_ACTOR_KIND
