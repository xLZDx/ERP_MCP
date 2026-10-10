"""Phase 2 sprint S8 / E2 (R2-US-040, TC118-TC120): coverage panel and scoped diff / evidence views.

Offline, unwired, in-memory, synchronous, display-only. Every builder derives a frozen view from existing
immutable records (``MatrixResult``, claims/evidence/links, ``RunLedger`` runs) and applies scope BEFORE
anything is shown:

* Rows, claims, evidence and runs of another (tenant, company) are DROPPED. The only trace is the opaque
  boolean ``hidden_by_scope`` (no count, no id, no name, no digest or status that depends on foreign
  rows), so existence is not disclosed. A cross-company evidence link is not rendered even as an id.
* The panel state (COMPLETE / INCOMPLETE / REFUSED) is computed from the viewer's own rows only, so a
  foreign open claim cannot flip it.
* A stale scope epoch gives a ``SafeError`` and no view; ``render_guard_coverage`` re-checks the epoch
  immediately before disclosure, and every builder re-checks it once more right before returning.
* A panel is a display, never a gate: this module neither opens nor tests any capability, and it exposes
  no ``source_ref``. Original numbers are shown exactly as stored (exact ``Decimal``).

Public functions never raise: hostile input (wrong or lying types, forged ``object.__new__`` instances,
malformed elements inside tuples, recursive/huge values) gives a fixed ``SafeError`` and no caller text is
echoed. Authority is ``EVALUATION_ONLY``. KNOWN GAPS: the matrix digest is verified for integrity only
(it is not authenticity); scope epochs are an injected fact; the diff shows measure keys that
``RunRecord.differences`` holds (row-level detail is the E1 adapter's concern).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from ._identity import scope_key
from .comparison_snapshot import RunLedger, RunRecord, RunView, canonical_digest
from .timeline_view import (
    TimelineSubject,
    _check_epoch,
    _digest_ok,
    _guard,
    _Refuse,
    _text_ok,
)
from .validation_coverage import (
    Claim,
    ClaimScope,
    CoverageCode,
    CoverageStatus,
    Evidence,
    EvidenceVerdict,
    Link,
    MatrixResult,
    MatrixRow,
    _matrix_digest,
)
from .workbench_types import (
    AUTHORITY,
    DEFAULT_CORRELATION_ID,
    ReasonCode,
    SafeError,
    ViewerScope,
    is_valid_scope,
)

__all__ = [
    "BASIS", "CoveragePanel", "CoveredItem", "DiffItem", "EvidenceItem", "ScopedDiffView",
    "ScopedEvidenceView", "build_coverage_panel", "build_scoped_diff", "build_scoped_evidence",
    "render_guard_coverage",
]

BASIS: Final = ("offline in-memory display over scripted records; not a gate, opens no capability; "
                "EVALUATION_ONLY")
_MAX_EPOCH: Final = 2**63 - 1
_RUN_STATUS: Final = frozenset({"CURRENT", "LATEST_ATTEMPT", "SUPERSEDED"})


def _scope_fields_ok(obj: object) -> bool:
    return (_text_ok(obj.tenant_id) and _text_ok(obj.company_id)  # type: ignore[attr-defined]
            and type(obj.scope_epoch) is int and 0 <= obj.scope_epoch <= _MAX_EPOCH  # type: ignore[attr-defined]
            and type(obj.hidden_by_scope) is bool and _digest_ok(obj.digest)  # type: ignore[attr-defined]
            and obj.authority == AUTHORITY and obj.basis == BASIS)  # type: ignore[attr-defined]


def _text_tuple(value: object) -> bool:
    return type(value) is tuple and all(_text_ok(x) for x in value)


# ------------------------------------------------------------------ coverage panel
@dataclass(frozen=True, slots=True)
class CoveredItem:
    claim_id: str
    capability: str
    operation: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (not _text_ok(self.claim_id) or not _text_ok(self.capability) or not _text_ok(self.operation)
                or not _text_tuple(self.evidence_ids) or not self.evidence_ids):
            raise ValueError("COVERED_ITEM_INVALID")


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
                or not _scope_fields_ok(self)):
            raise ValueError("COVERAGE_PANEL_INVALID")

    @property
    def complete(self) -> bool:
        """Display-only: every claim of the viewer's company is covered by PASS evidence."""
        return self.status is CoverageStatus.COMPLETE and self.code is CoverageCode.OK


