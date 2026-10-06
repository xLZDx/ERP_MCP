from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from ...models import Source


class RSVBridgeUnavailable(RuntimeError):
    """The pinned RSV bridge did not complete its read-only health handshake."""


UPSTREAM_SHA = "76fed8e6e16833fee1514969841b8d9a61c7c152"
METADATA_TOOLS = frozenset({"ping", "config", "describe", "get_structure", "help"})


class RSVDataBridgeClient:
    """Health and narrowly allowlisted metadata boundary for the pinned upstream process."""

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
        timeout_seconds: float = 30.0,
        expected_executable_sha256: str | None = None,
        config_secret_loader: Callable[[str], Awaitable[str]] | None = None,
        config_secret_ref: str | None = None,
    ):
        self.executable = str(Path(executable).resolve())
        self.config_root = Path(config_root).resolve()
        self._session_factory = session_factory
        self._stdio_factory = stdio_factory
        self.timeout_seconds = timeout_seconds
        self.expected_executable_sha256 = (
            expected_executable_sha256.lower() if expected_executable_sha256 else None
        )
        self._config_secret_loader = config_secret_loader
        self._config_secret_ref = config_secret_ref

    def _verify_executable(self) -> str:
        try:
            with open(self.executable, "rb") as executable:
                digest = hashlib.file_digest(executable, "sha256").hexdigest()
        except OSError:
            raise RSVBridgeUnavailable("configured RSV bridge executable is unavailable") from None
        if self.expected_executable_sha256 and not hmac.compare_digest(
            digest, self.expected_executable_sha256
        ):
            raise RSVBridgeUnavailable("configured RSV bridge executable digest mismatch")
        return digest

    @staticmethod
    def _metadata_arguments(operation: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        if operation not in METADATA_TOOLS:
            raise RSVBridgeUnavailable("RSV operation is not allowlisted")
        args = {} if arguments is None else arguments
        if not isinstance(args, dict):
            raise RSVBridgeUnavailable("RSV metadata arguments must be an object")
        allowed = {
            "ping": set(),
            "config": set(),
            "describe": {"type", "filter", "find", "subsystem", "object", "table"},
            "get_structure": {"object"},
            "help": {"topic"},
        }[operation]
        if set(args) - allowed:
            raise RSVBridgeUnavailable("RSV metadata arguments contain unsupported fields")
        if operation == "get_structure" and set(args) != {"object"}:
            raise RSVBridgeUnavailable("get_structure requires exactly one object name")
        if operation == "describe" and not args:
            raise RSVBridgeUnavailable("describe requires a bounded selector")
        if operation == "help" and args.get("topic") not in {
            None, "config", "describe", "get_structure", "help", "ping", "workflow", "about"
        }:
            raise RSVBridgeUnavailable("help topic is not allowlisted")
        for value in args.values():
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise RSVBridgeUnavailable("RSV metadata selectors must be strings of at most 256 chars")
        return dict(args)

    async def _parameters(
        self, source: Source
    ) -> tuple[StdioServerParameters, str, tempfile.TemporaryDirectory[str] | None]:
        if not self._SOURCE_ID.fullmatch(source.id):
            raise RSVBridgeUnavailable("source id is not safe for bridge config lookup")
        executable_sha256 = self._verify_executable()
        temporary: tempfile.TemporaryDirectory[str] | None = None
        if self._config_secret_loader is not None or self._config_secret_ref is not None:
            if self._config_secret_loader is None or not self._config_secret_ref:
                raise RSVBridgeUnavailable("secret-bound bridge config is incomplete")
            try:
                raw_config = await self._config_secret_loader(self._config_secret_ref)
                if not isinstance(raw_config, str) or len(raw_config.encode("utf-8")) > 65_536:
                    raise ValueError("bridge config secret is too large")
                parsed_config = json.loads(raw_config)
                if not isinstance(parsed_config, dict):
                    raise TypeError("bridge config secret must be a JSON object")
            except RSVBridgeUnavailable:
                raise
            except (OSError, TypeError, UnicodeError, ValueError, RuntimeError):
                raise RSVBridgeUnavailable("secret-bound bridge config is invalid") from None
            temporary = tempfile.TemporaryDirectory(prefix="erp-mcp-rsv-")
            config = Path(temporary.name) / f"{source.id}.json"
            config.write_text(
                json.dumps(parsed_config, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
        else:
            config = (self.config_root / f"{source.id}.json").resolve()
            if config.parent != self.config_root:
                raise RSVBridgeUnavailable("bridge config path escaped its configured root")
            if not config.is_file():
                raise RSVBridgeUnavailable("source bridge config is not installed")
        inherited = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP") if key in os.environ}
        parameters = StdioServerParameters(
            command=self.executable,
            args=["serve", "--config", str(config)],
            # Do not inherit credentials or ambient process configuration.
            env=inherited,
            cwd=str(Path(self.executable).parent),
        )
        return parameters, executable_sha256, temporary

    async def health(self, source: Source) -> dict[str, Any]:
        parameters, _executable_sha256, temporary = await self._parameters(source)
        try:
            async with (
                asyncio.timeout(self.timeout_seconds),
                self._stdio_factory(parameters) as (read_stream, write_stream),
                self._session_factory(read_stream, write_stream) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                if "ping" not in names or not names.issubset(self.UPSTREAM_TOOLS):
                    raise RSVBridgeUnavailable("upstream tool contract is not allowlisted")
                result = await session.call_tool("ping", {})
                if result.is_error:
                    raise RSVBridgeUnavailable("upstream ping failed")
            return {
                "status": "healthy",
                "source_id": source.id,
                "tool_names": sorted(names),
            }
        except RSVBridgeUnavailable:
            raise
        except TimeoutError:
            raise RSVBridgeUnavailable("upstream bridge health check timed out") from None
        except Exception as exc:  # noqa: BLE001
            # Do not forward subprocess stderr, connection strings, or upstream payloads.
            raise RSVBridgeUnavailable(
                f"upstream bridge health check failed ({type(exc).__name__})"
            ) from None
        finally:
            if temporary is not None:
                temporary.cleanup()

    async def metadata(
        self,
        source: Source,
        *,
        operation: str,
        arguments: dict[str, Any] | None = None,
        max_response_bytes: int = 1_000_000,
    ) -> dict[str, Any]:
        args = self._metadata_arguments(operation, arguments)
        parameters, executable_sha256, temporary = await self._parameters(source)
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with (
                    self._stdio_factory(parameters) as (read_stream, write_stream),
                    self._session_factory(read_stream, write_stream) as session,
                ):
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    if (
                        not METADATA_TOOLS.issubset(names)
                        or not names.issubset(self.UPSTREAM_TOOLS)
                    ):
                        raise RSVBridgeUnavailable("upstream tool contract is not allowlisted")
                    result = await session.call_tool(operation, args)
                    if result.is_error:
                        raise RSVBridgeUnavailable("upstream metadata operation failed")
                    text_blocks = []
                    for item in result.content:
                        if getattr(item, "type", None) != "text" or not isinstance(
                            getattr(item, "text", None), str
                        ):
                            raise RSVBridgeUnavailable("upstream metadata response type is unsupported")
                        text_blocks.append(item.text)
            content_bytes = sum(len(item.encode("utf-8")) for item in text_blocks)
            if content_bytes > max_response_bytes:
                raise RSVBridgeUnavailable("upstream metadata response exceeded configured limit")
            if len(text_blocks) == 1:
                try:
                    data: Any = json.loads(text_blocks[0])
                except json.JSONDecodeError:
                    data = text_blocks[0]
            else:
                data = text_blocks
            envelope = {
                "source_id": source.id,
                "adapter": {
                    "kind": "rsv_data_metadata",
                    "upstream_source_sha": UPSTREAM_SHA,
                    "executable_sha256": executable_sha256,
                },
                "operation": operation,
                "data": data,
            }
            if len(json.dumps(envelope, ensure_ascii=False).encode("utf-8")) > max_response_bytes:
                raise RSVBridgeUnavailable("normalized metadata response exceeded configured limit")
            return envelope
        except RSVBridgeUnavailable:
            raise
        except TimeoutError:
            raise RSVBridgeUnavailable("upstream bridge operation timed out") from None
        except Exception as exc:  # noqa: BLE001 - never return bridge stderr or payloads
            raise RSVBridgeUnavailable(
                f"upstream bridge metadata operation failed ({type(exc).__name__})"
            ) from None
        finally:
            if temporary is not None:
                temporary.cleanup()
