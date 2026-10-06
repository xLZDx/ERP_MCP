from __future__ import annotations

import asyncio
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
    def __init__(
        self,
        tools: list[str],
        *,
        is_error: bool = False,
        result_text: str = '{"status":"ok"}',
    ):
        self.tools = [SimpleNamespace(name=name) for name in tools]
        self.is_error = is_error
        self.result_text = result_text
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
        return SimpleNamespace(
            is_error=self.is_error,
            content=[SimpleNamespace(type="text", text=self.result_text)],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["health", "metadata"])
async def test_secret_resolution_is_deadline_bounded_before_process_launch(tmp_path, operation):
    executable = tmp_path / "fixture.exe"
    executable.touch()

    async def hung_loader(_ref):
        await asyncio.Event().wait()

    client = RSVDataBridgeClient(executable=str(executable), config_root=str(tmp_path),
                                config_secret_loader=hung_loader, config_secret_ref="synthetic",
                                timeout_seconds=0.01)
    with pytest.raises(RSVBridgeUnavailable, match="timed out"):
        if operation == "health":
            await client.health(_source())
        else:
            await client.metadata(_source(), operation="config")


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


@pytest.mark.asyncio
async def test_rsv_bridge_metadata_calls_only_allowlisted_tool_and_normalizes_envelope(
    tmp_path: Path,
):
    executable = tmp_path / "bridge.exe"
    executable.touch()
    config_root = tmp_path / "configs"
    config_root.mkdir()
    (config_root / "source-a.json").touch()
    session = FakeSession(
        ["ping", "config", "describe", "get_structure", "query", "execute_query", "reveal", "help"],
        result_text='{"synthetic":true}',
    )

    @asynccontextmanager
    async def fake_stdio(_parameters):
        yield object(), object()

    client = RSVDataBridgeClient(
        executable=str(executable),
        config_root=str(config_root),
        session_factory=lambda *_streams: session,
        stdio_factory=fake_stdio,
    )
    result = await client.metadata(
        _source(),
        operation="get_structure",
        arguments={"object": "Справочник.Тест"},
    )

    assert result["source_id"] == "source-a"
    assert result["adapter"]["upstream_source_sha"] == "76fed8e6e16833fee1514969841b8d9a61c7c152"
    assert len(result["adapter"]["executable_sha256"]) == 64
    assert result["operation"] == "get_structure"
    assert result["data"] == {"synthetic": True}
    assert session.calls == [("get_structure", {"object": "Справочник.Тест"})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("query", {"table": "Справочник.Тест"}),
        ("execute_query", {"query": "ВЫБРАТЬ 1"}),
        ("reveal", {"text": "[ОРГ-00001]"}),
        ("describe", {"type": "Документ", "query": "SELECT 1"}),
        ("get_structure", {}),
        ("help", {"topic": "execute_query"}),
    ],
)
async def test_rsv_bridge_metadata_rejects_business_tools_and_unreviewed_arguments(
    tmp_path: Path, operation, arguments
):
    client = RSVDataBridgeClient(executable="bridge.exe", config_root=str(tmp_path))
    with pytest.raises(RSVBridgeUnavailable, match="allowlisted|unsupported|requires"):
        await client.metadata(_source(), operation=operation, arguments=arguments)


@pytest.mark.asyncio
async def test_rsv_bridge_metadata_response_is_bounded(tmp_path: Path):
    executable = tmp_path / "bridge.exe"
    executable.touch()
    config_root = tmp_path / "configs"
    config_root.mkdir()
    (config_root / "source-a.json").touch()
    session = FakeSession(
        ["ping", "config", "describe", "get_structure", "query", "execute_query", "reveal", "help"],
        result_text='{"large":"' + "x" * 200 + '"}',
    )

    @asynccontextmanager
    async def fake_stdio(_parameters):
        yield object(), object()

    client = RSVDataBridgeClient(
        executable=str(executable),
        config_root=str(config_root),
        session_factory=lambda *_streams: session,
        stdio_factory=fake_stdio,
    )
    with pytest.raises(RSVBridgeUnavailable, match="exceeded configured limit"):
        await client.metadata(
            _source(), operation="config", max_response_bytes=64
        )


@pytest.mark.asyncio
async def test_rsv_bridge_checks_configured_executable_digest_before_launch(tmp_path: Path):
    executable = tmp_path / "bridge.exe"
    executable.write_bytes(b"not-the-approved-bridge")
    config_root = tmp_path / "configs"
    config_root.mkdir()
    (config_root / "source-a.json").touch()
    session = FakeSession(["ping", "config", "describe", "get_structure", "help"])
    launches = []

    @asynccontextmanager
    async def fake_stdio(parameters):
        launches.append(parameters)
        yield object(), object()

    client = RSVDataBridgeClient(
        executable=str(executable),
        config_root=str(config_root),
        expected_executable_sha256="0" * 64,
        session_factory=lambda *_streams: session,
        stdio_factory=fake_stdio,
    )
    with pytest.raises(RSVBridgeUnavailable, match="digest mismatch"):
        await client.metadata(_source(), operation="config")
    assert launches == []