def _matrix_ok(matrix: object) -> MatrixResult:
    if (type(matrix) is not MatrixResult or type(matrix.status) is not CoverageStatus
            or type(matrix.code) is not CoverageCode or type(matrix.rows) is not tuple
            or any(type(r) is not MatrixRow for r in matrix.rows)
            or type(matrix.uncovered) is not tuple or type(matrix.non_pass) is not tuple
            or type(matrix.digest) is not str):
        raise _Refuse(ReasonCode.INPUT_INVALID)
    for r in matrix.rows:
        if (not all(type(x) is str for x in (r.claim_id, r.capability, r.operation))
                or type(r.scope) is not tuple or len(r.scope) != 2 or not all(type(x) is str for x in r.scope)
                or type(r.evidence_ids) is not tuple or type(r.non_pass_ids) is not tuple
                or not all(type(x) is str for x in r.evidence_ids + r.non_pass_ids)):
            raise _Refuse(ReasonCode.INPUT_INVALID)
    if matrix.status is not CoverageStatus.REFUSED and matrix.digest != _matrix_digest(matrix.rows):
        raise _Refuse(ReasonCode.INPUT_INVALID)  # tampered rows do not verify
    return matrix


def _viewer_and_epoch(viewer: object, authority: object) -> ViewerScope:
    if not is_valid_scope(viewer):
        raise _Refuse(ReasonCode.INPUT_INVALID)
    _check_epoch(viewer, authority)  # type: ignore[arg-type]
    return viewer  # type: ignore[return-value]


def build_coverage_panel(viewer: object, authority: object, matrix: object, *,
                         correlation_id: object = DEFAULT_CORRELATION_ID) -> CoveragePanel | SafeError:
    """Coverage of the viewer's own company: covered / uncovered / non-pass claims with fixed codes."""
    def run() -> CoveragePanel:
        v = _viewer_and_epoch(viewer, authority)
        m = _matrix_ok(matrix)
        vkey = scope_key(v.tenant_id, v.company_id)
        mine = [r for r in m.rows if r.scope == vkey]
        hidden = any(r.scope != vkey for r in m.rows)
        covered, uncovered, non_pass = [], [], []
        for r in sorted(mine, key=lambda x: x.claim_id):
            if r.non_pass_ids:
                non_pass.append(r.claim_id)
            if not r.evidence_ids:
                uncovered.append(r.claim_id)
            else:
                covered.append(CoveredItem(r.claim_id, r.capability, r.operation, tuple(sorted(r.evidence_ids))))
        if m.status is CoverageStatus.REFUSED:
            status, code = CoverageStatus.REFUSED, m.code
            covered, uncovered, non_pass = [], [], []
        elif non_pass:
            status, code = CoverageStatus.INCOMPLETE, CoverageCode.NON_PASS_LINK
        elif uncovered:
            status, code = CoverageStatus.INCOMPLETE, CoverageCode.UNCOVERED_CLAIM
        elif not mine:
            status, code = CoverageStatus.INCOMPLETE, CoverageCode.EMPTY_MATRIX
        else:
            status, code = CoverageStatus.COMPLETE, CoverageCode.OK
        digest = canonical_digest({
            "v": 1, "tenant": v.tenant_id, "company": v.company_id, "epoch": v.scope_epoch,
            "status": status.value, "code": code.value, "hidden": hidden,
            "covered": [[c.claim_id, c.capability, c.operation, list(c.evidence_ids)] for c in covered],
            "uncovered": uncovered, "non_pass": non_pass})
        panel = CoveragePanel(v.tenant_id, v.company_id, v.scope_epoch, status, code, tuple(covered),
                              tuple(uncovered), tuple(non_pass), hidden, digest)
        _check_epoch(v, authority)  # type: ignore[arg-type]  # re-check immediately before disclosure
        return panel

    return _guard(run, correlation_id)  # type: ignore[return-value]


