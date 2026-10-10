"""Phase 2 sprint S8 / E2 (R2-US-040, TC118-TC120): coverage panel and scoped diff / evidence views.

Offline, unwired, in-memory, synchronous, display-only. Every builder derives a frozen view from existing
immutable records (``MatrixResult``, claims/evidence/links, ``RunLedger`` runs) and applies scope BEFORE
anything is shown, with the one identity rule of ``timeline_view.scope_relation``:

* Rows, claims, evidence and runs of another (tenant, company) are DROPPED unread and unvalidated: a claim
  or subject is the viewer's only on an exact (``type(x) is str``, ``==``) tenant and company match, so a
  casefold variant is foreign. The only trace is the opaque boolean ``hidden_by_scope`` (no count, no id,
  no name, no digest or status that depends on foreign rows); it is set only for another company of the
  SAME tenant, so existence in another tenant is not disclosed. Foreign duplicates, dangling links and
  malformed rows can neither change the viewer's output nor make it fail. A link that is not wholly inside
  the viewer's scope is dropped (never rendered, not even as an id).
* The panel state (COMPLETE / INCOMPLETE / REFUSED) is computed from the viewer's own rows only, so a
  foreign open claim cannot flip it; a REFUSED matrix shows one fixed code (its global reason may depend
  on foreign data and is never passed on).
* A stale scope epoch gives a ``SafeError`` and no view; ``render_guard_coverage`` re-verifies the digest
  and re-checks the epoch immediately before disclosure, and every builder re-checks it once more right
  before returning. Each view recomputes its digest on construction, so tampered content does not verify.
* A panel is a display, never a gate: this module neither opens nor tests any capability, and it exposes
  no ``source_ref``. Original numbers are shown exactly as stored (exact ``Decimal``).

Public functions never raise: hostile input (wrong or lying types, forged ``object.__new__`` instances,
malformed elements inside tuples, recursive/huge values) gives a fixed ``SafeError`` and no caller text is
echoed; a fault of an injected provider (the ledger) is ``INTERNAL_REFUSED``. Authority is
``EVALUATION_ONLY``. KNOWN GAPS: the matrix digest is verified for integrity only (it is not
authenticity); matrix rows hold only normalised scope keys, so the panel matches them by ``scope_key``;
scope epochs are an injected fact; the diff shows measure keys that ``RunRecord.differences`` holds
(row-level detail is the E1 adapter's concern).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from .comparison_snapshot import RunLedger, RunView, canonical_digest
from .timeline_view import (
    OWN,
    SIBLING,
    Refuse,
    TimelineSubject,
    check_epoch,
    check_ownership_port,
    check_run_record,
    collect_own_subjects,
    digest_ok,
    guard,
    provider,
    provider_invalid,
    scope_relation,
    scoped_matrix,
    text_ok,
    viewer_and_epoch,
)
from .validation_coverage import (
    Claim,
    ClaimScope,
    CoverageCode,
    CoverageStatus,
    Evidence,
    EvidenceVerdict,
    Link,
)
from .workbench_types import (
    AUTHORITY,
    DEFAULT_CORRELATION_ID,
    OwnershipPort,
    ReasonCode,
    SafeError,
    ViewerScope,
)

__all__ = [
    "BASIS", "REFUSED_CODE", "CoveragePanel", "CoveredItem", "DiffItem", "EvidenceItem", "Refuse",
    "ScopedDiffView", "ScopedEvidenceView", "build_coverage_panel", "build_scoped_diff",
    "build_scoped_evidence", "render_guard_coverage",
]

BASIS: Final = ("offline in-memory display over scripted records; not a gate, opens no capability; "
                "EVALUATION_ONLY")
# The code shown for a REFUSED matrix: fixed, because the matrix's own code may reflect foreign rows.
REFUSED_CODE: Final = CoverageCode.CLAIM_INVALID
_MAX_EPOCH: Final = 2**63 - 1
_RUN_STATUS: Final = frozenset({"CURRENT", "LATEST_ATTEMPT", "SUPERSEDED"})


def _scope_fields_ok(obj: object) -> bool:
    return (text_ok(obj.tenant_id) and text_ok(obj.company_id)  # type: ignore[attr-defined]
            and type(obj.scope_epoch) is int and 0 <= obj.scope_epoch <= _MAX_EPOCH  # type: ignore[attr-defined]
            and type(obj.hidden_by_scope) is bool and digest_ok(obj.digest)  # type: ignore[attr-defined]
            and type(obj.authority) is str and obj.authority == AUTHORITY  # type: ignore[attr-defined]
            and type(obj.basis) is str and obj.basis == BASIS)  # type: ignore[attr-defined]


def _text_tuple(value: object) -> bool:
    return type(value) is tuple and all(text_ok(x) for x in value)


def _digest_matches(view: object, make: Callable[..., str], *fields: str) -> bool:
    try:
        return view.digest == make(*(getattr(view, f) for f in fields))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - content that cannot be hashed is not a valid view
        return False


# ------------------------------------------------------------------ coverage panel
@dataclass(frozen=True, slots=True)
class CoveredItem:
    claim_id: str
    capability: str
    operation: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (not text_ok(self.claim_id) or not text_ok(self.capability) or not text_ok(self.operation)
                or not _text_tuple(self.evidence_ids) or not self.evidence_ids):
            raise ValueError("COVERED_ITEM_INVALID")


def _panel_digest(tenant: str, company: str, epoch: int, status: CoverageStatus, code: CoverageCode,
                  hidden: bool, covered: tuple[CoveredItem, ...], uncovered: tuple[str, ...],
                  non_pass: tuple[str, ...]) -> str:
    return canonical_digest({
        "v": 1, "tenant": tenant, "company": company, "epoch": epoch,
        "status": status.value, "code": code.value, "hidden": hidden,
        "covered": [[c.claim_id, c.capability, c.operation, list(c.evidence_ids)] for c in covered],
        "uncovered": list(uncovered), "non_pass": list(non_pass)})


@dataclass(frozen=True, slots=True)
class CoveragePanel:
    tenant_id: str
    company_id: str
    scope_epoch: int
    status: CoverageStatus
    code: CoverageCode
    covered: tuple[CoveredItem, ...]
    uncovered: tuple[str, ...]
    non_pass: tuple[str, ...]
    hidden_by_scope: bool
    digest: str
    authority: str = AUTHORITY
    basis: str = BASIS

    def __post_init__(self) -> None:
        if (type(self.status) is not CoverageStatus or type(self.code) is not CoverageCode
                or type(self.covered) is not tuple or any(type(c) is not CoveredItem for c in self.covered)
                or not _text_tuple(self.uncovered) or not _text_tuple(self.non_pass)
                or not _scope_fields_ok(self)
                or not _digest_matches(self, _panel_digest, "tenant_id", "company_id", "scope_epoch", "status",
                                       "code", "hidden_by_scope", "covered", "uncovered", "non_pass")):
            raise ValueError("COVERAGE_PANEL_INVALID")

    @property
    def complete(self) -> bool:
        """Display-only: every claim of the viewer's company is covered by PASS evidence."""
        return self.status is CoverageStatus.COMPLETE and self.code is CoverageCode.OK


