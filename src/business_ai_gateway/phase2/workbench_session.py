"""Phase 2 sprint S8 E4 (R2-US-039..041): the workbench session facade. Offline, unwired, in-memory.

``WorkbenchSession`` only COMPOSES the finished E1-E3 functions over injected ledgers, stores and fakes
so the accountant, auditor and API-engineer flows run end to end offline. It adds no decision rule of
its own: every verdict (cards, original-number check, annotation, rerun fence, timeline applicability,
coverage, scope, CSRF, idempotency, operation boundary) comes from exactly one E1-E3 function or injected
port, and the facade only passes typed arguments through and maps results.

Acting identity (security F2): the facade never trusts a self-asserted ``ViewerScope``. Every public method
takes the acting ``SessionRecord`` and, before anything else is read, asks the injected
``EntitlementPort`` whether ``(session tenant, session actor, viewer company)`` is entitled. A non-member,
an unknown company and a viewer of another tenant all get the SAME ``NOT_IN_SCOPE`` refusal, and the scope
epoch is not read until entitlement passed (so it cannot be probed). The methods that go through
``jobs_api`` (``rerun``, ``enqueue``, ``read_job``, ``read_result``) get their session / CSRF /
entitlement / epoch / ownership decisions from that module unchanged. ``annotate`` has no ``jobs_api``
decision function; it uses entitlement, session expiry, the injected ``CsrfGuard`` and the E1 epoch
and ownership gate, and records the session's actor (documented gap: no idempotency key, so a repeated
annotate request appends a second entry).

Other mappings:

* ``RerunGate``: ``check`` calls E1 ``check_rerun`` (pure) and keeps the returned ``RerunPlan`` in a bounded
  per-request table; ``commit`` hands that plan to E1 ``commit_rerun`` and returns
  ``RerunCommit(new run id, CREATED)`` or the refusal code. Refusal codes outside the accepted gate set
  become ``INTERNAL_REFUSED``.
* Any exception raised by a composed component or injected provider becomes a fixed
  ``SafeError(INTERNAL_REFUSED)`` with an id from the injected correlation source, and an event (class
  name only plus the correlation id) goes to the injected ``EventSink``. It is never swallowed into a
  partial view: a timeline is returned only if it was built AND re-checked by ``render_guard``.
* E1 refusals carry the default correlation id; the facade re-wraps them with a fresh injected id.
* ``cards`` returns ``CardsResult`` so 'no run' / PASS / FAIL / INCONCLUSIVE stay distinguishable.

Honest limits: providers (subjects, feeds, matrix, policy, evidence) and the reader are injected fakes;
the E2 builders enforce company scope from the subjects/matrix they are given. Authority is
``EVALUATION_ONLY``.
"""
from __future__ import annotations

import re
import threading
from collections import OrderedDict
from collections.abc import Callable
from datetime import datetime
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
    ApiEvent,
    ComponentName,
    EventKind,
    RerunCommit,
    RerunRequest,
    RunState,
    SessionRecord,
    decide_enqueue,
    decide_rerun,
    read_job,
    read_result,
)
from .safe_errors import RenderedError, new_safe_error, render_safe_error
from .timeline_view import ScopeAuthority, TimelineView, build_timeline, render_guard
from .workbench_review import (
    CardsResult,
    RerunOutcome,
    RerunPlan,
    ReviewLog,
    build_cards,
    check_rerun,
    commit_rerun,
    request_override,
    verify_original,
)
from .workbench_types import (
    AUTHORITY,
    DEFAULT_CORRELATION_ID,
    ReasonCode,
    SafeError,
    ViewerScope,
    correlation_ok,
    is_valid_safe_error,
    is_valid_scope,
)

__all__ = ["AUTHORITY", "WorkbenchSession"]

_R = ReasonCode
# Gate verdicts ``decide_rerun`` accepts from a ``RerunGate``; anything else is an internal refusal.
_GATE_CODES: Final = frozenset({
    _R.NO_NEW_EVIDENCE, _R.RERUN_TARGET_STALE, _R.RERUN_TARGET_UNKNOWN, _R.NOT_IN_SCOPE, _R.SOURCE_PAUSED,
    _R.OPERATION_DENIED, _R.NOT_FOUND, _R.RATE_LIMITED, _R.SCOPE_EPOCH_STALE, _R.DEPENDENCY_FAILED,
    _R.INTERNAL_REFUSED,
})
_MAX_PLANS: Final = 1024
_CLASS_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