# ------------------------------------------------------------------ scoped evidence
@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    verdict: EvidenceVerdict
    digest: str
    claim_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (not _text_ok(self.evidence_id) or type(self.verdict) is not EvidenceVerdict
                or not _digest_ok(self.digest) or not _text_tuple(self.claim_ids)):
            raise ValueError("EVIDENCE_ITEM_INVALID")


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
                or not _scope_fields_ok(self)):
            raise ValueError("SCOPED_EVIDENCE_INVALID")


def _typed_tuple(value: object, cls: type) -> tuple:
    if type(value) is not tuple or any(type(x) is not cls for x in value):
        raise _Refuse(ReasonCode.INPUT_INVALID)
    return value


def build_scoped_evidence(viewer: object, authority: object, claims: object, evidence: object, links: object,
                          *, correlation_id: object = DEFAULT_CORRELATION_ID) -> ScopedEvidenceView | SafeError:
    """Evidence (and its claim links) resolved inside the viewer's company only."""
    def run() -> ScopedEvidenceView:
        v = _viewer_and_epoch(viewer, authority)
        vkey = scope_key(v.tenant_id, v.company_id)
        claim_scope: dict[str, tuple[str, str] | None] = {}
        for c in _typed_tuple(claims, Claim):
            if type(c.scope) is not ClaimScope or not _text_ok(c.claim_id) or c.claim_id in claim_scope:
                raise _Refuse(ReasonCode.INPUT_INVALID)
            key = c.scope.key()
            if key is None:
                raise _Refuse(ReasonCode.INPUT_INVALID)
            claim_scope[c.claim_id] = key
        ev_rows: dict[str, Evidence] = {}
        ev_scope: dict[str, tuple[str, str]] = {}
        for e in _typed_tuple(evidence, Evidence):
            if (type(e.scope) is not ClaimScope or not _text_ok(e.evidence_id) or e.evidence_id in ev_rows
                    or not _digest_ok(e.digest) or type(e.verdict) is not EvidenceVerdict):
                raise _Refuse(ReasonCode.INPUT_INVALID)
            key = e.scope.key()
            if key is None:
                raise _Refuse(ReasonCode.INPUT_INVALID)
            ev_rows[e.evidence_id] = e
            ev_scope[e.evidence_id] = key
        hidden = any(k != vkey for k in claim_scope.values()) or any(k != vkey for k in ev_scope.values())
        linked: dict[str, set[str]] = {}
        for lk in _typed_tuple(links, Link):
            if not _text_ok(lk.claim_id) or not _text_ok(lk.evidence_id):
                raise _Refuse(ReasonCode.INPUT_INVALID)
            if lk.claim_id not in claim_scope or lk.evidence_id not in ev_scope:
                raise _Refuse(ReasonCode.INPUT_INVALID)
            if claim_scope[lk.claim_id] != vkey or ev_scope[lk.evidence_id] != vkey:
                hidden = True  # a cross-company link is never rendered, not even as an id
                continue
            linked.setdefault(lk.evidence_id, set()).add(lk.claim_id)
        items = tuple(
            EvidenceItem(eid, ev_rows[eid].verdict, ev_rows[eid].digest, tuple(sorted(linked.get(eid, ()))))
            for eid in sorted(ev_rows) if ev_scope[eid] == vkey)
        digest = canonical_digest({
            "v": 1, "tenant": v.tenant_id, "company": v.company_id, "epoch": v.scope_epoch, "hidden": hidden,
            "items": [[i.evidence_id, i.verdict.value, i.digest, list(i.claim_ids)] for i in items]})
        view = ScopedEvidenceView(v.tenant_id, v.company_id, v.scope_epoch, items, hidden, digest)
        _check_epoch(v, authority)  # type: ignore[arg-type]
        return view

    return _guard(run, correlation_id)  # type: ignore[return-value]


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
        if (not _text_ok(self.run_id) or not _text_ok(self.comparison_key) or not _text_ok(self.measure)
                or type(self.run_status) is not str or self.run_status not in _RUN_STATUS):
            raise ValueError("DIFF_ITEM_INVALID")


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
                or not _scope_fields_ok(self)):
            raise ValueError("SCOPED_DIFF_INVALID")


