"""Phase 2 capture loop: ONE capture step that enforces the resnapshot tracker.

Composes ``SourceScheduler.run_job`` (lease + fence + failure policy), the connector SDK exchange
validation (``checked_capture_page``), ``drift.classify`` and ``ResnapshotTracker``. The scheduler
itself does not know about the tracker; this object is the enforcement point.

Rules
- INCREMENTAL capture of a connection for which ``tracker.is_required`` is True is REFUSED with
  ``CaptureStatus.RESNAPSHOT_REQUIRED``. The refusal happens BEFORE the scheduler is entered, so no
  lease is taken, the connector is not called, the job is neither failed nor poisoned and the
  scheduler failure counter is untouched. Only a request flagged ``snapshot=True`` may run.
  (The work callable re-checks: if the requirement appeared between the pre-check and the lease,
  the connector is still not called; the port has no "release" call, so that rare race costs one
  scheduler-accounted retry - reported as a gap, see below.)
- A snapshot takes ``tracker.begin_snapshot()`` BEFORE the connector call. On ``OK_COMPLETE`` and a
  SUCCEEDED job it calls ``tracker.complete`` with the epoch the capture ran under and the LIVE
  ledger epoch read after the run. PARTIAL / failures / older epoch / a requirement recorded after
  the snapshot began never clear. Tracker clears and accepted-hash advances are applied only after
  the scheduler reports SUCCEEDED (a lost lease at finish applies nothing); a requirement
  (``CURSOR_LOST``) is applied immediately because requiring is the conservative direction.
- An SDK-invalid response (``ValidationError`` or wrong type) is the failure
  ``WORK_RETURNED_INVALID`` (work returns a non-outcome), never drift, never a hash.
- Typed connector failures are raised as ``ConnectorFailure(kind)``; ``TimeoutError`` is a TIMEOUT;
  any other exception is an OUTAGE recorded by the scheduler as ``WORK_EXCEPTION:<ClassName>``.
  Raw exception text is never stored or returned.
- The response ``content_digest`` is used as the structural hash handed to ``drift.classify`` ONLY for
  an ``OK_COMPLETE`` outcome; a partial/unknown capture carries no hash (drift rejects one).
- ``snapshot=True`` requires a request without ``page_cursor`` (first page); the request must carry
  the loop's own tenant/source. The connector call runs on a dedicated bounded executor under
  ``connector_timeout``; a call that outlives it is a TIMEOUT and its late result is discarded (the
  worker thread cannot be cancelled and is a known gap).
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final
from uuid import UUID

from .connector_sdk import (
    CaptureRequest,
    ConnectorContract,
    ValidationError,
    checked_capture_page,
    response_to_outcome,
)
from .drift import (
    CaptureOutcome,
    CaptureOutcomeKind,
    DriftDecision,
    DriftEventKind,
    classify,
)
from .ports import LedgerPort, PortError, Scope
from .resnapshot import ResnapshotReason, ResnapshotTracker
from .scheduler import LeaseHandle, RunResult, RunStatus, SourceScheduler

__all__ = ["CaptureLoop", "CaptureResult", "CaptureStatus", "ConnectorFailure"]

_FAILURE_KINDS: Final = frozenset({
    CaptureOutcomeKind.TIMEOUT, CaptureOutcomeKind.OUTAGE,
    CaptureOutcomeKind.ACCESS_DENIED, CaptureOutcomeKind.CURSOR_LOST,
})


class ConnectorFailure(Exception):
    """A connector's typed non-OK outcome (TIMEOUT / OUTAGE / ACCESS_DENIED / CURSOR_LOST)."""

    def __init__(self, kind: CaptureOutcomeKind) -> None:
        if kind not in _FAILURE_KINDS:
            raise ValueError("CONNECTOR_FAILURE_KIND_INVALID")
        super().__init__(kind.value)
        self.kind = kind


class CaptureStatus(StrEnum):
    CAPTURED = "CAPTURED"                        # job SUCCEEDED (complete or partial capture)
    RESNAPSHOT_REQUIRED = "RESNAPSHOT_REQUIRED"  # incremental refused; nothing ran
    INVALID_RESPONSE = "INVALID_RESPONSE"        # SDK-invalid response: failure, not drift
    FAILED = "FAILED"                            # connector failure; scheduler decided retry/poison
    NOT_RUN = "NOT_RUN"                          # scheduler did not run/finish the work (see run)


@dataclass(frozen=True, slots=True)
class CaptureResult:
    status: CaptureStatus
    outcome_kind: CaptureOutcomeKind | None
    events: tuple[DriftEventKind, ...]
    resnapshot_required: bool
    resnapshot_reason: ResnapshotReason | None
    cleared: bool
    accepted_hash: str | None
    candidate_hash: str | None
    run: RunResult | None  # None when the scheduler was not entered


class _Refused(Exception):
    """Internal: requirement appeared between the pre-check and the lease."""


