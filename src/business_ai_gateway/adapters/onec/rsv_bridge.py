from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from ...models import Source


class RSVBridgeUnavailable(RuntimeError):
    """The pinned RSV bridge did not complete its read-only health handshake."""


class RSVDataBridgeClient:
    """Health boundary for the pinned upstream process; it does not proxy arbitrary tools."""

    _SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    UPSTREAM_TOOLS = frozenset(
        {
            "config",
            "describe",
            "get_structure",
            "query",
            "execute_query",
            "ping",
            "help",
            "reveal",
        }
    )

    def __init__(
        self,
        *,
        executable: str,
        config_root: str,
        session_factory: Any = ClientSession,
        stdio_factory: Any = stdio_client,
    ):
        self.executable = str(Path(executable).resolve())
        self.config_root = Path(config_root).resolve()
        self._session_factory = session_factory
        self._stdio_factory = stdio_factory

    def _parameters(self, source: Source) -> StdioServerParameters:
        if not self._SOURCE_ID.fullmatch(source.id):
            raise RSVBridgeUnavailable("source id is not safe for bridge config lookup")
        config = (self.config_root / f"{source.id}.json").resolve()
        if config.parent != self.config_root:
            raise RSVBridgeUnavailable("bridge config path escaped its configured root")
        if not config.is_file():
            raise RSVBridgeUnavailable("source bridge config is not installed")
        inherited = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP") if key in os.environ}
        return StdioServerParameters(
            command=self.executable,
            args=["serve", "--config", str(config)],
            # Do not inherit credentials or ambient process configuration.
            env=inherited,
            cwd=str(Path(self.executable).parent),
        )

    async def health(self, source: Source) -> dict[str, Any]:
        parameters = self._parameters(source)
        try:
            async with (
                self._stdio_factory(parameters) as (read_stream, write_stream),
                self._session_factory(read_stream, write_stream) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                if "ping" not in names or not names.issubset(self.UPSTREAM_TOOLS):
                    raise RSVBridgeUnavailable("upstream tool contract is not allowlisted")
                result = await session.call_tool("ping", {})
                if result.isError:
                    raise RSVBridgeUnavailable("upstream ping failed")
            return {
                "status": "healthy",
                "source_id": source.id,
                "tool_names": sorted(names),
            }
        except RSVBridgeUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            # Do not forward subprocess stderr, connection strings, or upstream payloads.
            raise RSVBridgeUnavailable(
                f"upstream bridge health check failed ({type(exc).__name__})"
            ) from None
