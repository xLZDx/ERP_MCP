"""Black-box smoke for the local ChatGPT-facing MCP endpoint."""
from __future__ import annotations

import argparse
import asyncio
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

REQUIRED_TOOLS = {
    "system_status",
    "sources_list",
    "companies_list",
    "source_health",
    "onec_capabilities",
    "onec_metadata_summary",
    "onec_find_entities",
    "onec_read",
    "sales_documents",
    "purchase_documents",
    "receivable_aging",
    "payable_aging",
    "inventory_balance",
    "inventory_movements",
    "cash_movements",
    "bank_balance",
    "accounting_balance_and_turnovers",
    "accounting_posting_rows",
    "counterparty_duplicate_candidates",
}


async def run(url: str) -> None:
    async with (
        streamable_http_client(url) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        response = await session.list_tools()
        tools = {tool.name: tool for tool in response.tools}
        missing = sorted(REQUIRED_TOOLS - set(tools))
        if missing:
            raise RuntimeError(f"missing ChatGPT tools: {missing}")

        unsafe = []
        for name, tool in tools.items():
            annotations = tool.annotations
            if annotations is None:
                unsafe.append(f"{name}: annotations missing")
                continue
            if annotations.read_only_hint is not True:
                unsafe.append(f"{name}: readOnlyHint != true")
            if annotations.destructive_hint is not False:
                unsafe.append(f"{name}: destructiveHint != false")
        if unsafe:
            raise RuntimeError("; ".join(unsafe))

        status = await session.call_tool("system_status", {})
        if status.is_error:
            raise RuntimeError("system_status returned an MCP error")
        sources = await session.call_tool("sources_list", {})
        if sources.is_error:
            raise RuntimeError("sources_list returned an MCP error")

        print(
            json.dumps(
                {
                    "status": "PASS",
                    "endpoint": url,
                    "tool_count": len(tools),
                    "all_tools_read_only": True,
                    "system_status": "PASS",
                    "sources_list": "PASS",
                },
                indent=2,
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:18100/mcp")
    args = parser.parse_args()
    asyncio.run(run(args.url))


if __name__ == "__main__":
    main()