def build_coverage_panel(viewer: object, authority: object, matrix: object, *, ownership: OwnershipPort,
                         correlation_id: object = DEFAULT_CORRELATION_ID) -> CoveragePanel | SafeError:
    """Coverage of the viewer's own company: covered / uncovered / non-pass claims with fixed codes."""
    def run() -> CoveragePanel:
        v = viewer_and_epoch(viewer, authority)
        check_ownership_port(ownership)  # matrix rows carry no ledger key: nothing further to prove here
        sm = scoped_matrix(matrix, v)
        covered: list[CoveredItem] = []
        uncovered: list[str] = []
        non_pass: list[str] = []
        for r in sorted(sm.rows, key=lambda x: x.claim_id):
            if r.non_pass_ids:
                non_pass.append(r.claim_id)
            if not r.evidence_ids:
                uncovered.append(r.claim_id)
            else:
                covered.append(CoveredItem(r.claim_id, r.capability, r.operation, tuple(sorted(r.evidence_ids))))
        if sm.status is CoverageStatus.REFUSED:
            status, code = CoverageStatus.REFUSED, REFUSED_CODE
            covered, uncovered, non_pass = [], [], []
        elif non_pass:
            status, code = CoverageStatus.INCOMPLETE, CoverageCode.NON_PASS_LINK
        elif uncovered:
            status, code = CoverageStatus.INCOMPLETE, CoverageCode.UNCOVERED_CLAIM
        elif not sm.rows:
            status, code = CoverageStatus.INCOMPLETE, CoverageCode.EMPTY_MATRIX
        else:
            status, code = CoverageStatus.COMPLETE, CoverageCode.OK
        digest = _panel_digest(v.tenant_id, v.company_id, v.scope_epoch, status, code, sm.hidden,
                               tuple(covered), tuple(uncovered), tuple(non_pass))
        panel = CoveragePanel(v.tenant_id, v.company_id, v.scope_epoch, status, code, tuple(covered),
                              tuple(uncovered), tuple(non_pass), sm.hidden, digest)
        check_epoch(v, authority)  # type: ignore[arg-type]  # re-check immediately before disclosure
        return panel

    return guard(run, correlation_id)  # type: ignore[return-value]


