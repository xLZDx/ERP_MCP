"""Private-only MCP and approval-page composition for the isolated S16 surface.

The returned ASGI application is separate from the public ERP_MCP app. It exposes the
immutable S16 tool manifest only behind the private ingress guard and requires that guard's
per-request TEST principal before dispatch. This module never binds a socket or starts a
service; the host must explicitly serve the returned app on a private listener.
"""
from __future__ import annotations

import json
import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, Tool as MCPTool, ToolAnnotations

from business_ai_gateway.phase2.change.errors import ErrorCode
from .approval_page import ApproverSessionAuthenticator, ApprovalServicePort, Clock, create_approval_app
from .com_apply_port import S14ComDraftApplyPort
from .contracts import DomainReceipt, Result
from .ingress import (
    ExactPrivateListenerRouteProbe,
    PrivateNetworkConfig,
    RequestAuthenticator,
    RouteProbePort,
    create_private_s16_app,
    current_private_identity,
    private_listener_binding,
)
from .tools import ChangeServicePort, S16_TOOL_MANIFEST, ToolSpec, register_s16_tools


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(child) for key, child in value.items()}
    if type(value) in (list, tuple):
        return [_plain(child) for child in value]
    return value


class _PrivateGatewayApp:
    """ASGI wrapper carrying the optional S14 lane used by the listener lifecycle."""

    def __init__(self, app: Callable[..., Any], *, com_lane: object | None = None) -> None:
        self._app = app
        self.com_lane = com_lane

    async def __call__(self, scope, receive, send) -> None:
        await self._app(scope, receive, send)


class _OffLoopApplyService:
    """Keep synchronous S16 policy/storage work and the STA wait off the ASGI event loop."""

    def __init__(self, service: ChangeServicePort, *, s14_fingerprint: str) -> None:
        self._service = service
        self._s14_fingerprint = s14_fingerprint

    def __getattr__(self, name: str) -> object:
        return getattr(self._service, name)

    async def apply(self, requester, change_id, *, now=None):
        status = await asyncio.to_thread(self._service.status, requester, change_id)
        if (type(status) is Result and status.error is None
                and type(status.value) is DomainReceipt):
            proposal = status.value.proposal
            if (proposal.kind.value != "CREATE_DRAFT"
                    or status.value.scope.target_class != "TEST"
                    or status.value.scope.base_fingerprint != self._s14_fingerprint):
                return Result.refused(ErrorCode.SHAPE_NOT_QUALIFIED)
        return await asyncio.to_thread(
            self._service.apply, requester, change_id, **({} if now is None else {"now": now}),
        )


class _PrivateS16MCPServer(MCPServer):
    """MCP SDK transport bridge that preserves the S16 manifest's exact JSON schemas."""

    def __init__(self, *, origin: str, tool_path: str, max_body_bytes: int) -> None:
        super().__init__(
            name="ERP_MCP_S16_Private",
            title="ERP_MCP private S16 TEST tools",
            description="Private TEST-only S16 proposal and change tools.",
            instructions=("This is a private TEST-lane change surface. Use only the authenticated "
                          "scope returned for the current principal. Approval is performed only "
                          "through the separate approver page."),
        )
        parsed = urlsplit(origin)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("PRIVATE_ORIGIN_INVALID")
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._specs: dict[str, ToolSpec] = {}
        self._transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[parsed.netloc],
            allowed_origins=[origin],
        )
        self._tool_path = tool_path
        self._max_body_bytes = max_body_bytes

    def register_tool(self, name: str, handler: Callable[..., Any], schema: Mapping[str, object],
                      annotations: Mapping[str, bool]) -> None:
        expected = next((spec for spec in S16_TOOL_MANIFEST if spec.name == name), None)
        if (type(name) is not str or not name or name in self._handlers
                or not callable(handler) or not isinstance(schema, Mapping)
                or not isinstance(annotations, Mapping) or expected is None
                or _plain(schema) != _plain(expected.input_schema)
                or _plain(annotations) != _plain(expected.annotations)):
            raise ValueError("S16_TOOL_REGISTRATION_INVALID")
        self._handlers[name] = handler
        self._specs[name] = expected

    async def list_tools(self) -> list[MCPTool]:
        return [
            MCPTool(
                name=spec.name,
                description=spec.description,
                inputSchema=_plain(spec.input_schema),  # type: ignore[arg-type]
                annotations=ToolAnnotations(
                    readOnlyHint=spec.annotations.get("readOnlyHint"),
                    destructiveHint=spec.annotations.get("destructiveHint"),
                    openWorldHint=spec.annotations.get("openWorldHint"),
                ),
            )
            for spec in self._specs.values()
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any], context=None) -> CallToolResult:
        handler = self._handlers.get(name)
        if handler is None:
            payload: dict[str, object] = {"isError": True, "error": {"code": "SCHEMA_INVALID"}}
        else:
            payload = await handler(arguments, current_private_identity())
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return CallToolResult(
            content=[TextContent(text=encoded)],
            structuredContent=payload,
            isError=payload.get("isError") is True,
        )

    def streamable_http_app(self):
        return super().streamable_http_app(
            streamable_http_path=self._tool_path,
            json_response=True,
            max_request_body_size=self._max_body_bytes,
            transport_security=self._transport_security,
        )


