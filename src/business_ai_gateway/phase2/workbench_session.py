"""Phase 2 sprint S8 E4 (R2-US-039..041): the workbench session facade. Offline, unwired, in-memory.

``WorkbenchSession`` only COMPOSES the finished E1-E3 functions over injected ledgers, stores and fakes
so the accountant, auditor and API-engineer flows run end to end offline. It adds no decision rule of
its own: every verdict (cards, original-number check, annotation, rerun fence, timeline applicability,
coverage, scope, CSRF, idempotency, operation boundary) comes from exactly one E1-E3 function, and
the facade only passes typed arguments through, supplies the CURRENT scope epoch from the injected
epoch source, and maps results:

* ``RerunGate`` (design decision 12): ``decide_rerun`` asks the facade's gate, which calls E1
  ``request_rerun`` and maps its refusals ``NO_NEW_EVIDENCE`` / ``RERUN_TARGET_STALE`` /
  ``RERUN_TARGET_UNKNOWN`` / ``NOT_IN_SCOPE`` one-to-one to the gate verdicts. Any other refusal or any
  exception inside the gate is not a verdict: ``decide_rerun`` then answers ``INTERNAL_REFUSED``
  and records nothing. Paused-source / actor refusals are NOT modelled here (no injected fact exists).
* Any exception raised by a composed component or injected provider becomes a fixed
  ``SafeError(INTERNAL_REFUSED)`` with an id from the injected correlation source. It is never swallowed
  into a partial view: a timeline is returned only if it was built AND re-checked by ``render_guard``.
* E1 refusals carry the default correlation id; the facade re-wraps them with a fresh injected id.

Honest limits: providers (subjects, feeds, matrix, policy, evidence) and the reader are injected fakes;
E1 cards are keyed by tenant and comparison key, so company ownership of a comparison key is not
enforced by cards (the E2 builders enforce it from the subjects). Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Final

from .coverage_view import (
    CoveragePanel,
    ScopedDiffView,
    ScopedEvidenceView,
    build_coverage_panel,
    build_scoped_diff,
    build_scoped_evidence,
    render_guard_coverage,
)
from .jobs_api import (
    ApiContext,
    ApiDecision,
    RerunRequest,
    decide_enqueue,
    decide_rerun,
    read_job,
    read_result,
)
from .safe_errors import RenderedError, new_safe_error, render_safe_error
from .timeline_view import ScopeAuthority, TimelineView, build_timeline, render_guard
from .workbench_review import (
    DiscrepancyCard,
    RerunOutcome,
    ReviewLog,
    build_cards,
    request_override,
    request_rerun,
    verify_original,
)
from .workbench_types import (
    AUTHORITY,
    DEFAULT_CORRELATION_ID,
    ReasonCode,
    SafeError,
    ViewerScope,
    is_valid_safe_error,
    is_valid_scope,
)

__all__ = ["AUTHORITY", "WorkbenchSession"]

_STALE_SENTINEL: Final = -1  # an epoch no real scope has: unknown current epoch counts as stale
_GATE_CODES: Final = frozenset({
    ReasonCode.NO_NEW_EVIDENCE, ReasonCode.RERUN_TARGET_STALE, ReasonCode.RERUN_TARGET_UNKNOWN,
    ReasonCode.NOT_IN_SCOPE,
})


class _GateFailure(Exception):
    """A rerun refusal that is not a gate verdict; ``decide_rerun`` turns it into INTERNAL_REFUSED."""


class _FacadeRerunGate:
    """``RerunGate`` implementation: E1 ``request_rerun`` result -> gate verdict code (or ``None``)."""

    def __init__(self, session: WorkbenchSession) -> None:
        self._s = session

    def check(self, request: RerunRequest) -> ReasonCode | None:
        s = self._s
        result = request_rerun(
            s._ledger, s._store, s._review_log, request.scope, request.scope.tenant_id,
            request.comparison_key, request.previous_run_id, request.new_snapshot_id, s._reader,
            current_epoch=s._epoch(request.scope))
        if type(result) is RerunOutcome:
            return None
        if is_valid_safe_error(result) and result.reason_code in _GATE_CODES:
            return result.reason_code
        raise _GateFailure



class WorkbenchSession:
    """Composition root of the offline workbench; every public method returns a value or a ``SafeError``."""

    def __init__(self, *, ledger: object, store: object, review_log: ReviewLog, owners: object,
                 attestations: object, ctx: ApiContext, reader: Callable[..., object],
                 subjects: Callable[[], object], feeds: Callable[[], object],
                 matrix: Callable[[], object], policy: Callable[[], object],
                 evidence: Callable[[], object]) -> None:
        self._ledger, self._store, self._review_log = ledger, store, review_log
        self._owners, self._attestations, self._ctx = owners, attestations, ctx
        self._reader = reader
        self._subjects, self._feeds, self._matrix = subjects, feeds, matrix
        self._policy, self._evidence = policy, evidence
        self._authority = ScopeAuthority(lambda tenant, company: ctx.scopes.current_epoch(tenant, company))
        self._gate = _FacadeRerunGate(self)

    def __repr__(self) -> str:
        return "WorkbenchSession()"

    # ---------------------------------------------------------------- plumbing
    def _next_corr(self) -> str:
        try:
            value = self._ctx.correlation.next_id()
        except Exception:  # noqa: BLE001 - a broken id source degrades to the fixed default id
            return DEFAULT_CORRELATION_ID
        return value if type(value) is str else DEFAULT_CORRELATION_ID

    def _internal(self) -> SafeError:
        return new_safe_error(ReasonCode.INTERNAL_REFUSED, self._ctx.correlation)

    def _epoch(self, viewer: object) -> int:
        """The CURRENT epoch of the viewer's scope; unknown or unusable counts as stale."""
        try:
            if not is_valid_scope(viewer):
                return _STALE_SENTINEL
            value = self._ctx.scopes.current_epoch(viewer.tenant_id, viewer.company_id)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return _STALE_SENTINEL
        return value if type(value) is int else _STALE_SENTINEL

    def _rewrap(self, result: object) -> object:
        """Give an E1 refusal (default correlation id) a fresh injected id; everything else unchanged."""
        if is_valid_safe_error(result) and result.correlation_id == DEFAULT_CORRELATION_ID:  # type: ignore[attr-defined]
            return new_safe_error(result.reason_code, self._ctx.correlation)  # type: ignore[attr-defined]
        return result

    def _run(self, fn: Callable[[], object]) -> object:
        try:
            return self._rewrap(fn())
        except Exception:  # noqa: BLE001 - visible as INTERNAL_REFUSED, never swallowed into a view
            return self._internal()

    # ---------------------------------------------------------------- accountant (E1)
    def cards(self, viewer: ViewerScope, comparison_key: str, *, source_id: str, run_id: object = None,
              comparison: object = None) -> tuple[DiscrepancyCard, ...] | SafeError:
        return self._run(lambda: build_cards(  # type: ignore[return-value]
            self._ledger, getattr(viewer, "tenant_id", None), comparison_key, self._owners, viewer,
            source_id=source_id, run_id=run_id, comparison=comparison, current_epoch=self._epoch(viewer)))

    def verify_original(self, card: object) -> ReasonCode:
        try:
            return verify_original(card, self._ledger)
        except Exception:  # noqa: BLE001
            return ReasonCode.ORIGINAL_TAMPERED

    def annotate(self, viewer: ViewerScope, run_id: str, kind: object, text: object = "", *,
                 assignee: object = None) -> object:
        return self._run(lambda: self._review_log.add(
            self._ledger, viewer, getattr(viewer, "tenant_id", None), run_id, kind, text,
            assignee=assignee, current_epoch=self._epoch(viewer)))

    def annotations(self, viewer: ViewerScope, run_id: str) -> object:
        return self._run(lambda: self._review_log.entries(
            viewer, getattr(viewer, "tenant_id", None), run_id, current_epoch=self._epoch(viewer)))

    def override(self, *args: object, **kwargs: object) -> SafeError:
        return self._rewrap(request_override(*args, **kwargs))  # type: ignore[return-value]

    # ---------------------------------------------------------------- API engineer (E3) + safe rerun
    def rerun(self, request: object, session: object, csrf_token: object) -> ApiDecision | SafeError:
        return self._run(lambda: decide_rerun(  # type: ignore[return-value]
            self._ctx, request, session, csrf_token, self._gate))

    def enqueue(self, request: object, session: object, csrf_token: object,
                capture_allowed: object = False) -> ApiDecision | SafeError:
        return self._run(lambda: decide_enqueue(  # type: ignore[return-value]
            self._ctx, request, session, csrf_token, capture_allowed))

    def read_job(self, viewer: object, session: object, job_id: object) -> ApiDecision | SafeError:
        return self._run(lambda: read_job(self._ctx, viewer, session, job_id))  # type: ignore[return-value]

    def read_result(self, viewer: object, session: object, job_id: object) -> ApiDecision | SafeError:
        return self._run(lambda: read_result(self._ctx, viewer, session, job_id))  # type: ignore[return-value]

    def render_error(self, error: object) -> RenderedError:
        return render_safe_error(error)

    # ---------------------------------------------------------------- auditor (E2)
    def timeline(self, viewer: ViewerScope) -> TimelineView | SafeError:
        """A timeline only if it was built and then re-checked right before disclosure."""
        def build() -> object:
            clock = self._ctx.clock.now  # type: ignore[attr-defined]
            built = build_timeline(
                viewer, self._authority, self._ledger, self._attestations, self._subjects(),
                self._feeds(), self._matrix(), self._policy(), clock, correlation_id=self._next_corr())
            if type(built) is not TimelineView:
                return built
            return render_guard(built, self._authority, correlation_id=self._next_corr())
        return self._run(build)  # type: ignore[return-value]

    def coverage(self, viewer: ViewerScope) -> CoveragePanel | SafeError:
        return self._guarded_view(lambda: build_coverage_panel(
            viewer, self._authority, self._matrix(), correlation_id=self._next_corr()))  # type: ignore[return-value]

    def diff(self, viewer: ViewerScope) -> ScopedDiffView | SafeError:
        return self._guarded_view(lambda: build_scoped_diff(
            viewer, self._authority, self._ledger, self._subjects(),
            correlation_id=self._next_corr()))  # type: ignore[return-value]

    def evidence(self, viewer: ViewerScope) -> ScopedEvidenceView | SafeError:
        def build() -> object:
            claims, evidence, links = self._evidence()  # type: ignore[misc]
            return build_scoped_evidence(viewer, self._authority, claims, evidence, links,
                                         correlation_id=self._next_corr())
        return self._guarded_view(build)  # type: ignore[return-value]

    def _guarded_view(self, build: Callable[[], object]) -> object:
        def run() -> object:
            built = build()
            if is_valid_safe_error(built):
                return built
            return render_guard_coverage(built, self._authority, correlation_id=self._next_corr())
        return self._run(run)