# ------------------------------------------------------------------ scoped evidence
@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    verdict: EvidenceVerdict
    digest: str
    claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (not text_ok(self.evidence_id) or type(self.verdict) is not EvidenceVerdict
                or not digest_ok(self.digest) or not _text_tuple(self.claim_ids)):
            raise ValueError("EVIDENCE_ITEM_INVALID")


def _evidence_digest(tenant: str, company: str, epoch: int, hidden: bool, items: tuple[EvidenceItem, ...]) -> str:
    return canonical_digest({
        "v": 1, "tenant": tenant, "company": company, "epoch": epoch, "hidden": hidden,
        "items": [[i.evidence_id, i.verdict.value, i.digest, list(i.claim_ids)] for i in items]})


@dataclass(frozen=True, slots=True)
class ScopedEvidenceView:
    tenant_id: str
    company_id: str
    scope_epoch: int
    items: tuple[EvidenceItem, ...]
    hidden_by_scope: bool
    digest: str
    authority: str = AUTHORITY
    basis: str = BASIS

    def __post_init__(self) -> None:
        if (type(self.items) is not tuple or any(type(i) is not EvidenceItem for i in self.items)
                or not _scope_fields_ok(self)
                or not _digest_matches(self, _evidence_digest, "tenant_id", "company_id", "scope_epoch",
                                       "hidden_by_scope", "items")):
            raise ValueError("SCOPED_EVIDENCE_INVALID")


def _typed_tuple(value: object, cls: type) -> tuple:
    if type(value) is not tuple or any(type(x) is not cls for x in value):
        raise Refuse(ReasonCode.INPUT_INVALID)
    return value


def _row_relation(viewer: ViewerScope, row: Claim | Evidence) -> str:
    scope = row.scope
    if type(scope) is not ClaimScope:
        raise Refuse(ReasonCode.INPUT_INVALID)
    return scope_relation(viewer, scope.tenant_id, scope.company_id)


