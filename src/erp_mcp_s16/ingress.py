"""Private-only S16 ASGI composition. Factory construction never binds or starts a listener."""
from __future__ import annotations

import inspect
import ipaddress
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

from business_ai_gateway.phase2.change.errors import ErrorCode, render

from .contracts import ApproverSession, AuthenticatedPrincipal, PrincipalRole, TokenClass

__all__ = ["PrivateNetworkConfig", "RouteAssessment", "create_private_s16_app"]


@dataclass(frozen=True, slots=True)
class PrivateNetworkConfig:
    origin: str
    allowed_networks: tuple[str, ...] = ("127.0.0.1/32", "::1/128")
    approval_prefix: str = "/approval/"
    tool_prefix: str = "/mcp"
    max_body_bytes: int = 1_048_576


@dataclass(frozen=True, slots=True)
class RouteAssessment:
    resolved_addresses: tuple[str, ...]
    redirects: bool = False
    proxy_used: bool = False
    unresolved: bool = False


class RouteProbePort(Protocol):
    def assess(self, address: str, *, port: int) -> RouteAssessment: ...


class RequestAuthenticator(Protocol):
    def authenticate(self, scope: Mapping[str, Any], headers: Mapping[str, str]) -> object | None: ...


_FORWARDED_NAMES = frozenset({"forwarded", "x-real-ip"})
_SECURITY_HEADERS = [
    (b"cache-control", b"no-store"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
]


def _safe_response(status: int, code: ErrorCode, *, html_response: bool = False
                   ) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    info = render(code)
    if html_response:
        body = ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><title>Request refused</title>"
                "<main><h1 tabindex=\"-1\">Request refused</h1><p>" +
                info.message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") +
                "</p></main></html>").encode("utf-8")
        headers = [(b"content-type", b"text/html; charset=utf-8"),
                   (b"content-security-policy", b"default-src 'none'; script-src 'none'; frame-ancestors 'none'")]
    else:
        body = json.dumps({"error": {"code": code.value, "message": info.message,
                                      "next_action": info.next_action.value}},
                          separators=(",", ":")).encode("utf-8")
        headers = [(b"content-type", b"application/json; charset=utf-8")]
    headers.extend(_SECURITY_HEADERS)
    headers.append((b"content-length", str(len(body)).encode("ascii")))
    return status, headers, body


