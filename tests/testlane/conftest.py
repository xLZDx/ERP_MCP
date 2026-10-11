"""Fixtures for the test-lane tests."""
from __future__ import annotations

from typing import Any

import pytest
from _testlane_helpers import FakeGateway

from testlane.phase2_mcp.reconcile import Reconciler


@pytest.fixture
def make_reconciler():
    def build(a: dict[str, Any], b: dict[str, Any]) -> tuple[Reconciler, FakeGateway, FakeGateway]:
        ga, gb = FakeGateway("A", a), FakeGateway("B", b)
        return Reconciler(ga, gb, "src-test"), ga, gb
    return build