def build_scoped_evidence(viewer: object, authority: object, claims: object, evidence: object, links: object,
                          *, ownership: OwnershipPort, correlation_id: object = DEFAULT_CORRELATION_ID) -> ScopedEvidenceView | SafeError:
    """Evidence (and its claim links) resolved inside the viewer's company only."""
    def run() -> ScopedEvidenceView:
        v = viewer_and_epoch(viewer, authority)
        check_ownership_port(ownership)  # claims/evidence carry no ledger key: nothing further to prove here
        hidden = False
        own_claims: set[str] = set()
        for c in _typed_tuple(claims, Claim):
            relation = _row_relation(v, c)
            if relation != OWN:
                hidden = hidden or relation == SIBLING  # dropped unread and unvalidated
                continue
            if not text_ok(c.claim_id) or c.claim_id in own_claims or c.scope.key() is None:
                raise Refuse(ReasonCode.INPUT_INVALID)
            own_claims.add(c.claim_id)
        ev_rows: dict[str, Evidence] = {}
        for e in _typed_tuple(evidence, Evidence):
            relation = _row_relation(v, e)
            if relation != OWN:
                hidden = hidden or relation == SIBLING
                continue
            if (not text_ok(e.evidence_id) or e.evidence_id in ev_rows or not digest_ok(e.digest)
                    or type(e.verdict) is not EvidenceVerdict or e.scope.key() is None):
                raise Refuse(ReasonCode.INPUT_INVALID)
            ev_rows[e.evidence_id] = e
        linked: dict[str, set[str]] = {}
        for lk in _typed_tuple(links, Link):
            cid, eid = lk.claim_id, lk.evidence_id
            if type(cid) is str and type(eid) is str and cid in own_claims and eid in ev_rows:
                linked.setdefault(eid, set()).add(cid)  # anything not wholly inside the scope is dropped
        items = tuple(
            EvidenceItem(eid, ev_rows[eid].verdict, ev_rows[eid].digest, tuple(sorted(linked.get(eid, ()))))
            for eid in sorted(ev_rows))
        view = ScopedEvidenceView(v.tenant_id, v.company_id, v.scope_epoch, items, hidden,
                                  _evidence_digest(v.tenant_id, v.company_id, v.scope_epoch, hidden, items))
        check_epoch(v, authority)  # type: ignore[arg-type]
        return view

    return guard(run, correlation_id)  # type: ignore[return-value]


# ------------------------------------------------------------------ scoped diff
@dataclass(frozen=True, slots=True)
class DiffItem:
    run_id: str
    comparison_key: str
    measure: str
    native: Decimal | None  # None: the side holds no value for this measure
    gateway: Decimal | None
    run_status: str

    def __post_init__(self) -> None:
        for number in (self.native, self.gateway):
            if number is not None and (type(number) is not Decimal or not number.is_finite()):
                raise ValueError("DIFF_ITEM_INVALID")
        if (not text_ok(self.run_id) or not text_ok(self.comparison_key) or not text_ok(self.measure)
                or type(self.run_status) is not str or self.run_status not in _RUN_STATUS):
            raise ValueError("DIFF_ITEM_INVALID")


def _diff_digest(tenant: str, company: str, epoch: int, hidden: bool, items: tuple[DiffItem, ...]) -> str:
    return canonical_digest({
        "v": 1, "tenant": tenant, "company": company, "epoch": epoch, "hidden": hidden,
        "items": [[i.run_id, i.comparison_key, i.measure, i.native, i.gateway, i.run_status] for i in items]})


@dataclass(frozen=True, slots=True)
class ScopedDiffView:
    tenant_id: str
    company_id: str
    scope_epoch: int
    items: tuple[DiffItem, ...]
    hidden_by_scope: bool
    digest: str
    authority: str = AUTHORITY
    basis: str = BASIS

    def __post_init__(self) -> None:
        if (type(self.items) is not tuple or any(type(i) is not DiffItem for i in self.items)
                or not _scope_fields_ok(self)
                or not _digest_matches(self, _diff_digest, "tenant_id", "company_id", "scope_epoch",
                                       "hidden_by_scope", "items")):
            raise ValueError("SCOPED_DIFF_INVALID")


