"""Functional suite configuration. Skips ONLY when the stack env vars are absent."""

from __future__ import annotations

import pytest

from tests.functional.support import harness


def pytest_sessionstart(session):
    if harness.stack_configured():
        from tests.functional.support import evidence

        evidence.reset()


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/functional" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.functional)
            if not harness.stack_configured():
                item.add_marker(pytest.mark.skip(reason=harness.MISSING))


@pytest.fixture(scope="session", autouse=True)
def suite_start():
    """DB-clock marker + Fake1C log cursor taken before the first test (for whole-run proofs)."""
    import asyncio

    if not harness.stack_configured():
        pytest.skip(harness.MISSING)
    return {"db": asyncio.run(harness.db_now()), "fake_seq": harness.fake_mark(),
            "sidecar_seq": harness.sidecar_requests(10**9)["last_seq"]}
