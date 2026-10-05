from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from business_ai_gateway.adapters.onec.rsv_bridge import (
    RSVBridgeUnavailable,
    RSVDataBridgeClient,
)
from business_ai_gateway.models import Source


def _source(source_id: str = "source-a") -> Source:
    return Source(
        id=source_id,
        project="onec",
        kind="onec_auto",
        display_name="fixture",
        base_url="https://onec.example/odata/standard.odata",
        username_secret_ref=None,
        password_secret_ref=None,
        read_only=True,
        enabled=True,
        tags=(),
        entity_allow_patterns=(),
        entity_deny_patterns=(),
    )


class FakeSession:
    def __init__(self, tools: list[str], *, is_error: bool = False):
        self.tools = [SimpleNamespace(name=name) for name in tools]
        self.is_error = is_error
        self.calls: list[tuple[str, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def initialize(self):
        return None

    async def list_tools(self):
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name: str, arguments: dict):
        self.calls.append((name, arguments))
        return SimpleNamespace(isError=self.is_error)


@pytest.mark.asyncio
async def test_rsv_bridge_health_uses_pinned_process_and_only_calls_ping(tmp_path: Path):
    executable = tmp_path / "rsvdata-bridge.exe"
    executable.touch()
    config_root = tmp_path / "configs"
    config_root.mkdir()
    (config_root / "source-a.json").write_text("{}", encoding="utf-8")
    captured = {}
    session = FakeSession(["ping", "query", "execute_query", "reveal"])

    @asynccontextmanager
    async def fake_stdio(parameters):
        captured["parameters"] = parameters
        yield object(), object()

    def fake_session(read_stream, write_stream):
        captured["streams"] = (read_stream, write_stream)
        return session

    client = RSVDataBridgeClient(
        executable=str(executable),
        config_root=str(config_root),
        session_factory=fake_session,
        stdio_factory=fake_stdio,
    )

    result = await client.health(_source())

    assert result["status"] == "healthy"
    assert captured["parameters"].command == str(executable.resolve())
    assert captured["parameters"].args == [
        "serve",
        "--config",
        str((config_root / "source-a.json").resolve()),
    ]
    assert session.calls == [("ping", {})]


@pytest.mark.asyncio
async def test_rsv_bridge_rejects_unsafe_source_id_before_process_launch(tmp_path: Path):
    client = RSVDataBridgeClient(executable="bridge.exe", config_root=str(tmp_path))

    with pytest.raises(RSVBridgeUnavailable, match="source id"):
        await client.health(_source("../other"))


@pytest.mark.asyncio
async def test_rsv_bridge_fails_closed_on_unreviewed_upstream_tool(tmp_path: Path):
    executable = tmp_path / "bridge.exe"
    executable.touch()
    config_root = tmp_path / "configs"
    config_root.mkdir()
    (config_root / "source-a.json").touch()
    session = FakeSession(["ping", "write_record"])

    @asynccontextmanager
    async def fake_stdio(_parameters):
        yield object(), object()

    client = RSVDataBridgeClient(
        executable=str(executable),
        config_root=str(config_root),
        session_factory=lambda *_streams: session,
        stdio_factory=fake_stdio,
    )

    with pytest.raises(RSVBridgeUnavailable, match="not allowlisted"):
        await client.health(_source())
    assert session.calls == []


@pytest.mark.asyncio
async def test_rsv_bridge_sanitizes_ping_failure(tmp_path: Path):
    executable = tmp_path / "bridge.exe"
    executable.touch()
    config_root = tmp_path / "configs"
    config_root.mkdir()
    (config_root / "source-a.json").touch()
    session = FakeSession(["ping"], is_error=True)

    @asynccontextmanager
    async def fake_stdio(_parameters):
        yield object(), object()

    client = RSVDataBridgeClient(
        executable=str(executable),
        config_root=str(config_root),
        session_factory=lambda *_streams: session,
        stdio_factory=fake_stdio,
    )

    with pytest.raises(RSVBridgeUnavailable, match="ping failed") as exc:
        await client.health(_source())
    assert "arguments" not in str(exc.value)

