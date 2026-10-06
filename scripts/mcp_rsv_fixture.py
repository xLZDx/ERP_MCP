"""Test-only official SDK server; never connects to 1C or registers query/write tools."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer


def main() -> None:
    mode, config_path, marker_path = sys.argv[1:4]
    configuration = json.loads(Path(config_path).read_text(encoding="utf-8"))
    server = MCPServer("synthetic-rsv-lifecycle", log_level="CRITICAL")

    @server.tool()
    async def ping() -> dict[str, str]:
        Path(marker_path).write_text(mode, encoding="utf-8")
        if mode == "crash":
            os._exit(17)  # Intentional crash in a disposable test process.
        if mode == "malformed":
            sys.stdout.write('{"jsonrpc":"2.0","id":0,"result":[]}\n')
            sys.stdout.flush()
        if mode in {"timeout", "malformed"}:
            await asyncio.Event().wait()
        return {"status": "healthy"}

    @server.tool()
    def config() -> dict[str, int]:
        return {"generation": configuration["generation"]}

    @server.tool()
    def describe() -> str:
        return "synthetic metadata"

    @server.tool()
    def get_structure(object: str) -> str:
        return "synthetic metadata"

    @server.tool()
    def help() -> str:
        return "synthetic metadata"

    server.run(transport="stdio")


if __name__ == "__main__":
    main()
