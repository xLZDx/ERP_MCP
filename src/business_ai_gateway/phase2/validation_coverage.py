"""Phase 2 operation validation coverage matrix (R2-US-034): pure, in-memory, no I/O, no clock.

Maps every CLAIMED capability to the evidence that supports it. It decides nothing about the
evidence itself (that is attestation, E1); it only proves that every claim is covered and that the
matrix does not double-count or inherit.

Rules
- A claim is (claim_id, scope, capability, operation). Evidence is (evidence_id, scope, source_ref,
  digest, verdict). A link binds ONE evidence to ONE claim. Evidence counts only with verdict PASS.
- A claim without a PASS-evidence link is UNCOVERED: the matrix is INCOMPLETE and refused
  (``accepted`` is False, nothing is enabled).
- No cross-claim inheritance: coverage is per claim. Evidence is scope-bound (a link across scopes is
  refused), so evidence can never serve another company/tenant; sharing one evidence between claims
  of the same scope is refused (codes 9 and 10 below). ``capability_enabled`` answers True only for
  the exact capability of a covered claim in an accepted matrix.
- ``ap.account_based`` (R2-US-031, NOT_STARTED) is a reserved capability: a claim for it is refused
  (CAPABILITY_NOT_OPENED) whatever evidence exists. "purchases validated" therefore opens nothing for AP.
- Ten duplicate/overlap cases, each with its OWN fixed code (first violation in this order wins):
    1 DUP_CLAIM_ID               same claim_id twice
    2 DUP_CLAIM_SEMANTIC         same scope+capability+operation under two claim ids (same claim twice)
    3 DUP_CLAIM_LOOKALIKE        same as 2 after the confusable-skeleton fold (spoofed duplicate)
    4 DUP_CLAIM_OVERLAP          same scope+operation, capabilities in a dotted parent/child relation
                                 ("purchases" vs "purchases.receipts"): one claim silently covers the other
    5 DUP_EVIDENCE_ID            same evidence_id twice
    6 DUP_EVIDENCE_DIGEST        same artifact digest registered twice in one scope under two ids
    7 DUP_EVIDENCE_SOURCE        same source_ref twice in one scope (same source counted twice)
    8 DUP_LINK                   same (claim, evidence) link twice
    9 EVIDENCE_SHARED_ACROSS_OPERATIONS    one evidence linked to claims of different operations
                                 with no scope difference (links across scopes are refused anyway)
   10 EVIDENCE_SHARED_ACROSS_CAPABILITIES  one evidence linked to claims of different capabilities
                                 (same operation) - the cross-claim inheritance attempt
- Result codes are fixed constants; caller-supplied text is never echoed into them.
- No write path: this module imports only the standard library and ``_identity`` (audited by test).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from ._identity import clean_identity, exact_text, scope_key, skeleton, stable_key

__all__ = [
    "RESERVED_CAPABILITIES", "Claim", "ClaimScope", "CoverageCode", "CoverageStatus",
    "Evidence", "EvidenceVerdict", "Link", "MatrixResult", "MatrixRow", "build_matrix",
    "capability_enabled",
]

RESERVED_CAPABILITIES = frozenset({"ap.account_based"})
_HEX = frozenset("0123456789abcdef")


class CoverageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    REFUSED = "REFUSED"


class EvidenceVerdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_RUN = "NOT_RUN"


class CoverageCode(StrEnum):
    OK = "OK"
    UNCOVERED_CLAIM = "UNCOVERED_CLAIM"
    EMPTY_MATRIX = "EMPTY_MATRIX"
    CLAIM_INVALID = "CLAIM_INVALID"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"
    LINK_INVALID = "LINK_INVALID"
    LINK_UNKNOWN_REF = "LINK_UNKNOWN_REF"
    LINK_SCOPE_MISMATCH = "LINK_SCOPE_MISMATCH"
    CAPABILITY_NOT_OPENED = "CAPABILITY_NOT_OPENED"
    DUP_CLAIM_ID = "DUP_CLAIM_ID"
    DUP_CLAIM_SEMANTIC = "DUP_CLAIM_SEMANTIC"
    DUP_CLAIM_LOOKALIKE = "DUP_CLAIM_LOOKALIKE"
    DUP_CLAIM_OVERLAP = "DUP_CLAIM_OVERLAP"
    DUP_EVIDENCE_ID = "DUP_EVIDENCE_ID"
    DUP_EVIDENCE_DIGEST = "DUP_EVIDENCE_DIGEST"
    DUP_EVIDENCE_SOURCE = "DUP_EVIDENCE_SOURCE"
    DUP_LINK = "DUP_LINK"
    EVIDENCE_SHARED_ACROSS_OPERATIONS = "EVIDENCE_SHARED_ACROSS_OPERATIONS"
    EVIDENCE_SHARED_ACROSS_CAPABILITIES = "EVIDENCE_SHARED_ACROSS_CAPABILITIES"


@dataclass(frozen=True, slots=True)
class ClaimScope:
    tenant_id: str
    company_id: str

    def key(self) -> tuple[str, str] | None:
        return scope_key(self.tenant_id, self.company_id)


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: str
    scope: ClaimScope
    capability: str
    operation: str


@dataclass(frozen=True, slots=True)
class Evidence:
    evidence_id: str
    scope: ClaimScope
    source_ref: str
    digest: str  # lowercase hex sha256 of the evidence artifact
    verdict: EvidenceVerdict


@dataclass(frozen=True, slots=True)
class Link:
    claim_id: str
    evidence_id: str


@dataclass(frozen=True, slots=True)
class MatrixRow:
    claim_id: str
    capability: str
    operation: str
    evidence_ids: tuple[str, ...]  # PASS evidence only; empty means uncovered


@dataclass(frozen=True, slots=True)
class MatrixResult:
    status: CoverageStatus
    code: CoverageCode
    rows: tuple[MatrixRow, ...] = ()
    uncovered: tuple[str, ...] = ()
    digest: str = ""

    @property
    def accepted(self) -> bool:
        return self.status is CoverageStatus.COMPLETE


def _refuse(code: CoverageCode) -> MatrixResult:
    return MatrixResult(CoverageStatus.REFUSED, code)


def _valid_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def _claim_norm(claim: object) -> tuple[str, tuple[str, str], str, str] | None:
    if type(claim) is not Claim or type(claim.scope) is not ClaimScope:
        return None
    cid, scope = exact_text(claim.claim_id), claim.scope.key()
    cap, op = clean_identity(claim.capability), clean_identity(claim.operation)
    return (cid, scope, cap, op) if cid and scope and cap and op else None


def _evidence_norm(ev: object) -> tuple[str, tuple[str, str], str, str, EvidenceVerdict] | None:
    if type(ev) is not Evidence or type(ev.scope) is not ClaimScope:
        return None
    eid, scope, src = exact_text(ev.evidence_id), ev.scope.key(), clean_identity(ev.source_ref)
    if not (eid and scope and src and _valid_digest(ev.digest) and type(ev.verdict) is EvidenceVerdict):
        return None
    return eid, scope, src, ev.digest, ev.verdict


def _related(a: str, b: str) -> bool:
    return a.startswith(b + ".") or b.startswith(a + ".")


def _claim_dups(claims: list[tuple[str, tuple[str, str], str, str]]) -> CoverageCode | None:
    ids: set[str] = set()
    semantic: set[tuple[tuple[str, str], str, str]] = set()
    lookalike: set[tuple[str, str, str, str]] = set()
    seen: list[tuple[tuple[str, str], str, str]] = []
    for cid, scope, cap, op in claims:
        if cid in ids:
            return CoverageCode.DUP_CLAIM_ID
        sem = (scope, cap, op)
        if sem in semantic:
            return CoverageCode.DUP_CLAIM_SEMANTIC
        look = (skeleton(scope[0]), skeleton(scope[1]), skeleton(cap), skeleton(op))
        if look in lookalike:
            return CoverageCode.DUP_CLAIM_LOOKALIKE
        if any(s == scope and o == op and _related(c, cap) for s, c, o in seen):
            return CoverageCode.DUP_CLAIM_OVERLAP
        ids.add(cid)
        semantic.add(sem)
        lookalike.add(look)
        seen.append(sem)
    return None


def _evidence_dups(items: list[tuple[str, tuple[str, str], str, str, EvidenceVerdict]]) -> CoverageCode | None:
    ids: set[str] = set()
    digests: set[tuple[tuple[str, str], str]] = set()
    sources: set[tuple[tuple[str, str], str]] = set()
    for eid, scope, src, digest, _verdict in items:
        if eid in ids:
            return CoverageCode.DUP_EVIDENCE_ID
        if (scope, digest) in digests:
            return CoverageCode.DUP_EVIDENCE_DIGEST
        if (scope, src) in sources:
            return CoverageCode.DUP_EVIDENCE_SOURCE
        ids.add(eid)
        digests.add((scope, digest))
        sources.add((scope, src))
    return None


def build_matrix(claims: object, evidence: object, links: object) -> MatrixResult:
    """Build the coverage matrix; any structural/duplicate violation REFUSES it, an uncovered claim
    makes it INCOMPLETE (also not accepted). Only COMPLETE enables anything."""
    if not all(isinstance(x, (tuple, list)) for x in (claims, evidence, links)):
        return _refuse(CoverageCode.CLAIM_INVALID)
    if not claims:
        return _refuse(CoverageCode.EMPTY_MATRIX)
    nclaims = [_claim_norm(c) for c in claims]
    if any(n is None for n in nclaims):
        return _refuse(CoverageCode.CLAIM_INVALID)
    cl = [n for n in nclaims if n is not None]
    if any(cap in RESERVED_CAPABILITIES for _, _, cap, _ in cl):
        return _refuse(CoverageCode.CAPABILITY_NOT_OPENED)
    nev = [_evidence_norm(e) for e in evidence]
    if any(n is None for n in nev):
        return _refuse(CoverageCode.EVIDENCE_INVALID)
    ev = [n for n in nev if n is not None]
    if any(type(lk) is not Link or not exact_text(lk.claim_id) or not exact_text(lk.evidence_id)
           for lk in links):
        return _refuse(CoverageCode.LINK_INVALID)
    dup = _claim_dups(cl) or _evidence_dups(ev)
    if dup is not None:
        return _refuse(dup)

    by_claim = {c[0]: c for c in cl}
    by_ev = {e[0]: e for e in ev}
    seen_links: set[tuple[str, str]] = set()
    claims_of: dict[str, list[str]] = {}
    for lk in links:  # type: ignore[attr-defined]
        pair = (exact_text(lk.claim_id), exact_text(lk.evidence_id))
        if pair[0] not in by_claim or pair[1] not in by_ev:
            return _refuse(CoverageCode.LINK_UNKNOWN_REF)
        if by_claim[pair[0]][1] != by_ev[pair[1]][1]:
            return _refuse(CoverageCode.LINK_SCOPE_MISMATCH)
        if pair in seen_links:
            return _refuse(CoverageCode.DUP_LINK)
        seen_links.add(pair)
        claims_of.setdefault(pair[1], []).append(pair[0])
    for linked in claims_of.values():
        if len({by_claim[c][3] for c in linked}) > 1:
            return _refuse(CoverageCode.EVIDENCE_SHARED_ACROSS_OPERATIONS)
        if len({by_claim[c][2] for c in linked}) > 1:
            return _refuse(CoverageCode.EVIDENCE_SHARED_ACROSS_CAPABILITIES)

    rows: list[MatrixRow] = []
    for cid, _scope, cap, op in cl:
        passing = tuple(sorted(
            eid for c, eid in seen_links if c == cid and by_ev[eid][4] is EvidenceVerdict.PASS
        ))
        rows.append(MatrixRow(cid, cap, op, passing))
    uncovered = tuple(r.claim_id for r in rows if not r.evidence_ids)
    digest = hashlib.sha256(stable_key(*(
        stable_key(r.claim_id, r.capability, r.operation, *r.evidence_ids) for r in rows
    )).encode("ascii")).hexdigest()
    if uncovered:
        return MatrixResult(CoverageStatus.INCOMPLETE, CoverageCode.UNCOVERED_CLAIM,
                            tuple(rows), uncovered, digest)
    return MatrixResult(CoverageStatus.COMPLETE, CoverageCode.OK, tuple(rows), (), digest)


def capability_enabled(result: object, capability: object) -> bool:
    """True only for the EXACT capability of a covered claim in an accepted matrix.

    No parent/child, prefix or sibling inheritance; reserved capabilities are never enabled."""
    cap = clean_identity(capability)
    if type(result) is not MatrixResult or not result.accepted or not cap:
        return False
    if cap in RESERVED_CAPABILITIES:
        return False
    return any(r.capability == cap and r.evidence_ids for r in result.rows)
