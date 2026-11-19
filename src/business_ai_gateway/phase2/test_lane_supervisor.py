"""Injected, test-lane-only supervision policy; no OS process control or runtime wiring.

The runner adapter owns how one approved component is started. This module only
observes its exit, records sanitized lifecycle evidence, and bounds restarts.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from .ops_types import is_aware_datetime, is_identity_text

__all__ = [
    "ComponentHandlePort", "ComponentRunnerPort", "LifecycleEvidence", "LifecycleEvent",
    "SupervisorFailure", "TestLaneSupervisor",
]

MAX_COMPONENT_ID_CHARS = 128
MAX_RESTARTS = 5


class ComponentHandlePort(Protocol):
    async def wait(self) -> int:
        """Wait for observed component exit and return its exact integer exit code."""


class ComponentRunnerPort(Protocol):
    async def start(self, component_id: str, generation: int) -> ComponentHandlePort:
        """Start the preconfigured component identified by stable ID; accepts no command input."""


class LifecycleEvent(StrEnum):
    STARTED = "STARTED"
    EXITED = "EXITED"
    RESTART_SCHEDULED = "RESTART_SCHEDULED"
    RESTART_LIMIT_REACHED = "RESTART_LIMIT_REACHED"
    START_UNCERTAIN = "START_UNCERTAIN"
    WAIT_FAILED = "WAIT_FAILED"


@dataclass(frozen=True, slots=True)
class LifecycleEvidence:
    """Sanitized event; deliberately excludes PID, command, stdout, stderr and exception text."""

    component_id: str
    generation: int
    event: LifecycleEvent
    at: datetime
    exit_code: int | None = None


class SupervisorFailure(RuntimeError):
    """Sanitized failure with the lifecycle record accumulated before stopping."""

    def __init__(self, code: str, evidence: tuple[LifecycleEvidence, ...]) -> None:
        self.code = code
        self.evidence = evidence
        super().__init__(code)


class TestLaneSupervisor:
    """One-shot supervisor for one stable, preconfigured test-lane component.

    The adapter must not accept caller-provided executables. A timeout, runner
    error, or malformed response stops retries: the old process might still live.
    """

    __slots__ = ("_component_id", "_runner", "_max_restarts", "_clock", "_lock", "_has_run")

    def __init__(self, component_id: str, runner: ComponentRunnerPort, *,
                 max_restarts: int, clock: Callable[[], datetime]) -> None:
        if (not is_identity_text(component_id)
                or len(component_id) > MAX_COMPONENT_ID_CHARS
                or type(max_restarts) is not int or not 0 <= max_restarts <= MAX_RESTARTS
                or not callable(getattr(runner, "start", None))
                or not callable(clock)):
            raise ValueError("SUPERVISOR_CONFIG_INVALID")
        self._component_id = component_id
        self._runner = runner
        self._max_restarts = max_restarts
        self._clock = clock
        self._lock = asyncio.Lock()
        self._has_run = False

    def _timestamp(self) -> datetime:
        try:
            value = self._clock()
        except Exception:  # noqa: BLE001 - never expose adapter exception text
            raise SupervisorFailure("CLOCK_UNAVAILABLE", ()) from None
        if not is_aware_datetime(value):
            raise SupervisorFailure("CLOCK_INVALID", ())
        return value.astimezone(UTC)

    async def run(self) -> tuple[LifecycleEvidence, ...]:
        """Start, observe exits and restart the same ID no more than the configured bound."""
        async with self._lock:
            if self._has_run:
                raise SupervisorFailure("SUPERVISOR_ALREADY_USED", ())
            self._has_run = True
            evidence: list[LifecycleEvidence] = []

            def record_at(generation: int, event: LifecycleEvent, at: datetime,
                          exit_code: int | None = None) -> None:
                evidence.append(LifecycleEvidence(
                    self._component_id, generation, event, at, exit_code))

            def record(generation: int, event: LifecycleEvent,
                       exit_code: int | None = None) -> None:
                try:
                    at = self._timestamp()
                except SupervisorFailure as exc:
                    raise SupervisorFailure(exc.code, tuple(evidence)) from None
                record_at(generation, event, at, exit_code)

            for generation in range(self._max_restarts + 1):
                # Validate time before starting so a broken evidence clock cannot leave an
                # unobserved child running after startup.
                try:
                    pre_start_at = self._timestamp()
                except SupervisorFailure as exc:
                    raise SupervisorFailure(exc.code, tuple(evidence)) from None
                try:
                    handle = await self._runner.start(self._component_id, generation)
                except Exception:  # noqa: BLE001 - no restart when start outcome is uncertain
                    record(generation, LifecycleEvent.START_UNCERTAIN)
                    raise SupervisorFailure("COMPONENT_START_UNCERTAIN", tuple(evidence)) from None
                if not callable(getattr(handle, "wait", None)):
                    record(generation, LifecycleEvent.START_UNCERTAIN)
                    raise SupervisorFailure("COMPONENT_START_UNCERTAIN", tuple(evidence))
                try:
                    started_at = self._timestamp()
                except SupervisorFailure as exc:
                    # A child may now be running. Never retry or return while its exit is
                    # unobserved just because the evidence clock failed after start.
                    try:
                        await handle.wait()
                    except Exception:  # noqa: BLE001 - child may still be alive
                        raise SupervisorFailure("COMPONENT_EXIT_UNOBSERVED", tuple(evidence)) from None
                    raise SupervisorFailure(exc.code, tuple(evidence)) from None
                record_at(generation, LifecycleEvent.STARTED, started_at)
                try:
                    exit_code = await handle.wait()
                except Exception:  # noqa: BLE001 - old component may still be alive
                    record(generation, LifecycleEvent.WAIT_FAILED)
                    raise SupervisorFailure("COMPONENT_EXIT_UNOBSERVED", tuple(evidence)) from None
                if (type(exit_code) is not int
                        or not -(2 ** 31) <= exit_code < 2 ** 31):
                    record(generation, LifecycleEvent.WAIT_FAILED)
                    raise SupervisorFailure("COMPONENT_EXIT_INVALID", tuple(evidence))
                record(generation, LifecycleEvent.EXITED, exit_code)
                if generation == self._max_restarts:
                    record(generation, LifecycleEvent.RESTART_LIMIT_REACHED, exit_code)
                    return tuple(evidence)
                record(generation + 1, LifecycleEvent.RESTART_SCHEDULED, exit_code)
            raise SupervisorFailure("SUPERVISOR_STATE_INVALID", tuple(evidence))
