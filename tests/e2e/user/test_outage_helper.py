"""The `outage()` helper always restarts the component (monkeypatched run_fault, no env needed)."""

from __future__ import annotations

import subprocess

import pytest
import user_support

pytestmark = [pytest.mark.user]


def _fake(monkeypatch, behaviour):
    calls: list[tuple[str, str]] = []

    def run_fault(component, action, **kwargs):
        calls.append((component, action))
        behaviour(component, action, len([c for c in calls if c[1] == action]))

    monkeypatch.setattr(user_support, "run_fault", run_fault)
    return calls


def test_failing_stop_still_triggers_start(monkeypatch):
    def behaviour(component, action, nth):
        if action == "stop":
            raise subprocess.TimeoutExpired("fault.ps1", 1)

    calls = _fake(monkeypatch, behaviour)
    with pytest.raises(subprocess.TimeoutExpired), user_support.outage("redis"):
        pytest.fail("body must not run when the stop failed")
    assert calls == [("redis", "stop"), ("redis", "start")]


def test_body_exception_propagates_after_start(monkeypatch):
    calls = _fake(monkeypatch, lambda *a: None)
    with pytest.raises(ValueError, match="boom"), user_support.outage("postgres"):
        raise ValueError("boom")
    assert calls == [("postgres", "stop"), ("postgres", "start")]


def test_start_is_retried_once_on_timeout(monkeypatch):
    def behaviour(component, action, nth):
        if action == "start" and nth == 1:
            raise subprocess.TimeoutExpired("fault.ps1", 1)

    calls = _fake(monkeypatch, behaviour)
    with user_support.outage("fake1c"):
        pass
    assert [a for _, a in calls] == ["stop", "start", "start"]


def test_unrecoverable_start_is_reported_chained(monkeypatch):
    def behaviour(component, action, nth):
        if action == "start":
            raise RuntimeError(f"start failed #{nth}")

    _fake(monkeypatch, behaviour)
    with pytest.raises(RuntimeError, match="could NOT be restarted") as info, \
            user_support.outage("sidecar"):
        raise ValueError("body failure")
    assert isinstance(info.value.__cause__, RuntimeError)
    chain, link = [], info.value
    while link is not None:  # the original body failure stays reachable through the chain
        chain.append(type(link))
        link = link.__context__
    assert ValueError in chain, chain