def _values(pairs: object) -> dict[str, Decimal]:
    if type(pairs) is not tuple:
        provider_invalid()
    out: dict[str, Decimal] = {}
    for pair in pairs:  # type: ignore[attr-defined]
        if type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str or type(pair[1]) is not Decimal:
            provider_invalid()
        out[pair[0]] = pair[1]
    return out


def _diff_items(ledger: RunLedger, sub: TimelineSubject) -> list[DiffItem]:
    views = ledger.list_runs(sub.tenant_id, sub.comparison_key)
    if type(views) is not tuple:
        provider_invalid()
    items: list[DiffItem] = []
    for rv in views:  # every record is verified BEFORE any number is read
        if type(rv) is not RunView:
            provider_invalid()
        check_run_record(rv.record, sub.tenant_id, sub.comparison_key)
    for rv in views:
        rec = rv.record
        native, gateway = _values(rec.native_values), _values(rec.gateway_values)
        if type(rec.differences) is not tuple:
            provider_invalid()
        items.extend(DiffItem(rec.run_id, sub.comparison_key, measure, native.get(measure),
                              gateway.get(measure), rv.status) for measure in rec.differences)
    return items


def build_scoped_diff(viewer: object, authority: object, ledger: object, subjects: object, *,
                      ownership: OwnershipPort, correlation_id: object = DEFAULT_CORRELATION_ID) -> ScopedDiffView | SafeError:
    """Differing measures (exact stored numbers) of the viewer's own comparison keys; others are dropped."""
    def run() -> ScopedDiffView:
        v = viewer_and_epoch(viewer, authority)
        if type(ledger) is not RunLedger:
            raise Refuse(ReasonCode.INPUT_INVALID)
        own_subjects, hidden = collect_own_subjects(v, _typed_tuple(subjects, TimelineSubject), ownership)
        items: list[DiffItem] = []
        for sub in own_subjects:
            items.extend(provider(_diff_items, ledger, sub))  # type: ignore[arg-type]
        items.sort(key=lambda i: (i.comparison_key, i.run_id, i.measure))
        done = tuple(items)
        view = ScopedDiffView(v.tenant_id, v.company_id, v.scope_epoch, done, hidden,
                              _diff_digest(v.tenant_id, v.company_id, v.scope_epoch, hidden, done))
        check_epoch(v, authority)  # type: ignore[arg-type]
        return view

    return guard(run, correlation_id)  # type: ignore[return-value]


# ------------------------------------------------------------------ render guard
def render_guard_coverage(view: object, authority: object, *,
                          correlation_id: object = DEFAULT_CORRELATION_ID,
                          ) -> CoveragePanel | ScopedEvidenceView | ScopedDiffView | SafeError:
    """Re-verify the digest and the viewer's scope epoch right before a built view is disclosed."""
    def run() -> object:
        if type(view) is CoveragePanel:
            CoveragePanel(view.tenant_id, view.company_id, view.scope_epoch, view.status, view.code,
                          view.covered, view.uncovered, view.non_pass, view.hidden_by_scope, view.digest,
                          view.authority, view.basis)
        elif type(view) is ScopedEvidenceView:
            ScopedEvidenceView(view.tenant_id, view.company_id, view.scope_epoch, view.items,
                               view.hidden_by_scope, view.digest, view.authority, view.basis)
        elif type(view) is ScopedDiffView:
            ScopedDiffView(view.tenant_id, view.company_id, view.scope_epoch, view.items,
                           view.hidden_by_scope, view.digest, view.authority, view.basis)
        else:
            raise Refuse(ReasonCode.INPUT_INVALID)
        viewer = ViewerScope(view.tenant_id, view.company_id, view.scope_epoch)
        check_epoch(viewer, authority)  # type: ignore[arg-type]
        return view

    return guard(run, correlation_id)  # type: ignore[return-value]
