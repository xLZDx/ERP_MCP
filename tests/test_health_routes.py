from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_readiness_returns_503_when_control_dependencies_are_not_ready(monkeypatch):
    from business_ai_gateway.app import readyz, runtime

    async def not_ready():
        return False

    monkeypatch.setattr(runtime, "ready", not_ready)
    response = await readyz(None)

    assert response.status_code == 503
    assert json.loads(response.body) == {"status": "not-ready"}


@pytest.mark.asyncio
async def test_readiness_sanitizes_dependency_failure(monkeypatch):
    from business_ai_gateway.app import readyz, runtime

    async def database_unavailable():
        raise ConnectionError("credential=PRIVATE-DETAIL")

    monkeypatch.setattr(runtime, "ready", database_unavailable)
    response = await readyz(None)

    assert response.status_code == 503
    assert json.loads(response.body) == {
        "status": "not-ready",
        "error": "ConnectionError",
    }
    assert b"PRIVATE-DETAIL" not in response.body