def create_private_s16_gateway_app(
        *,
        change_service: ChangeServicePort,
        approval_service: ApprovalServicePort,
        request_authenticator: RequestAuthenticator,
        approver_session_authenticator: ApproverSessionAuthenticator,
        route_probe: RouteProbePort | None = None,
        config: PrivateNetworkConfig,
        clock: Clock,
        s14_apply_port: S14ComDraftApplyPort | None = None) -> Callable[..., Any]:
    """Compose the real MCP SDK transport behind S16's private per-request ingress.

    The caller supplies TEST-only S16 services and authenticators. The returned app is not
    mounted into the public R1 gateway; bind it only with ``serve_private_s16_gateway``.
    """
    if type(config) is not PrivateNetworkConfig:
        raise ValueError("PRIVATE_NETWORK_CONFIG_INVALID")
    com_lane = None
    if s14_apply_port is not None:
        if type(s14_apply_port) is not S14ComDraftApplyPort:
            raise ValueError("S16_S14_COM_COMPOSITION_INVALID")
        lane = getattr(s14_apply_port, "lane", None)
        bind = getattr(getattr(change_service, "core", None), "bind_private_apply_port", None)
        if lane is None or not callable(getattr(lane, "start", None)) or not callable(bind):
            raise ValueError("S16_S14_COM_COMPOSITION_INVALID")
        try:
            bind(s14_apply_port)
        except (RuntimeError, ValueError):
            raise ValueError("S16_S14_COM_COMPOSITION_INVALID") from None
        fingerprint = getattr(s14_apply_port, "expected_base_fingerprint", None)
        if type(fingerprint) is not str:
            raise ValueError("S16_S14_COM_COMPOSITION_INVALID")
        change_service = _OffLoopApplyService(change_service, s14_fingerprint=fingerprint)
        com_lane = lane
    if route_probe is None:
        route_probe = ExactPrivateListenerRouteProbe(config.origin)
    server = _PrivateS16MCPServer(
        origin=config.origin, tool_path=config.tool_prefix, max_body_bytes=config.max_body_bytes,
    )
    register_s16_tools(
        server,
        change_service,
        lambda _context: current_private_identity(),
    )
    tool_app = server.streamable_http_app()
    approval_app = create_approval_app(
        approval_service,
        approver_session_authenticator,
        origin=config.origin,
        clock=clock,
    )
    app = create_private_s16_app(
        tool_app,
        approval_app,
        request_authenticator,
        route_probe,
        config,
        lifespan_app=tool_app,
    )
    return _PrivateGatewayApp(app, com_lane=com_lane)


async def serve_private_s16_gateway(
        app: Callable[..., Any], *, config: PrivateNetworkConfig,
        certificate_file: str, private_key_file: str) -> None:
    """Bind the composed S16 app to its exact private HTTPS origin until shutdown.

    Wildcard, public, mismatched-host, mismatched-port, and missing-TLS configurations fail
    closed before Uvicorn is started. The public R1 app has no reference to this listener.
    """
    if (not callable(app) or type(config) is not PrivateNetworkConfig
            or type(certificate_file) is not str or type(private_key_file) is not str
            or not certificate_file or not private_key_file):
        raise ValueError("PRIVATE_LISTENER_CONFIG_INVALID")
    try:
        host, port, _ = private_listener_binding(config)
    except (TypeError, ValueError):
        raise ValueError("PRIVATE_LISTENER_CONFIG_INVALID") from None
    cert_path = Path(certificate_file)
    key_path = Path(private_key_file)
    if (not cert_path.is_absolute() or not key_path.is_absolute()
            or not cert_path.is_file() or not key_path.is_file()
            or cert_path.resolve() == key_path.resolve()):
        raise ValueError("PRIVATE_LISTENER_TLS_FILES_INVALID")
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(
        app,
        host=str(host),
        port=port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        access_log=False,
    ))
    com_lane = getattr(app, "com_lane", None)
    lane_started = False
    try:
        if com_lane is not None:
            await com_lane.start()
            lane_started = True
        await server.serve()
    finally:
        if lane_started:
            await com_lane.close_after_drain()
