"""MCP server (streamable HTTP) exposing the Phase 2 test-lane tools.

Run: ``python -m testlane.phase2_mcp`` (see the design document for environment variables).
Read-only: every tool only reads two gateways and compares in memory.
"""
from __future__ import annotations

import asyncio
import hmac
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .config import ServerConfig, load_config
from .gateway_client import Gateway, GatewayPort
from .reconcile import Reconciler, capabilities

_READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                             openWorldHint=True)

INSTRUCTIONS = (
    "Phase 2 test lane (EVALUATION_ONLY, Release 2 NO-GO). Read-only comparison of two copies of "
    "one 1C base through their Release 1 gateways using Release 2 reference modules. A MATCH is "
    "numeric agreement of two machine reads, never a native 1C PASS. INCONCLUSIVE means the data "
    "was incomplete; never present it as agreement. Amounts and names are hidden unless "
    "show_values=true is passed explicitly. as_of, start_period and end_period need a timezone "
    "offset, e.g. 2026-08-31T23:59:59+03:00."
)


def build_server(reconciler: Reconciler, config_state: dict[str, bool]) -> MCPServer:
    mcp = MCPServer("Phase 2 test lane", instructions=INSTRUCTIONS)

    @mcp.tool(annotations=_READ_ONLY)
    async def phase2_capabilities() -> dict[str, Any]:
        """List the Phase 2 reference modules, their status ceiling and what this lane covers."""
        return capabilities(config_state)

    @mcp.tool(annotations=_READ_ONLY)
    async def phase2_reconcile_two_bases(
        company_id: str, as_of: str, start_period: str, end_period: str,
        show_values: bool = False,
    ) -> dict[str, Any]:
        """Compare base A (reference) and base B through R2 reconciliation.

        Returns a six-column per-account R2 comparison, a PARTIAL 521.1 closing-balance comparison
        and a purchase-documents section (NOT_SUPPORTED when the shape does not allow R2).
        """
        return await asyncio.to_thread(
            reconciler.reconcile_two_bases, company_id, as_of, start_period, end_period, show_values)

    @mcp.tool(annotations=_READ_ONLY)
    async def phase2_reconcile_negative_control(
        company_id: str, start_period: str, end_period: str,
        delta: str = "1", measure: str = "closing_debit", show_values: bool = False,
    ) -> dict[str, Any]:
        """SYNTHETIC_NEGATIVE_CONTROL: perturb one side-B row in memory and show R2 finds it."""
        return await asyncio.to_thread(
            reconciler.negative_control, company_id, start_period, end_period, delta, measure,
            show_values)

    return mcp


class BearerGuard:
    """Pure ASGI guard: requires ``Authorization: Bearer <token>`` on every HTTP request."""

    def __init__(self, app: Any, token: str) -> None:
        self._app, self._token = app, token.encode()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            supplied = b""
            for name, value in scope.get("headers", []):
                if name == b"authorization" and value[:7].lower() == b"bearer ":
                    supplied = value[7:]
            if not hmac.compare_digest(supplied, self._token):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await self._app(scope, receive, send)


def build_app(config: ServerConfig, side_a: GatewayPort | None = None,
              side_b: GatewayPort | None = None) -> Any:
    a = side_a or Gateway(config.side_a)
    b = side_b or Gateway(config.side_b)
    state = {"side_a_configured": config.side_a.configured,
             "side_b_configured": config.side_b.configured}
    mcp = build_server(Reconciler(a, b, config.source_id), state)
    security = None
    if config.allowed_hosts:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=list(config.allowed_hosts))
    app = mcp.streamable_http_app(host=config.host, transport_security=security)
    return BearerGuard(app, config.inbound_token) if config.inbound_token else app


def main() -> None:
    import uvicorn

    config = load_config()
    if config.host not in ("127.0.0.1", "localhost", "::1") and not config.inbound_token:
        raise SystemExit("REFUSED: non-loopback bind requires TESTLANE_INBOUND_TOKEN")
    uvicorn.run(build_app(config), host=config.host, port=config.port,
                log_level="warning", access_log=False)