class _FacadeRerunGate:
    """``RerunGate`` implementation over E1 ``check_rerun`` / ``commit_rerun`` (the plan lives between them)."""

    def __init__(self, session: WorkbenchSession) -> None:
        self._s = session
        self._lock = threading.Lock()
        self._plans: OrderedDict[tuple[object, ...], RerunPlan] = OrderedDict()

    @staticmethod
    def _key(request: RerunRequest) -> tuple[object, ...]:
        return (request.scope, request.actor_id, request.comparison_key, request.previous_run_id,
                request.new_snapshot_id, request.idempotency_key)

    @staticmethod
    def _code(result: object) -> ReasonCode:
        if is_valid_safe_error(result) and result.reason_code in _GATE_CODES:  # type: ignore[attr-defined]
            return result.reason_code  # type: ignore[attr-defined,no-any-return]
        return _R.INTERNAL_REFUSED

    def _plan_for(self, request: RerunRequest) -> RerunPlan | SafeError:
        s = self._s
        return check_rerun(
            s._ledger, s._store, s._review_log, request.scope, request.scope.tenant_id,
            request.comparison_key, request.previous_run_id, request.new_snapshot_id,
            ownership=s._ctx.ownership, current_epoch=s._epoch_reader(request.scope))

    def check(self, request: RerunRequest) -> ReasonCode | None:
        plan = self._plan_for(request)
        if type(plan) is not RerunPlan:
            return self._code(plan)
        with self._lock:
            self._plans[self._key(request)] = plan
            self._plans.move_to_end(self._key(request))
            while len(self._plans) > _MAX_PLANS:
                self._plans.popitem(last=False)
        return None

    def commit(self, request: RerunRequest) -> RerunCommit | ReasonCode:
        s = self._s
        with self._lock:
            plan = self._plans.pop(self._key(request), None)  # always cleaned up, whatever happens next
        if plan is None:  # evicted from the bounded table: derive it again, never act without a plan
            fresh = self._plan_for(request)
            if type(fresh) is not RerunPlan:
                return self._code(fresh)
            plan = fresh
        result = commit_rerun(
            s._ledger, s._store, s._review_log, request.scope, plan, s._reader, actor_id=request.actor_id,
            ownership=s._ctx.ownership, current_epoch=s._epoch_reader(request.scope))
        if type(result) is RerunOutcome:
            return RerunCommit(result.new_run_id, RunState.CREATED)
        return self._code(result)

    def pending(self) -> int:
        with self._lock:
            return len(self._plans)


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
        return value if correlation_ok(value) else DEFAULT_CORRELATION_ID

    def _emit(self, kind: EventKind, component: ComponentName, corr: str, error: BaseException | None) -> None:
        """Operational event to the injected sink: class name only, never a message. Never raises."""
        try:
            sink = self._ctx.events
            if sink is None:
                return
            name = type(error).__name__ if error is not None else ""
            if name and _CLASS_NAME.fullmatch(name) is None:
                name = "Exception"
            sink.emit(ApiEvent(kind, component, name, corr if correlation_ok(corr) else DEFAULT_CORRELATION_ID))
        except Exception:  # noqa: BLE001, S110 - observability must never break a decision
            pass

    def _refusal(self, code: ReasonCode) -> SafeError:
        return new_safe_error(code, self._ctx.correlation)

    def _internal(self, error: BaseException | None = None) -> SafeError:
        result = self._refusal(_R.INTERNAL_REFUSED)
        self._emit(EventKind.UNEXPECTED_EXCEPTION, ComponentName.UNEXPECTED, result.correlation_id, error)
        return result

    def _epoch_reader(self, viewer: ViewerScope) -> Callable[[], object]:
        """A zero-argument callable reading the LIVE epoch of the viewer's scope (never a cached value)."""
        scopes, tenant, company = self._ctx.scopes, viewer.tenant_id, viewer.company_id
        return lambda: scopes.current_epoch(tenant, company)

    def _rewrap(self, result: object) -> object:
        """Fresh injected id for an E1 refusal that carries the default id; INTERNAL_REFUSED is reported."""
        if is_valid_safe_error(result) and result.correlation_id == DEFAULT_CORRELATION_ID:  # type: ignore[attr-defined]
            result = new_safe_error(result.reason_code, self._ctx.correlation)  # type: ignore[attr-defined]
        if is_valid_safe_error(result) and result.reason_code is _R.INTERNAL_REFUSED:  # type: ignore[attr-defined]
            self._emit(EventKind.UNEXPECTED_EXCEPTION, ComponentName.UNEXPECTED,
                       result.correlation_id, None)  # type: ignore[attr-defined]
        return result

    def _run(self, fn: Callable[[], object]) -> object:
        try:
            return self._rewrap(fn())
        except Exception as exc:  # noqa: BLE001 - visible as INTERNAL_REFUSED, never swallowed into a view
            return self._internal(exc)

    def _admit(self, session: object, viewer: object, token: object = None, *,
               mutation: bool = False) -> SafeError | None:
        """Who is asking: session shape -> entitlement FIRST -> session expiry -> CSRF (mutations only).

        ``None`` means admitted. Non-member, unknown company, foreign tenant and an unusable viewer are all
        ``NOT_IN_SCOPE``; the scope epoch is not read here (nor before this passes).
        """
        try:
            if type(session) is not SessionRecord:
                return self._refusal(_R.SESSION_INVALID)
            tenant, actor, expires = session.tenant_id, session.actor_id, session.expires_at
            if (type(tenant) is not str or type(actor) is not str or not tenant or not actor
                    or type(expires) is not datetime or expires.utcoffset() is None):
                return self._refusal(_R.SESSION_INVALID)
        except Exception:  # noqa: BLE001 - forged instance
            return self._refusal(_R.SESSION_INVALID)
        if not is_valid_scope(viewer) or viewer.tenant_id != tenant:  # type: ignore[attr-defined]
            return self._refusal(_R.NOT_IN_SCOPE)
        corr = self._next_corr()
        try:
            entitled = self._ctx.entitlements.entitled(tenant, actor, viewer.company_id)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self._emit(EventKind.COMPONENT_EXCEPTION, ComponentName.ENTITLEMENTS, corr, exc)
            return self._refusal(_R.DEPENDENCY_FAILED)
        if entitled is not True:
            if type(entitled) is not bool:
                self._emit(EventKind.COMPONENT_OUTPUT_INVALID, ComponentName.ENTITLEMENTS, corr, None)
            return self._refusal(_R.NOT_IN_SCOPE)
        try:
            now = self._ctx.clock.now()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self._emit(EventKind.COMPONENT_EXCEPTION, ComponentName.CLOCK, corr, exc)
            return self._refusal(_R.DEPENDENCY_FAILED)
        if type(now) is not datetime or now.utcoffset() is None:
            self._emit(EventKind.COMPONENT_OUTPUT_INVALID, ComponentName.CLOCK, corr, None)
            return self._refusal(_R.DEPENDENCY_FAILED)
        if now >= expires:
            return self._refusal(_R.SESSION_INVALID)
        if mutation and not self._ctx.csrf.check(session, token):
            return self._refusal(_R.CSRF_REJECTED)
        return None

    # ---------------------------------------------------------------- accountant (E1)
    def cards(self, session: SessionRecord, viewer: ViewerScope, comparison_key: str, *, source_id: str,
              run_id: object = None, comparison: object = None) -> CardsResult | SafeError:
        refused = self._admit(session, viewer)
        if refused is not None:
            return refused
        return self._run(lambda: build_cards(  # type: ignore[return-value]
            self._ledger, viewer.tenant_id, comparison_key, self._owners, viewer, source_id=source_id,
            ownership=self._ctx.ownership, current_epoch=self._epoch_reader(viewer), run_id=run_id,
            comparison=comparison))

    def verify_original(self, session: SessionRecord, viewer: ViewerScope, card: object) -> ReasonCode:
        refused = self._admit(session, viewer)
        if refused is not None:
            return refused.reason_code
        try:
            return verify_original(card, self._ledger, viewer, ownership=self._ctx.ownership,
                                   current_epoch=self._epoch_reader(viewer))
        except Exception as exc:  # noqa: BLE001
            self._internal(exc)
            return _R.INTERNAL_REFUSED

    def annotate(self, session: SessionRecord, viewer: ViewerScope, csrf_token: object, run_id: str,
                 kind: object, text: object = "", *, assignee: object = None) -> object:
        refused = self._admit(session, viewer, csrf_token, mutation=True)
        if refused is not None:
            return refused
        return self._run(lambda: self._review_log.add(
            self._ledger, viewer, viewer.tenant_id, run_id, kind, text, actor_id=session.actor_id,
            ownership=self._ctx.ownership, current_epoch=self._epoch_reader(viewer), assignee=assignee))

    def annotations(self, session: SessionRecord, viewer: ViewerScope, run_id: str) -> object:
        refused = self._admit(session, viewer)
        if refused is not None:
            return refused
        return self._run(lambda: self._review_log.entries(
            viewer, viewer.tenant_id, run_id, ownership=self._ctx.ownership,
            current_epoch=self._epoch_reader(viewer)))

    def override(self, *args: object, **kwargs: object) -> SafeError:
        return self._rewrap(request_override(*args, **kwargs))  # type: ignore[return-value]

    # ---------------------------------------------------------------- API engineer (E3) + safe rerun
    def rerun(self, request: object, session: object, csrf_token: object) -> ApiDecision | SafeError:
        return self._run(lambda: decide_rerun(  # type: ignore[return-value]
            self._ctx, request, session, csrf_token, self._gate))

    def enqueue(self, request: object, session: object, csrf_token: object) -> ApiDecision | SafeError:
        return self._run(lambda: decide_enqueue(  # type: ignore[return-value]
            self._ctx, request, session, csrf_token))

    def read_job(self, viewer: object, session: object, job_id: object) -> ApiDecision | SafeError:
        return self._run(lambda: read_job(self._ctx, viewer, session, job_id))  # type: ignore[return-value]

    def read_result(self, viewer: object, session: object, job_id: object) -> ApiDecision | SafeError:
        return self._run(lambda: read_result(self._ctx, viewer, session, job_id))  # type: ignore[return-value]

    def render_error(self, error: object) -> RenderedError:
        return render_safe_error(error)

    # ---------------------------------------------------------------- auditor (E2)
    def timeline(self, session: SessionRecord, viewer: ViewerScope) -> TimelineView | SafeError:
        """A timeline only if it was built and then re-checked right before disclosure."""
        refused = self._admit(session, viewer)
        if refused is not None:
            return refused

        def build() -> object:
            clock = self._ctx.clock.now  # type: ignore[attr-defined]
            built = build_timeline(
                viewer, self._authority, self._ledger, self._attestations, self._subjects(),
                self._feeds(), self._matrix(), self._policy(), clock, correlation_id=self._next_corr())
            if type(built) is not TimelineView:
                return built
            return render_guard(built, self._authority, correlation_id=self._next_corr())
        return self._run(build)  # type: ignore[return-value]

    def coverage(self, session: SessionRecord, viewer: ViewerScope) -> CoveragePanel | SafeError:
        refused = self._admit(session, viewer)
        if refused is not None:
            return refused
        return self._guarded_view(lambda: build_coverage_panel(
            viewer, self._authority, self._matrix(), correlation_id=self._next_corr()))  # type: ignore[return-value]

    def diff(self, session: SessionRecord, viewer: ViewerScope) -> ScopedDiffView | SafeError:
        refused = self._admit(session, viewer)
        if refused is not None:
            return refused
        return self._guarded_view(lambda: build_scoped_diff(
            viewer, self._authority, self._ledger, self._subjects(),
            correlation_id=self._next_corr()))  # type: ignore[return-value]

    def evidence(self, session: SessionRecord, viewer: ViewerScope) -> ScopedEvidenceView | SafeError:
        refused = self._admit(session, viewer)
        if refused is not None:
            return refused

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
