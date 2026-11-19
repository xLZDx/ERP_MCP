"""Regressions for S18 test-lane supervision lifecycle evidence."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from business_ai_gateway.phase2.test_lane_supervisor import (
    LifecycleEvent,
    SupervisorFailure,
    TestLaneSupervisor as Supervisor,
)


START = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.current = START
        self.calls = 0
        self.fail_on_call = fail_on_call

    def __call__(self):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise RuntimeError("private clock adapter detail")
        return self.current


class Handle:
    def __init__(self, clock: Clock, *, fail_wait: bool = False) -> None:
        self.clock = clock
        self.fail_wait = fail_wait
        self.wait_calls = 0

    async def wait(self) -> int:
        self.wait_calls += 1
        self.clock.current += timedelta(seconds=2)
        if self.fail_wait:
            raise RuntimeError("private process handle detail")
        return 0


class Runner:
    def __init__(self, clock: Clock, handle: Handle, *, start_delay_seconds: int = 0) -> None:
        self.clock = clock
        self.handle = handle
        self.start_delay_seconds = start_delay_seconds
        self.starts: list[tuple[str, int]] = []

    async def start(self, component_id: str, generation: int) -> Handle:
        self.starts.append((component_id, generation))
        self.clock.current += timedelta(seconds=self.start_delay_seconds)
        return self.handle


@pytest.mark.asyncio
async def test_started_timestamp_is_captured_after_delayed_successful_start():
    clock = Clock()
    handle = Handle(clock)
    runner = Runner(clock, handle, start_delay_seconds=5)
    supervisor = Supervisor("component-a", runner, max_restarts=0, clock=clock)

    evidence = await supervisor.run()

    started = next(item for item in evidence if item.event is LifecycleEvent.STARTED)
    exited = next(item for item in evidence if item.event is LifecycleEvent.EXITED)
    assert started.at == START + timedelta(seconds=5)
    assert exited.at == START + timedelta(seconds=7)
    assert handle.wait_calls == 1
    assert runner.starts == [("component-a", 0)]


@pytest.mark.asyncio
async def test_post_start_clock_failure_waits_for_child_and_does_not_restart():
    clock = Clock(fail_on_call=2)
    handle = Handle(clock)
    runner = Runner(clock, handle)
    supervisor = Supervisor("component-a", runner, max_restarts=2, clock=clock)

    with pytest.raises(SupervisorFailure) as failure:
        await supervisor.run()

    assert failure.value.code == "CLOCK_UNAVAILABLE"
    assert failure.value.evidence == ()
    assert "private clock adapter detail" not in str(failure.value)
    assert handle.wait_calls == 1
    assert runner.starts == [("component-a", 0)]


@pytest.mark.asyncio
async def test_post_start_clock_and_exit_observation_failure_is_sanitized_without_restart():
    clock = Clock(fail_on_call=2)
    handle = Handle(clock, fail_wait=True)
    runner = Runner(clock, handle)
    supervisor = Supervisor("component-a", runner, max_restarts=2, clock=clock)

    with pytest.raises(SupervisorFailure) as failure:
        await supervisor.run()

    assert failure.value.code == "COMPONENT_EXIT_UNOBSERVED"
    assert failure.value.evidence == ()
    assert "private process handle detail" not in str(failure.value)
    assert handle.wait_calls == 1
    assert runner.starts == [("component-a", 0)]