class CaptureLoop:
    def __init__(self, scheduler: SourceScheduler, tracker: ResnapshotTracker,
                 connector: ConnectorContract, ledger: LedgerPort, scope: Scope, *,
                 connector_timeout: float = 30.0, max_threads: int = 4) -> None:
        if not (isinstance(connector_timeout, (int, float)) and connector_timeout > 0):
            raise ValueError("CONNECTOR_TIMEOUT_INVALID")
        self._timeout = float(connector_timeout)
        self._executor = ThreadPoolExecutor(max_workers=max_threads,
                                            thread_name_prefix="capture-connector")
        self._sched, self._tracker, self._connector = scheduler, tracker, connector
        self._ledger, self._scope = ledger, scope
        self._accepted: dict[str, str] = {}

    def accepted_hash(self, connection_id: str) -> str | None:
        return self._accepted.get(connection_id)

    def _result(self, status: CaptureStatus, connection_id: str, *,
                kind: CaptureOutcomeKind | None = None, decision: DriftDecision | None = None,
                cleared: bool = False, run: RunResult | None = None) -> CaptureResult:
        return CaptureResult(
            status, kind, decision.events if decision else (),
            self._tracker.is_required(connection_id), self._tracker.reason(connection_id),
            cleared, self._accepted.get(connection_id),
            decision.candidate_hash if decision else None, run)

    async def capture_step(self, job_id: UUID, connection_id: str, request: CaptureRequest, *,
                           snapshot: bool = False) -> CaptureResult:
        if request.tenant_id != self._scope.tenant_id or request.source_id != self._scope.source_id:
            raise ValueError("REQUEST_SCOPE_MISMATCH")
        if snapshot and request.page_cursor is not None:
            raise ValueError("SNAPSHOT_REQUIRES_FIRST_PAGE")
        if self._tracker.is_required(connection_id) and not snapshot:
            return self._result(CaptureStatus.RESNAPSHOT_REQUIRED, connection_id)
        state: dict[str, Any] = {"invalid": False, "refused": False}

        async def work(handle: LeaseHandle) -> CaptureOutcomeKind:
            await handle.ensure_fresh()
            # re-check with no await between here and the connector call
            if self._tracker.is_required(connection_id) and not snapshot:
                state["refused"] = True
                raise _Refused
            token = self._tracker.begin_snapshot() if snapshot else None
            state["token"] = token
            kind, digest = await self._call(request, state)
            if kind is None:  # SDK-invalid response
                state["invalid"] = True
                return None  # type: ignore[return-value]  # scheduler: WORK_RETURNED_INVALID
            state["kind"] = kind
            decision = classify(CaptureOutcome(kind, digest), self._accepted.get(connection_id))
            state["decision"] = decision
            self._tracker.observe_decision(connection_id, decision, request.scope_epoch)
            return kind

        run = await self._sched.run_job(job_id, work)
        kind = state.get("kind")
        decision = state.get("decision")
        if state["refused"]:
            return self._result(CaptureStatus.RESNAPSHOT_REQUIRED, connection_id, run=run)
        if state["invalid"]:
            return self._result(CaptureStatus.INVALID_RESPONSE, connection_id, run=run)
        if run.status is not RunStatus.SUCCEEDED:
            status = (CaptureStatus.FAILED if kind in _FAILURE_KINDS or
                      run.status in (RunStatus.RETRY_SCHEDULED, RunStatus.POISONED)
                      else CaptureStatus.NOT_RUN)
            return self._result(status, connection_id, kind=kind, decision=decision, run=run)
        cleared = False
        if decision is not None:
            if decision.accepted_hash is not None:
                self._accepted[connection_id] = decision.accepted_hash
            if snapshot and state.get("token") is not None:
                try:
                    live = await self._ledger.scope_epoch(self._scope)
                except PortError:
                    live = None  # cannot prove the epoch: keep the requirement (conservative)
                if type(live) is int:
                    cleared = self._tracker.complete(
                        connection_id, kind, request.scope_epoch, live,
                        snapshot_token=state["token"])
        return self._result(CaptureStatus.CAPTURED, connection_id, kind=kind, decision=decision,
                            cleared=cleared, run=run)

    async def _call(self, request: CaptureRequest,
                    state: dict[str, Any]) -> tuple[CaptureOutcomeKind | None, str | None]:
        """(kind, digest); kind None = SDK-invalid. Typed failures are returned as kinds."""
        try:
            response = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    self._executor, checked_capture_page, self._connector, request),
                self._timeout)
            kind = response_to_outcome(response)
            digest = (response.provenance.content_digest
                      if kind is CaptureOutcomeKind.OK_COMPLETE else None)
            return kind, digest
        except ValidationError:
            return None, None
        except ConnectorFailure as exc:
            return exc.kind, None
        except TimeoutError:
            return CaptureOutcomeKind.TIMEOUT, None
        except Exception:
            # record the failure for the result, then let the scheduler account it by class name
            # only (WORK_EXCEPTION:<ClassName>); the raw text is never read here.
            state["kind"] = CaptureOutcomeKind.OUTAGE
            state["decision"] = classify(
                CaptureOutcome(CaptureOutcomeKind.OUTAGE), None)
            raise
