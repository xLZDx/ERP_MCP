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

from .contracts import ApproverSession, AuthenticatedPrincipal, PrincipalRole, TargetScope, TokenClass
from .core import _as_utc, _valid_approver_session

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
_MAX_POST_REQUEST_MESSAGES = 8192
_SECURITY_HEADERS = [
    (b"cache-control", b"no-store"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
]


class _BodyLimitExceeded(ValueError):
    """Internal sentinel for the fixed HTTP 413 request-size response."""


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


def _valid_route_prefix(value: object, *, trailing_slash: bool) -> bool:
    if (type(value) is not str or not value.startswith("/")
            or value.endswith("/") != trailing_slash
            or "//" in value or "\\" in value or any(char in value for char in "?#%")
            or any(ord(char) < 33 or ord(char) == 127 for char in value)):
        return False
    segments = value[1:].split("/")
    if trailing_slash:
        segments.pop()
    return bool(segments) and all(segment not in ("", ".", "..") for segment in segments)


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
        if type(identity) is not ApproverSession or type(identity.principal) is not AuthenticatedPrincipal:
            return False
        principal = identity.principal
        scope = principal.scope
        if (principal.token_class is not TokenClass.APPROVER_SESSION
                or type(principal.principal_id) is not str or not principal.principal_id
                or type(principal.person_id) is not str or not principal.person_id
                or type(principal.epoch) is not int or principal.epoch < 0
                or type(principal.lane) is not str or principal.lane != "TEST"
                or type(scope) is not TargetScope
                or any(type(value) is not str or not value for value in (
                    scope.tenant, scope.company, scope.organization,
                    scope.base_fingerprint, scope.target_class))
                or scope.target_class != "TEST"
                or type(principal.roles) is not frozenset
                or any(type(role) is not PrincipalRole for role in principal.roles)
                or PrincipalRole.APPROVER not in principal.roles
                or principal.mfa_authenticated is not True
                or not _valid_approver_session(identity, principal, now)):
            return False
        principal_expires_at = _as_utc(principal.expires_at)
        return principal_expires_at is not None and principal_expires_at > now
    if (type(identity) is not AuthenticatedPrincipal
            or identity.token_class is not TokenClass.CHAT_WRITE
            or type(identity.roles) is not frozenset
            or any(type(role) is not PrincipalRole for role in identity.roles)
            or PrincipalRole.REQUESTER not in identity.roles
            or type(identity.principal_id) is not str or not identity.principal_id
            or type(identity.person_id) is not str or not identity.person_id
            or type(identity.epoch) is not int or identity.epoch < 0
            or type(identity.mfa_authenticated) is not bool
            or type(identity.lane) is not str or identity.lane != "TEST"
            or type(identity.scope) is not TargetScope
            or any(type(value) is not str or not value for value in (
                identity.scope.tenant, identity.scope.company, identity.scope.organization,
                identity.scope.base_fingerprint, identity.scope.target_class))
            or identity.scope.target_class != "TEST"):
        return False
    expires_at = _as_utc(identity.expires_at)
    return expires_at is not None and expires_at > now


def create_private_s16_app(tool_app: Callable[..., Any], approval_app: Callable[..., Any],
                           authenticator: RequestAuthenticator, route_probe: RouteProbePort,
                           config: PrivateNetworkConfig) -> Callable[..., Any]:
    """Compose the two isolated applications behind fail-closed per-request checks only."""
    if (type(config) is not PrivateNetworkConfig or type(config.origin) is not str):
        raise ValueError("PRIVATE_NETWORK_CONFIG_INVALID")
    approval_prefix = config.approval_prefix
    tool_prefix = config.tool_prefix
    approval_root = approval_prefix[:-1] if type(approval_prefix) is str else ""
    if (not _valid_route_prefix(approval_prefix, trailing_slash=True)
            or not _valid_route_prefix(tool_prefix, trailing_slash=False)
            or approval_root == tool_prefix
            or approval_root.startswith(tool_prefix + "/")
            or tool_prefix.startswith(approval_root + "/")):
        raise ValueError("PRIVATE_ROUTE_CONFIG_INVALID")
    origin = urlsplit(config.origin)
    if (origin.scheme != "https" or not origin.netloc or origin.path or origin.query or origin.fragment
            or origin.username or origin.password):
        raise ValueError("PRIVATE_ORIGIN_INVALID")
    try:
        origin_ip = ipaddress.ip_address(origin.hostname or "")
        configured_port = origin.port
        origin_port = 443 if configured_port is None else configured_port
    except ValueError as exc:
        raise ValueError("PRIVATE_ORIGIN_INVALID") from exc
    if not _is_private(origin_ip) or not 1 <= origin_port <= 65535:
        raise ValueError("PRIVATE_ORIGIN_INVALID")
    networks = _configured_networks(config)
    if type(config.max_body_bytes) is not int or not 1 <= config.max_body_bytes <= 1_048_576:
        raise ValueError("REQUEST_LIMIT_INVALID")

    async def app(scope: Mapping[str, Any], receive: Callable[..., Any], send: Callable[..., Any]) -> None:
        if type(scope) is not dict:
            status, response_headers, body = _safe_response(400, ErrorCode.SCHEMA_INVALID)
            await send({"type": "http.response.start", "status": status,
                        "headers": response_headers})
            await send({"type": "http.response.body", "body": body})
            return
        scope_type = scope.get("type")
        if type(scope_type) is not str:
            status, response_headers, body = _safe_response(400, ErrorCode.SCHEMA_INVALID)
            await send({"type": "http.response.start", "status": status,
                        "headers": response_headers})
            await send({"type": "http.response.body", "body": body})
            return
        if scope_type == "lifespan":
            while True:
                event = await receive()
                if event.get("type") == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif event.get("type") == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope_type != "http":
            return
        path = scope.get("path")
        method = scope.get("method")
        scheme = scope.get("scheme")
        is_approval = type(path) is str and path.startswith(config.approval_prefix)
        is_tool = type(path) is str and (path == config.tool_prefix or path.startswith(config.tool_prefix + "/"))
        html_response = bool(is_approval)
        response: tuple[int, list[tuple[bytes, bytes]], bytes] | None = None
        downstream_invoked = False
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
                if type(method) is not str or type(scheme) is not str:
                    raise ValueError("REQUEST_ROUTING_FIELDS_INVALID")
                client = scope.get("client")
                server = scope.get("server")
                if (type(client) not in (tuple, list) or len(client) != 2
                        or type(server) not in (tuple, list) or len(server) != 2
                        or type(client[0]) is not str or type(server[0]) is not str
                        or type(server[1]) is not int or not 1 <= server[1] <= 65535):
                    raise ValueError("ENDPOINT_INVALID")
                peer_ip = ipaddress.ip_address(client[0])
                server_ip = ipaddress.ip_address(server[0])
                if (scheme != "https" or not _allowed(peer_ip, networks)
                        or not _allowed(server_ip, networks) or server_ip != origin_ip
                        or server[1] != origin_port):
                    raise ValueError("PUBLIC_ENDPOINT")
                hosts = headers_seen.get("host", [])
                if len(hosts) != 1 or not _host_matches(hosts[0], server[0], server[1],
                                                        scheme):
                    raise ValueError("HOST_MISMATCH")
                if not _same_origin(headers, config.origin,
                                    required=is_approval and method == "POST"):
                    raise PermissionError("ORIGIN_INVALID")
                if method == "POST":
                    lengths = headers_seen.get("content-length", [])
                    if len(lengths) > 1:
                        raise _BodyLimitExceeded("BODY_LIMIT")
                    if lengths:
                        raw_length = lengths[0]
                        if not raw_length.isascii() or not raw_length.isdecimal():
                            raise ValueError("INVALID_CONTENT_LENGTH")
                        normalized_length = raw_length.lstrip("0") or "0"
                        max_length = str(config.max_body_bytes)
                        if (len(normalized_length) > len(max_length)
                                or (len(normalized_length) == len(max_length)
                                    and normalized_length > max_length)):
                            raise _BodyLimitExceeded("BODY_LIMIT")
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

                downstream_receive = receive
                if method == "POST":
                    # Content-Length is only an early rejection hint: chunked requests may omit it.
                    # Buffer the bounded body before entering either downstream app so no oversized
                    # request can be partially processed before the limit is noticed.
                    request_messages: list[Mapping[str, Any]] = []
                    body_size = 0
                    message_count = 0
                    while True:
                        request_message = await receive()
                        if request_message.get("type") == "http.disconnect":
                            raise ValueError("REQUEST_DISCONNECTED")
                        if request_message.get("type") != "http.request":
                            raise ValueError("REQUEST_MESSAGE_INVALID")
                        message_count += 1
                        if message_count > _MAX_POST_REQUEST_MESSAGES:
                            response = _safe_response(413, ErrorCode.SCHEMA_INVALID,
                                                      html_response=html_response)
                            break
                        chunk = request_message.get("body", b"")
                        if type(chunk) is not bytes:
                            raise ValueError("REQUEST_BODY_INVALID")
                        more_body = request_message.get("more_body", False)
                        if type(more_body) is not bool:
                            raise ValueError("REQUEST_MESSAGE_INVALID")
                        if len(chunk) > config.max_body_bytes - body_size:
                            response = _safe_response(413, ErrorCode.SCHEMA_INVALID,
                                                      html_response=html_response)
                            break
                        body_size += len(chunk)
                        # Empty intermediate chunks carry no payload and need not be replayed.
                        # Omitting them keeps memory bounded by body bytes, even if the server
                        # delivers an unusually large number of zero-length ASGI messages.
                        if chunk or not more_body:
                            request_messages.append(request_message)
                        if not more_body:
                            messages_remaining = iter(request_messages)

                            async def replay_receive() -> Mapping[str, Any]:
                                try:
                                    return next(messages_remaining)
                                except StopIteration:
                                    return await receive()

                            downstream_receive = replay_receive
                            break
                    if response is not None:
                        # The downstream application must not see any part of an oversized body.
                        pass
                    else:
                        downstream_invoked = True
                        await _invoke(downstream, scope, downstream_receive, protected_send)
                        return
                if method != "POST":
                    downstream_invoked = True
                    await _invoke(downstream, scope, receive, protected_send)
                    return
        except _BodyLimitExceeded:
            if downstream_invoked:
                raise
            response = _safe_response(413, ErrorCode.SCHEMA_INVALID, html_response=html_response)
        except PermissionError:
            if downstream_invoked:
                raise
            response = _safe_response(403, ErrorCode.NOT_ENTITLED, html_response=html_response)
        except Exception:
            if downstream_invoked:
                raise
            response = _safe_response(400, ErrorCode.SCHEMA_INVALID, html_response=html_response)
        status, out_headers, body = response or _safe_response(400, ErrorCode.SCHEMA_INVALID,
                                                               html_response=html_response)
        await send({"type": "http.response.start", "status": status, "headers": out_headers})
        await send({"type": "http.response.body", "body": body})

    return app