async def _invoke(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    result = function(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


def _is_private(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return address.is_loopback or address.is_private


def _configured_networks(config: PrivateNetworkConfig) -> tuple[Any, ...]:
    if type(config.allowed_networks) is not tuple or not config.allowed_networks:
        raise ValueError("PRIVATE_NETWORK_CONFIG_INVALID")
    networks = tuple(ipaddress.ip_network(value, strict=True) for value in config.allowed_networks)
    if any(not _is_private(network.network_address) or not _is_private(network.broadcast_address)
           for network in networks):
        raise ValueError("PUBLIC_NETWORK_FORBIDDEN")
    return networks


def _allowed(address: ipaddress.IPv4Address | ipaddress.IPv6Address,
             networks: tuple[Any, ...]) -> bool:
    return _is_private(address) and any(address.version == net.version and address in net for net in networks)


def _host_matches(raw_host: str, server_host: str, server_port: int, scheme: str) -> bool:
    if not raw_host or any(ch.isspace() for ch in raw_host) or "%" in raw_host:
        return False
    try:
        parsed = urlsplit("//" + raw_host)
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return False
        host = parsed.hostname
        if not host:
            return False
        if ipaddress.ip_address(host) != ipaddress.ip_address(server_host):
            return False
        port = parsed.port
        if port is None:
            port = 443 if scheme == "https" else 80 if scheme == "http" else -1
        return port == server_port
    except (ValueError, TypeError):
        return False


def _same_origin(headers: Mapping[str, str], expected: str, *, required: bool) -> bool:
    origin = headers.get("origin")
    referer = headers.get("referer")
    if not origin and not referer:
        return not required
    target = urlsplit(expected)
    if origin:
        parsed_origin = urlsplit(origin)
        if (origin != f"{target.scheme}://{target.netloc}" or
                parsed_origin.scheme != target.scheme or parsed_origin.netloc != target.netloc):
            return False
    if referer:
        parsed_ref = urlsplit(referer)
        if (parsed_ref.scheme != target.scheme or parsed_ref.netloc != target.netloc or
                parsed_ref.username or parsed_ref.password or parsed_ref.fragment):
            return False
    return True


def _positive_identity(identity: object, *, approval: bool) -> bool:
    now = datetime.now(timezone.utc)
    if approval:
        return (type(identity) is ApproverSession
                and type(identity.principal) is AuthenticatedPrincipal
                and identity.principal.token_class is TokenClass.APPROVER_SESSION
                and PrincipalRole.APPROVER in identity.principal.roles
                and identity.principal.session_id == identity.session_id
                and identity.idle_expires_at.tzinfo is not None
                and identity.expires_at.tzinfo is not None
                and now < identity.idle_expires_at and now < identity.expires_at
                and identity.principal.expires_at.tzinfo is not None
                and now < identity.principal.expires_at)
    return (type(identity) is AuthenticatedPrincipal
            and identity.token_class is TokenClass.CHAT_WRITE
            and PrincipalRole.REQUESTER in identity.roles
            and identity.expires_at.tzinfo is not None and now < identity.expires_at)


def create_private_s16_app(tool_app: Callable[..., Any], approval_app: Callable[..., Any],
                           authenticator: RequestAuthenticator, route_probe: RouteProbePort,
                           config: PrivateNetworkConfig) -> Callable[..., Any]:
    """Compose the two isolated applications behind fail-closed per-request checks only."""
    if (type(config) is not PrivateNetworkConfig or type(config.origin) is not str):
        raise ValueError("PRIVATE_NETWORK_CONFIG_INVALID")
    origin = urlsplit(config.origin)
    if (origin.scheme != "https" or not origin.netloc or origin.path or origin.query or origin.fragment
            or origin.username or origin.password):
        raise ValueError("PRIVATE_ORIGIN_INVALID")
    try:
        origin_ip = ipaddress.ip_address(origin.hostname or "")
        origin_port = origin.port or 443
    except ValueError as exc:
        raise ValueError("PRIVATE_ORIGIN_INVALID") from exc
    if not _is_private(origin_ip) or not 1 <= origin_port <= 65535:
        raise ValueError("PRIVATE_ORIGIN_INVALID")
    networks = _configured_networks(config)
    if type(config.max_body_bytes) is not int or not 1 <= config.max_body_bytes <= 1_048_576:
        raise ValueError("REQUEST_LIMIT_INVALID")

    async def app(scope: Mapping[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        if scope.get("type") == "lifespan":
            while True:
                event = await receive()
                if event.get("type") == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event.get("type") == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope.get("type") != "http":
            return
        path = scope.get("path")
        is_approval = type(path) is str and path.startswith(config.approval_prefix)
        is_tool = type(path) is str and (path == config.tool_prefix or path.startswith(config.tool_prefix + "/"))
        html_response = bool(is_approval)
        response: tuple[int, list[tuple[bytes, bytes]], bytes] | None = None
        try:
            headers_seen: dict[str, list[str]] = {}
            for key, value in scope.get("headers", ()):
                name = key.decode("latin-1").casefold()
                headers_seen.setdefault(name, []).append(value.decode("latin-1"))
            headers = {key: values[0] for key, values in headers_seen.items() if len(values) == 1}
            if any(len(values) != 1 for values in headers_seen.values()):
                raise ValueError("DUPLICATE_HEADERS")
            if any(name in _FORWARDED_NAMES or name.startswith("x-forwarded-") for name in headers):
                raise ValueError("FORWARDED_HEADERS")
            if not (is_approval or is_tool):
                response = _safe_response(404, ErrorCode.REF_OUT_OF_SCOPE)
            else:
                client = scope.get("client")
                server = scope.get("server")
                if (type(client) is not tuple or len(client) != 2 or type(server) is not tuple or len(server) != 2
                        or type(client[0]) is not str or type(server[0]) is not str
                        or type(server[1]) is not int or not 1 <= server[1] <= 65535):
                    raise ValueError("ENDPOINT_INVALID")
                peer_ip = ipaddress.ip_address(client[0])
                server_ip = ipaddress.ip_address(server[0])
                if (scope.get("scheme") != "https" or not _allowed(peer_ip, networks)
                        or not _allowed(server_ip, networks) or server_ip != origin_ip
                        or server[1] != origin_port):
                    raise ValueError("PUBLIC_ENDPOINT")
                hosts = headers_seen.get("host", [])
                if len(hosts) != 1 or not _host_matches(hosts[0], server[0], server[1],
                                                        str(scope.get("scheme", ""))):
                    raise ValueError("HOST_MISMATCH")
                if not _same_origin(headers, config.origin,
                                    required=is_approval and scope.get("method") == "POST"):
                    raise PermissionError("ORIGIN_INVALID")
                if scope.get("method") == "POST":
                    lengths = headers_seen.get("content-length", [])
                    if len(lengths) > 1 or (lengths and
                            (not lengths[0].isascii() or not lengths[0].isdecimal() or
                             int(lengths[0]) > config.max_body_bytes)):
                        raise ValueError("BODY_LIMIT")
                assessment = await _invoke(route_probe.assess, str(server_ip), port=server[1])
                if (type(getattr(assessment, "resolved_addresses", None)) is not tuple
                        or type(getattr(assessment, "unresolved", None)) is not bool
                        or type(getattr(assessment, "redirects", None)) is not bool
                        or type(getattr(assessment, "proxy_used", None)) is not bool
                        or assessment.unresolved or assessment.redirects or assessment.proxy_used
                        or assessment.resolved_addresses != (str(server_ip),)):
                    raise ValueError("ROUTE_NOT_PRIVATE")
                identity = await _invoke(authenticator.authenticate, scope, headers)
                if not _positive_identity(identity, approval=is_approval):
                    raise PermissionError("AUTHENTICATION_REQUIRED")
                downstream = approval_app if is_approval else tool_app
                redirect_started = False

                async def protected_send(message: Mapping[str, Any]) -> None:
                    nonlocal redirect_started
                    if message.get("type") == "http.response.start":
                        status = message.get("status")
                        if type(status) is int and 300 <= status < 400:
                            redirect_started = True
                            code, out_headers, body = _safe_response(403, ErrorCode.NOT_ENTITLED,
                                                                     html_response=html_response)
                            await send({"type": "http.response.start", "status": code, "headers": out_headers})
                            await send({"type": "http.response.body", "body": body})
                            return
                    if not redirect_started:
                        await send(message)

                await _invoke(downstream, scope, receive, protected_send)
                return
        except PermissionError:
            response = _safe_response(403, ErrorCode.NOT_ENTITLED, html_response=html_response)
        except Exception:
            response = _safe_response(400, ErrorCode.SCHEMA_INVALID, html_response=html_response)
        status, out_headers, body = response or _safe_response(400, ErrorCode.SCHEMA_INVALID,
                                                               html_response=html_response)
        await send({"type": "http.response.start", "status": status, "headers": out_headers})
        await send({"type": "http.response.body", "body": body})

    return app

