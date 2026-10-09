"""R2-US-034 validation coverage: TC100 claims/evidence coverage, TC101 ten duplicate cases with
distinct codes, TC102 'purchases validated' opens nothing for AP and the module has no write path."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from business_ai_gateway.phase2 import validation_coverage as vc
from business_ai_gateway.phase2.validation_coverage import (
    Claim,
    ClaimScope,
    CoverageCode,
    CoverageStatus,
    Evidence,
    EvidenceVerdict,
    Link,
    build_matrix,
    capability_enabled,
)

S = ClaimScope("t1", "companyA")
S2 = ClaimScope("t1", "companyB")
PASS = EvidenceVerdict.PASS


def h(n: int) -> str:
    return f"{n:064x}"


def claim(cid="c1", cap="purchases", op="validate", scope=S):
    return Claim(cid, scope, cap, op)


def ev(eid="e1", n=1, src="src-1", scope=S, verdict=PASS):
    return Evidence(eid, scope, src, h(n), verdict)


def build(claims, evidence, links):
    return build_matrix(tuple(claims), tuple(evidence), tuple(links))


# ---------------------------------------------------------------- TC100
def test_tc100_every_claim_covered_is_complete_and_accepted():
    r = build([claim("c1"), claim("c2", cap="sales")], [ev("e1", 1, "s1"), ev("e2", 2, "s2")],
              [Link("c1", "e1"), Link("c2", "e2")])
    assert r.status is CoverageStatus.COMPLETE and r.code is CoverageCode.OK and r.accepted
    assert {(x.claim_id, x.evidence_ids) for x in r.rows} == {("c1", ("e1",)), ("c2", ("e2",))}
    assert r.uncovered == () and len(r.digest) == 64


def test_tc100_uncovered_claim_makes_matrix_incomplete_and_refused():
    r = build([claim("c1"), claim("c2", cap="sales")], [ev("e1")], [Link("c1", "e1")])
    assert r.status is CoverageStatus.INCOMPLETE and r.code is CoverageCode.UNCOVERED_CLAIM
    assert not r.accepted and r.uncovered == ("c2",)
    assert not capability_enabled(r, S, "purchases") and not capability_enabled(r, S, "sales")


@pytest.mark.parametrize("verdict", [EvidenceVerdict.FAIL, EvidenceVerdict.NOT_RUN])
def test_tc100_non_pass_evidence_does_not_cover(verdict):
    r = build([claim()], [ev(verdict=verdict)], [Link("c1", "e1")])
    assert r.status is CoverageStatus.INCOMPLETE and r.uncovered == ("c1",) and not r.accepted


def test_tc100_claim_with_no_links_and_empty_matrix():
    assert build([claim()], [ev()], []).status is CoverageStatus.INCOMPLETE
    assert build([], [], []).code is CoverageCode.EMPTY_MATRIX


def test_tc100_digest_is_stable_and_changes_with_evidence():
    a = build([claim()], [ev("e1", 1)], [Link("c1", "e1")])
    assert a.digest == build([claim()], [ev("e1", 1)], [Link("c1", "e1")]).digest
    assert a.digest != build([claim()], [ev("e9", 1)], [Link("c1", "e9")]).digest


def test_tc100_evidence_of_another_scope_cannot_cover():
    r = build([claim()], [ev(scope=S2)], [Link("c1", "e1")])
    assert r.code is CoverageCode.LINK_SCOPE_MISMATCH and not r.accepted


@pytest.mark.parametrize("claims,evidence,links,code", [
    ([claim()], [ev()], [Link("c1", "nope")], CoverageCode.LINK_UNKNOWN_REF),
    ([claim()], [ev()], [Link("nope", "e1")], CoverageCode.LINK_UNKNOWN_REF),
    ([claim()], [ev()], [Link("", "e1")], CoverageCode.LINK_INVALID),
    ([claim()], [ev()], ["c1:e1"], CoverageCode.LINK_INVALID),
    ([claim(cid="")], [ev()], [], CoverageCode.CLAIM_INVALID),
    ([claim(cap="  ")], [ev()], [], CoverageCode.CLAIM_INVALID),
    ([claim(scope=ClaimScope("", "x"))], [ev()], [], CoverageCode.CLAIM_INVALID),
    (["not a claim"], [ev()], [], CoverageCode.CLAIM_INVALID),
    ([claim()], [Evidence("e1", S, "s", "XYZ", PASS)], [], CoverageCode.EVIDENCE_INVALID),
    ([claim()], [Evidence("e1", S, "s", h(255).upper(), PASS)], [], CoverageCode.EVIDENCE_INVALID),
    ([claim()], [Evidence("e1", S, "s", h(1), "PASS")], [], CoverageCode.EVIDENCE_INVALID),
    ([claim()], [Evidence("e1", S, "", h(1), PASS)], [], CoverageCode.EVIDENCE_INVALID),
])
def test_tc100_invalid_inputs_are_refused_with_fixed_codes(claims, evidence, links, code):
    r = build(claims, evidence, links)
    assert r.status is CoverageStatus.REFUSED and r.code is code and not r.accepted


def test_tc100_non_sequence_inputs_refused():
    assert build_matrix(None, (), ()).status is CoverageStatus.REFUSED
    assert build_matrix(1, 2, 3).status is CoverageStatus.REFUSED


# ---------------------------------------------------------------- TC101
CYR_CO = "со"  # Cyrillic 'co', skeleton-equal to Latin 'co'

TEN_CASES = [
    ("DUP_CLAIM_ID", [claim("c1"), claim("c1", cap="sales")], [ev()], []),
    ("DUP_CLAIM_SEMANTIC", [claim("c1"), claim("c2", cap=" PURCHASES ")], [ev()], []),
    ("DUP_CLAIM_LOOKALIKE", [claim("c1", cap="co"), claim("c2", cap=CYR_CO)], [ev()], []),
    ("DUP_CLAIM_OVERLAP", [claim("c1", cap="purchases"), claim("c2", cap="purchases.receipts")],
     [ev()], []),
    ("DUP_EVIDENCE_ID", [claim()], [ev("e1", 1, "s1"), ev("e1", 2, "s2")], []),
    ("DUP_EVIDENCE_DIGEST", [claim()], [ev("e1", 1, "s1"), ev("e2", 1, "s2")], []),
    ("DUP_EVIDENCE_SOURCE", [claim()], [ev("e1", 1, "same"), ev("e2", 2, " SAME ")], []),
    ("DUP_LINK", [claim()], [ev()], [Link("c1", "e1"), Link("c1", "e1")]),
    ("EVIDENCE_SHARED_ACROSS_OPERATIONS",
     [claim("c1", op="validate"), claim("c2", op="reconcile")], [ev()],
     [Link("c1", "e1"), Link("c2", "e1")]),
    ("EVIDENCE_SHARED_ACROSS_CAPABILITIES",
     [claim("c1", cap="purchases"), claim("c2", cap="sales")], [ev()],
     [Link("c1", "e1"), Link("c2", "e1")]),
]


@pytest.mark.parametrize("code,claims,evidence,links", TEN_CASES, ids=[c[0] for c in TEN_CASES])
def test_tc101_each_duplicate_case_is_rejected_with_its_own_code(code, claims, evidence, links):
    r = build(claims, evidence, links)
    assert r.status is CoverageStatus.REFUSED and not r.accepted and r.rows == ()
    assert r.code is CoverageCode(code)


def test_tc101_the_ten_codes_are_distinct_and_cover_ten_cases():
    codes = [build(c, e, lk).code for _n, c, e, lk in TEN_CASES]
    assert len(TEN_CASES) == 10 and len(set(codes)) == 10


def test_tc101_same_digest_in_different_scopes_is_not_a_duplicate():
    r = build([claim("c1"), claim("c2", scope=S2)],
              [ev("e1", 1, "s1"), ev("e2", 1, "s1", scope=S2)],
              [Link("c1", "e1"), Link("c2", "e2")])
    assert r.accepted


# ---------------------------------------------------------------- TC102
def test_tc102_purchases_validated_opens_nothing_for_ap():
    r = build([claim("c1", cap="purchases")], [ev()], [Link("c1", "e1")])
    assert r.accepted
    assert capability_enabled(r, S, "purchases")
    for other in ("ap.account_based", "ap", "purchases.receipts", "purch", "sales", "", None, 5):
        assert not capability_enabled(r, S, other)


def test_tc102_ap_claim_is_refused_even_with_passing_evidence():
    r = build([claim("c1", cap="purchases"), claim("c2", cap="ap.account_based")],
              [ev("e1", 1, "s1"), ev("e2", 2, "s2")], [Link("c1", "e1"), Link("c2", "e2")])
    assert r.status is CoverageStatus.REFUSED and r.code is CoverageCode.CAPABILITY_NOT_OPENED
    assert not capability_enabled(r, S, "ap.account_based") and not capability_enabled(r, S, "purchases")


def test_tc102_purchases_evidence_cannot_back_an_ap_claim():
    r = build([claim("c1", cap="purchases"), claim("c2", cap="ap.other")], [ev()],
              [Link("c1", "e1"), Link("c2", "e1")])
    assert r.code is CoverageCode.EVIDENCE_SHARED_ACROSS_CAPABILITIES


def test_tc102_enabled_requires_an_accepted_matrix_of_the_right_type():
    partial = build([claim("c1"), claim("c2", cap="sales")], [ev()], [Link("c1", "e1")])
    assert not capability_enabled(partial, S, "purchases")
    assert not capability_enabled({"rows": ()}, S, "purchases")


def test_tc102_static_proxy_imports_and_calls_only_no_write_primitives():
    # STATIC PROXY ONLY: an AST scan of imports/calls/attributes. It does not prove absence of a
    # write path (aliasing, getattr, indirect calls are not detected); it only guards the obvious.
    tree = ast.parse(Path(vc.__file__).read_text(encoding="utf-8"))
    stdlib_ok = {"__future__", "hashlib", "dataclasses", "enum"}
    imported: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [(0, a.name.split(".")[0]) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append((node.level, node.module or ""))
    for level, name in imported:
        if level == 0:
            assert name in stdlib_ok, name
        else:
            assert (level, name) == (1, "_identity"), (level, name)
    banned_calls = {"open", "exec", "eval", "compile", "__import__"}
    called = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not called & banned_calls
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"write_text", "write_bytes", "execute", "executemany", "commit", "import_module"}


# ---------------------------------------------------------------- review-fix batch
@pytest.mark.parametrize("cap", [
    "ap.account_based", "ap.account_based.invoices", "ap.account_based.", "ap", "AP.Account_Based.X",
    ".ap.account_based", "ap..account_based",
])
def test_reserved_capability_family_is_refused_and_never_enabled(cap):
    r = build([claim("c1", cap="purchases"), claim("c2", cap=cap)],
              [ev("e1", 1, "s1"), ev("e2", 2, "s2")], [Link("c1", "e1"), Link("c2", "e2")])
    assert r.status is CoverageStatus.REFUSED and r.code is CoverageCode.CAPABILITY_NOT_OPENED
    ok = build([claim("c1", cap="purchases")], [ev()], [Link("c1", "e1")])
    assert ok.accepted and not capability_enabled(ok, S, cap)


@pytest.mark.parametrize("verdicts", [[PASS, EvidenceVerdict.FAIL], [PASS, EvidenceVerdict.NOT_RUN]])
def test_pass_beside_non_pass_link_is_never_complete(verdicts):
    r = build([claim()], [ev("e1", 1, "s1", verdict=verdicts[0]), ev("e2", 2, "s2", verdict=verdicts[1])],
              [Link("c1", "e1"), Link("c1", "e2")])
    assert r.status is CoverageStatus.INCOMPLETE and r.code is CoverageCode.NON_PASS_LINK
    assert not r.accepted and r.non_pass == ("c1",) and r.rows[0].evidence_ids == ("e1",)
    assert not capability_enabled(r, S, "purchases")


def _good():
    return build([claim("c1"), claim("c2", cap="sales")], [ev("e1", 1, "s1"), ev("e2", 2, "s2")],
                 [Link("c1", "e1"), Link("c2", "e2")])


def _forged(rows, base=None):
    base = base or _good()
    return vc.MatrixResult(CoverageStatus.COMPLETE, CoverageCode.OK, tuple(rows), (), base.digest)


def test_capability_enabled_rejects_hand_built_forged_results():
    good = _good()
    assert capability_enabled(good, S, "purchases")
    row = good.rows[0]
    # forged status over rows that were never verified: digest mismatch
    assert not capability_enabled(vc.MatrixResult(CoverageStatus.COMPLETE, CoverageCode.OK), S, "purchases")
    assert not capability_enabled(_forged([row]), S, "purchases")  # row dropped, stale digest
    import dataclasses
    swapped = dataclasses.replace(row, capability="payroll")
    assert not capability_enabled(_forged([swapped, good.rows[1]]), S, "payroll")
    tampered_ev = dataclasses.replace(row, evidence_digests=(h(99),))
    assert not capability_enabled(_forged([tampered_ev, good.rows[1]]), S, "purchases")
    # consistent digest but reserved capability in a row
    res_row = dataclasses.replace(row, capability="ap.account_based.invoices")
    forged = vc.MatrixResult(CoverageStatus.COMPLETE, CoverageCode.OK, (res_row,), (),
                             vc._matrix_digest((res_row,)))
    assert not capability_enabled(forged, S, "ap.account_based.invoices")
    # consistent digest but duplicate claim ids
    dup = vc.MatrixResult(CoverageStatus.COMPLETE, CoverageCode.OK, (row, row), (),
                          vc._matrix_digest((row, row)))
    assert not capability_enabled(dup, S, "purchases")
    # consistent digest but empty evidence
    bare = dataclasses.replace(row, evidence_ids=(), evidence_digests=(), evidence_sources=())
    forged = vc.MatrixResult(CoverageStatus.COMPLETE, CoverageCode.OK, (bare,), (),
                             vc._matrix_digest((bare,)))
    assert not capability_enabled(forged, S, "purchases")


def test_digest_binds_scope_evidence_digest_source_and_is_order_independent():
    base = build([claim()], [ev("e1", 1, "s1")], [Link("c1", "e1")])
    other_tenant = build([claim(scope=ClaimScope("t2", "companyA"))],
                         [ev("e1", 1, "s1", scope=ClaimScope("t2", "companyA"))], [Link("c1", "e1")])
    other_company = build([claim(scope=S2)], [ev("e1", 1, "s1", scope=S2)], [Link("c1", "e1")])
    assert len({base.digest, other_tenant.digest, other_company.digest}) == 3
    assert build([claim()], [ev("e1", 2, "s1")], [Link("c1", "e1")]).digest != base.digest
    assert build([claim()], [ev("e1", 1, "s9")], [Link("c1", "e1")]).digest != base.digest
    a = build([claim("c1"), claim("c2", cap="sales")], [ev("e1", 1, "s1"), ev("e2", 2, "s2")],
              [Link("c1", "e1"), Link("c2", "e2")])
    b = build([claim("c2", cap="sales"), claim("c1")], [ev("e2", 2, "s2"), ev("e1", 1, "s1")],
              [Link("c2", "e2"), Link("c1", "e1")])
    assert a.digest == b.digest and a.accepted and b.accepted


def test_digest_binds_verdict_and_claim_text():
    base = build([claim()], [ev()], [Link("c1", "e1")])
    failed = build([claim()], [ev(verdict=EvidenceVerdict.FAIL)], [Link("c1", "e1")])
    mixed = build([claim()], [ev("e1", 1, "s1"), ev("e2", 2, "s2", verdict=EvidenceVerdict.FAIL)],
                  [Link("c1", "e1"), Link("c1", "e2")])
    solo = build([claim()], [ev("e1", 1, "s1")], [Link("c1", "e1")])
    assert len({base.digest, failed.digest, mixed.digest}) == 3 and mixed.digest != solo.digest
    assert build([claim(cap="sales")], [ev()], [Link("c1", "e1")]).digest != base.digest
    assert build([claim(op="reconcile")], [ev()], [Link("c1", "e1")]).digest != base.digest
    assert build([claim("c9")], [ev()], [Link("c9", "e1")]).digest != base.digest


def test_scope_a_coverage_does_not_enable_scope_b():
    r = build([claim("c1", scope=S), claim("c2", cap="sales", scope=S2)],
              [ev("e1", 1, "s1", scope=S), ev("e2", 2, "s2", scope=S2)],
              [Link("c1", "e1"), Link("c2", "e2")])
    assert r.accepted
    assert capability_enabled(r, S, "purchases") and capability_enabled(r, S2, "sales")
    assert not capability_enabled(r, S2, "purchases") and not capability_enabled(r, S, "sales")
    assert not capability_enabled(r, ClaimScope("t2", "companyA"), "purchases")
    assert not capability_enabled(r, None, "purchases") and not capability_enabled(r, ("t1", "companyA"), "purchases")
    assert not capability_enabled(r, ClaimScope("", "x"), "purchases")


@pytest.mark.parametrize("cap", ["ap.account_bаsed", "аp.account_based.invoices"])
def test_reserved_mixed_script_lookalike_is_refused_never_enabled(cap):
    # mixed-script spoofs are refused earlier as invalid identities (CLAIM_INVALID); the skeleton
    # form in _is_reserved is a defence-in-depth layer behind that and is not separately reachable.
    r = build([claim("c1", cap=cap)], [ev()], [Link("c1", "e1")])
    assert r.status is CoverageStatus.REFUSED and not r.accepted
    ok = build([claim("c1", cap="purchases")], [ev()], [Link("c1", "e1")])
    assert not capability_enabled(ok, S, cap)