@pytest.mark.asyncio
async def test_health_timeout_closes_session_and_ephemeral_config(tmp_path: Path):
    executable = tmp_path / "bridge.exe"
    executable.touch()
    configs = []
    closed = []

    async def loader(_ref):
        return '{}'

    class HangingSession(FakeSession):
        async def initialize(self):
            await asyncio.sleep(60)

    @asynccontextmanager
    async def stdio(parameters):
        configs.append(Path(parameters.args[-1]))
        try:
            yield object(), object()
        finally:
            closed.append(True)

    client = RSVDataBridgeClient(
        executable=str(executable), config_root=str(tmp_path),
        config_secret_loader=loader, config_secret_ref="fixture",
        session_factory=lambda *_: HangingSession(["ping"]),
        stdio_factory=stdio, timeout_seconds=0.01,
    )
    with pytest.raises(RSVBridgeUnavailable, match="health check timed out"):
        await client.health(_source())
    assert closed == [True]
    assert configs and not configs[0].exists()


@pytest.mark.asyncio
async def test_digest_mismatch_does_not_resolve_secret_or_create_config(tmp_path: Path):
    executable = tmp_path / "bridge.exe"
    executable.touch()
    resolved = []

    async def loader(_ref):
        resolved.append(True)
        return '{}'

    client = RSVDataBridgeClient(
        executable=str(executable), config_root=str(tmp_path),
        config_secret_loader=loader, config_secret_ref="fixture",
        expected_executable_sha256="f" * 64,
    )
    with pytest.raises(RSVBridgeUnavailable, match="digest mismatch"):
        await client.health(_source())
    assert not resolved


@pytest.mark.asyncio
async def test_rsv_bridge_uses_secret_bound_ephemeral_config_and_removes_it(tmp_path: Path):
    executable = tmp_path / "bridge.exe"
    executable.touch()
    config_root = tmp_path / "configs"
    config_root.mkdir()
    session = FakeSession(
        ["ping", "config", "describe", "get_structure", "help"],
        result_text='{"safe":true}',
    )
    observed_config = {}

    @asynccontextmanager
    async def fake_stdio(parameters):
        config_path = Path(parameters.args[2])
        observed_config["path"] = config_path
        observed_config["content"] = config_path.read_text(encoding="utf-8")
        yield object(), object()

    async def loader(_ref: str) -> str:
        return '{"kind":"file","file":"C:\\\\disposable\\\\base"}'

    client = RSVDataBridgeClient(
        executable=str(executable),
        config_root=str(config_root),
        config_secret_loader=loader,
        config_secret_ref="rsv-config",
        session_factory=lambda *_streams: session,
        stdio_factory=fake_stdio,
    )
    result = await client.metadata(_source(), operation="config")

    assert result["operation"] == "config"
    assert '"kind":"file"' in observed_config["content"]
    assert not observed_config["path"].exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret_config",
    ["not-json", "[]"],
    ids=["malformed-json", "non-object"],
)
async def test_rsv_bridge_rejects_invalid_secret_config_before_process_launch(
    tmp_path: Path, secret_config: str
):
    executable = tmp_path / "bridge.exe"
    executable.touch()
    launches = []

    async def loader(_ref: str) -> str:
        return secret_config

    @asynccontextmanager
    async def fake_stdio(parameters):
        launches.append(parameters)
        yield object(), object()

    client = RSVDataBridgeClient(
        executable=str(executable),
        config_root=str(tmp_path),
        config_secret_loader=loader,
        config_secret_ref="rsv-config",
        session_factory=lambda *_streams: FakeSession(["ping"]),
        stdio_factory=fake_stdio,
    )
    with pytest.raises(RSVBridgeUnavailable, match="secret-bound bridge config is invalid"):
        await client.health(_source())
    assert launches == []


@pytest.mark.asyncio
async def test_rsv_bridge_rejects_oversized_secret_config_before_process_launch(
    tmp_path: Path,
):
    executable = tmp_path / "bridge.exe"
    executable.touch()
    launches = []

    async def loader(_ref: str) -> str:
        return '{"x":"' + ("x" * 70_000) + '"}'

    @asynccontextmanager
    async def fake_stdio(parameters):
        launches.append(parameters)
        yield object(), object()

    client = RSVDataBridgeClient(
        executable=str(executable),
        config_root=str(tmp_path),
        config_secret_loader=loader,
        config_secret_ref="rsv-config",
        session_factory=lambda *_streams: FakeSession(["ping"]),
        stdio_factory=fake_stdio,
    )
    with pytest.raises(RSVBridgeUnavailable, match="secret-bound bridge config is invalid"):
        await client.health(_source())
    assert launches == []

