"""Regressions for S18 test-lane supervision lifecycle evidence."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from business_ai_gateway.phase2.test_lane_supervisor import (
    LifecycleEvent,
    SupervisorCancelled,
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


class UncertainStartRunner:
    def __init__(self) -> None:
        self.starts: list[tuple[str, int]] = []

    async def start(self, component_id: str, generation: int) -> Handle:
        self.starts.append((component_id, generation))
        raise RuntimeError("private runner error with process details")


class GatedHandle:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.wait_entered = asyncio.Event()
        self.release_wait = asyncio.Event()
        self.wait_calls = 0

    async def wait(self) -> int:
        self.wait_calls += 1
        self.wait_entered.set()
        await self.release_wait.wait()
        self.clock.current += timedelta(seconds=2)
        return 0


class GatedStartRunner:
    def __init__(self, handle: GatedHandle) -> None:
        self.handle = handle
        self.start_entered = asyncio.Event()
        self.release_start = asyncio.Event()
        self.starts: list[tuple[str, int]] = []

    async def start(self, component_id: str, generation: int) -> GatedHandle:
        self.starts.append((component_id, generation))
        self.start_entered.set()
        await self.release_start.wait()
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


@pytest.mark.asyncio
async def test_uncertain_start_failure_is_sanitized_recorded_and_never_retried():
    clock = Clock()
    runner = UncertainStartRunner()
    supervisor = Supervisor("component-a", runner, max_restarts=3, clock=clock)

    with pytest.raises(SupervisorFailure) as failure:
        await supervisor.run()

    assert failure.value.code == "COMPONENT_START_UNCERTAIN"
    assert [(item.event, item.component_id, item.generation) for item in failure.value.evidence] == [
        (LifecycleEvent.START_UNCERTAIN, "component-a", 0),
    ]
    assert failure.value.evidence[0].at == START
    assert "private runner error" not in str(failure.value)
    assert runner.starts == [("component-a", 0)]


@pytest.mark.asyncio
async def test_cancellation_during_handle_wait_waits_for_exit_before_raising():
    clock = Clock()
    handle = GatedHandle(clock)
    runner = Runner(clock, handle)
    supervisor = Supervisor("component-a", runner, max_restarts=3, clock=clock)
    task = asyncio.create_task(supervisor.run())
    await handle.wait_entered.wait()

    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert handle.wait_calls == 1

    handle.release_wait.set()
    with pytest.raises(SupervisorCancelled) as cancelled:
        await task

    assert [item.event for item in cancelled.value.evidence] == [
        LifecycleEvent.STARTED, LifecycleEvent.EXITED,
    ]
    assert cancelled.value.evidence[-1].exit_code == 0
    assert runner.starts == [("component-a", 0)]


@pytest.mark.asyncio
async def test_cancellation_during_start_observes_returned_handle_exit_before_raising():
    clock = Clock()
    handle = GatedHandle(clock)
    runner = GatedStartRunner(handle)
    supervisor = Supervisor("component-a", runner, max_restarts=3, clock=clock)
    task = asyncio.create_task(supervisor.run())
    await runner.start_entered.wait()

    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert runner.starts == [("component-a", 0)]
    assert handle.wait_calls == 0

    runner.release_start.set()
    await handle.wait_entered.wait()
    assert not task.done()
    assert handle.wait_calls == 1
    handle.release_wait.set()
    with pytest.raises(SupervisorCancelled) as cancelled:
        await task

    assert [item.event for item in cancelled.value.evidence] == [
        LifecycleEvent.STARTED, LifecycleEvent.EXITED,
    ]
    assert cancelled.value.evidence[-1].exit_code == 0
    assert runner.starts == [("component-a", 0)]