def _values(pairs: object) -> dict[str, Decimal]:
    if type(pairs) is not tuple:
        raise _Refuse(ReasonCode.INPUT_INVALID)
    out: dict[str, Decimal] = {}
    for pair in pairs:
        if type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str or type(pair[1]) is not Decimal:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        out[pair[0]] = pair[1]
    return out


def build_scoped_diff(viewer: object, authority: object, ledger: object, subjects: object, *,
                      correlation_id: object = DEFAULT_CORRELATION_ID) -> ScopedDiffView | SafeError:
    """Differing measures (exact stored numbers) of the viewer's own comparison keys; others are dropped."""
    def run() -> ScopedDiffView:
        v = _viewer_and_epoch(viewer, authority)
        if type(ledger) is not RunLedger:
            raise _Refuse(ReasonCode.INPUT_INVALID)
        vkey = scope_key(v.tenant_id, v.company_id)
        hidden = False
        seen: set[tuple[str, str, str]] = set()
        items: list[DiffItem] = []
        for sub in _typed_tuple(subjects, TimelineSubject):
            TimelineSubject(sub.tenant_id, sub.company_id, sub.comparison_key, sub.bindings)
            if scope_key(sub.tenant_id, sub.company_id) != vkey:
                hidden = True
                continue
            ident = (sub.tenant_id, sub.company_id, sub.comparison_key)
            if ident in seen:
                continue
            seen.add(ident)
            views = ledger.list_runs(sub.tenant_id, sub.comparison_key)
            if type(views) is not tuple:
                raise _Refuse(ReasonCode.INPUT_INVALID)
            for rv in views:
                if type(rv) is not RunView or type(rv.record) is not RunRecord:
                    raise _Refuse(ReasonCode.INPUT_INVALID)
                rec = rv.record
                native, gateway = _values(rec.native_values), _values(rec.gateway_values)
                if type(rec.differences) is not tuple:
                    raise _Refuse(ReasonCode.INPUT_INVALID)
                for measure in rec.differences:
                    items.append(DiffItem(rec.run_id, sub.comparison_key, measure, native.get(measure),
                                          gateway.get(measure), rv.status))
        items.sort(key=lambda i: (i.comparison_key, i.run_id, i.measure))
        digest = canonical_digest({
            "v": 1, "tenant": v.tenant_id, "company": v.company_id, "epoch": v.scope_epoch, "hidden": hidden,
            "items": [[i.run_id, i.comparison_key, i.measure, i.native, i.gateway, i.run_status] for i in items]})
        view = ScopedDiffView(v.tenant_id, v.company_id, v.scope_epoch, tuple(items), hidden, digest)
        _check_epoch(v, authority)  # type: ignore[arg-type]
        return view

    return _guard(run, correlation_id)  # type: ignore[return-value]


# ------------------------------------------------------------------ render guard
def render_guard_coverage(view: object, authority: object, *,
                          correlation_id: object = DEFAULT_CORRELATION_ID,
                          ) -> CoveragePanel | ScopedEvidenceView | ScopedDiffView | SafeError:
    """Re-verify the viewer's scope epoch right before a built view is disclosed (revoke-before-disclosure)."""
    def run() -> object:
        if type(view) not in (CoveragePanel, ScopedEvidenceView, ScopedDiffView):
            raise _Refuse(ReasonCode.INPUT_INVALID)
        viewer = ViewerScope(view.tenant_id, view.company_id, view.scope_epoch)  # type: ignore[attr-defined]
        if not _scope_fields_ok(view) or type(view.authority) is not str:  # type: ignore[attr-defined]
            raise _Refuse(ReasonCode.INPUT_INVALID)
        _check_epoch(viewer, authority)  # type: ignore[arg-type]
        return view

    return _guard(run, correlation_id)  # type: ignore[return-value]

