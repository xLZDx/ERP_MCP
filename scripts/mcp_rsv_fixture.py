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
    # The locked SDK diverts handler stdout to stderr while serving. Keep the original wire
    # descriptor only in this fixture so intentional malformed/flood DATA really reaches it.
    wire = os.fdopen(os.dup(sys.stdout.fileno()), 'w', encoding='utf-8')
    server = MCPServer("synthetic-rsv-lifecycle", log_level="CRITICAL")

    @server.tool()
    async def ping() -> dict[str, str]:
        Path(marker_path).write_text(mode, encoding="utf-8")
        if mode == "crash":
            os._exit(17)  # Intentional crash in a disposable test process.
        if mode == "malformed":
            wire.write('{"jsonrpc":"2.0","id":0,"result":[]}\n')
            wire.flush()
        if mode == "wire_flood":
            # Adversarial stdout DATA only in this owned fixture process; no JSON framing fork.
            wire.write('{"private":"WIRE_PRIVATE_SECRET_' + 'x' * 6_000_000)
            wire.flush()
        if mode == 'wire_oversized_json':
            return {'status': 'healthy', 'private': 'WIRE_PRIVATE_SECRET_' + 'x' * 6_000_000}
        if mode in {"timeout", "malformed", "wire_flood"}:
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

    try:
        server.run(transport="stdio")
    finally:
        wire.close()


if __name__ == "__main__":
    main()
