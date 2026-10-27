"""Loopback-only HTTP adapter for the isolated private writer process.

The factory creates an ASGI application but never starts it. Deployment must still delay listener
startup until durable recovery is complete and all qualification gates pass.
"""
from __future__ import annotations

import ipaddress
import json
import math
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from business_ai_gateway.phase2.change_ledger.write_port import ApplyTicket, DispatchPermit

from .json_preflight import (
    MAX_JSON_DOCUMENT_DEPTH,
    MAX_JSON_DOCUMENT_STRUCTURAL_NODES,
    check_json_document_limits,
)
from .private_auth import (
    PrivateWriterAuthenticationError,
    PrivateWriterAuthenticator,
    PrivateWriterCaller,
)
from .private_authorization import (
    ConfiguredPrivateWriterAuthorizer,
    PrivateWriterAuthorizationUnavailable,
)
from .runtime_composition import PrivateWriterRuntime
from .service import CallSnapshot, PrivateWriterService, ServiceError

_MAX_REQUEST_BYTES = 1_048_576
_CONFLICT_CODES = frozenset({
    "CALL_IDENTITY_INVALID",
    "CALL_IDENTITY_CONFLICT",
    "CALL_SCOPE_INVALID",
    "OPERATION_UNSUPPORTED",
    "BASE_FINGERPRINT_MISMATCH",
    "STALE_EPOCH",
    "STARTUP_RECOVERY_REQUIRED",
})


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _ApplyTicketBody(_StrictModel):
    change_id: StrictStr
    generation: StrictInt
    call_id: StrictStr
    kind: StrictStr
    tenant_id: StrictStr
    company_id: StrictStr
    organization: StrictStr
    base_fingerprint: StrictStr
    target_ref: StrictStr | None
    target_version: StrictStr | None
    digest_set_hash: StrictStr
    repair_authorization_id: StrictStr | None
    approved_payload_digest: StrictStr | None


class _DispatchPermitBody(_StrictModel):
    permit_id: StrictStr
    permit_digest: StrictStr
    change_id: StrictStr
    generation: StrictInt
    call_id: StrictStr
    expires_at: StrictStr
    checkpoint_seq: StrictInt
    signer_key_id: StrictStr
    signature: StrictStr
    repair_authorization_id: StrictStr | None
    lifecycle_epoch: StrictInt


class _DispatchBody(_StrictModel):
    ticket: _ApplyTicketBody
    permit: _DispatchPermitBody
    payload: dict[str, Any]


class _LookupBody(_StrictModel):
    ticket: _ApplyTicketBody
    permit: _DispatchPermitBody


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> None:
    raise ValueError("NONFINITE_JSON_NUMBER")


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("NONFINITE_JSON_NUMBER")
    return parsed


def _private_loopback_request(request: Request) -> bool:
    client = request.client
    server = request.scope.get("server")
    hosts = request.headers.getlist("host")
    if any(
        name.casefold() == "forwarded"
        or name.casefold() == "x-real-ip"
        or name.casefold().startswith("x-forwarded-")
        for name, _ in request.headers.items()
    ):
        # ASGI proxy middleware can rewrite scope['client'] from these caller-controlled
        # headers. A forwarded peer is not proof of the socket peer required by this boundary.
        return False
    if (client is None or type(server) is not tuple or len(server) != 2
            or len(hosts) != 1):
        return False
    try:
        server_host, server_port = server
        if (type(server_host) is not str or not server_host or "%" in server_host
                or type(server_port) is not int or not 1 <= server_port <= 65535
                or not ipaddress.ip_address(server_host).is_loopback):
            return False
        server_address = ipaddress.ip_address(server_host)
        if "%" in client.host:
            return False
        if not ipaddress.ip_address(client.host).is_loopback:
            return False
        raw_host = hosts[0]
        if not raw_host or any(character.isspace() for character in raw_host):
            return False
        parsed = urlsplit(f"//{raw_host}")
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            return False
        if not parsed.hostname or "%" in parsed.hostname:
            return False
        host_address = ipaddress.ip_address(parsed.hostname)
        if not host_address.is_loopback or host_address != server_address:
            return False
        host_port = parsed.port
        if host_port is None:
            if request.url.scheme == "https":
                host_port = 443
            elif request.url.scheme == "http":
                host_port = 80
            else:
                return False
        if not 1 <= host_port <= 65535 or host_port != server_port:
            return False
        return True
    except (ValueError, TypeError):
        return False


async def _read_bounded_json(request: Request) -> Any:
    content_types = request.headers.getlist("content-type")
    if len(content_types) != 1:
        raise ValueError("INVALID_CONTENT_TYPE")
    content_type_parts = [part.strip() for part in content_types[0].split(";")]
    if (
        content_type_parts[0].casefold() != "application/json"
        or len(content_type_parts) > 2
        or (
            len(content_type_parts) == 2
            and content_type_parts[1].casefold()
            not in {"charset=utf-8", 'charset="utf-8"'}
        )
    ):
        raise ValueError("INVALID_CONTENT_TYPE")

    lengths = request.headers.getlist("content-length")
    if len(lengths) > 1:
        raise ValueError("INVALID_CONTENT_LENGTH")
    if lengths:
        raw_length = lengths[0]
        if not raw_length.isascii() or not raw_length.isdecimal():
            raise ValueError("INVALID_CONTENT_LENGTH")
        # Compare decimal text before converting it. HTTP servers normally cap header
        # sizes, but parsing an attacker-controlled, very long decimal integer is
        # unnecessary work on the authenticated private ingress path.
        normalized_length = raw_length.lstrip("0") or "0"
        max_length = str(_MAX_REQUEST_BYTES)
        if (len(normalized_length) > len(max_length)
                or (len(normalized_length) == len(max_length)
                    and normalized_length > max_length)):
            raise OverflowError("REQUEST_TOO_LARGE")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_REQUEST_BYTES:
            raise OverflowError("REQUEST_TOO_LARGE")
        body.extend(chunk)
    document = bytes(body).decode("utf-8")
    check_json_document_limits(
        document,
        max_depth=MAX_JSON_DOCUMENT_DEPTH,
        max_structural_nodes=MAX_JSON_DOCUMENT_STRUCTURAL_NODES,
    )
    return json.loads(
        document,
        object_pairs_hook=_duplicate_rejecting_object,
        parse_constant=_reject_json_constant,
        parse_float=_parse_finite_json_float,
    )


def _permit_value(body: _DispatchPermitBody) -> DispatchPermit:
    permit_data = body.model_dump()
    raw_expiry = permit_data["expires_at"]
    try:
        parsed_expiry = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError("INVALID_PERMIT_EXPIRY") from None
    if parsed_expiry.tzinfo is None or parsed_expiry.utcoffset() is None:
        raise ValueError("INVALID_PERMIT_EXPIRY")
    permit_data["expires_at"] = parsed_expiry
    return DispatchPermit(**permit_data)


def _dispatch_values(value: Any) -> tuple[ApplyTicket, DispatchPermit, dict[str, Any]]:
    body = _DispatchBody.model_validate(value)
    return ApplyTicket(**body.ticket.model_dump()), _permit_value(body.permit), body.payload


def _lookup_values(value: Any) -> tuple[ApplyTicket, DispatchPermit]:
    body = _LookupBody.model_validate(value)
    return ApplyTicket(**body.ticket.model_dump()), _permit_value(body.permit)


def _call_result(snapshot: CallSnapshot) -> dict[str, Any]:
    if type(snapshot) is not CallSnapshot:
        raise ServiceError("OUTCOME_LOOKUP_INVALID")
    identity = snapshot.identity
    return {
        "call_id": identity.call_id,
        "generation": identity.generation,
        "operation": identity.operation,
        "state": snapshot.state.value,
    }


def create_private_writer_app(
    service: PrivateWriterService,
    authenticator: PrivateWriterAuthenticator,
    *,
    call_authorizer: ConfiguredPrivateWriterAuthorizer,
    runtime: PrivateWriterRuntime,
) -> Starlette:
    """Create a loopback-only app bound to its drainable runtime lifecycle."""
    if type(service) is not PrivateWriterService:
        raise ValueError("PRIVATE_WRITER_SERVICE_REQUIRED")
    if type(authenticator) is not PrivateWriterAuthenticator:
        raise ValueError("PRIVATE_WRITER_AUTHENTICATOR_REQUIRED")
    if type(call_authorizer) is not ConfiguredPrivateWriterAuthorizer:
        raise ValueError("PRIVATE_WRITER_CALL_AUTHORIZER_REQUIRED")
    if type(runtime) is not PrivateWriterRuntime or runtime.service is not service:
        raise ValueError("PRIVATE_WRITER_RUNTIME_MISMATCH")

    @asynccontextmanager
    async def lifespan(_app):
        # Startup recovery and release-gate evidence are explicit preconditions; ASGI lifespan
        # must not manufacture either. Refuse startup unless the caller prepared the runtime.
        try:
            if not runtime.service.ready:
                raise ServiceError("STARTUP_RECOVERY_REQUIRED")
            yield
        finally:
            # ASGI servers complete startup before accepting requests and stop accepting before
            # lifespan shutdown, so runtime drain/close follows listener shutdown.
            await runtime.close()

    async def authorize_dispatch(
        caller: PrivateWriterCaller,
        ticket: ApplyTicket,
        permit: DispatchPermit,
    ) -> Response | None:
        try:
            await call_authorizer.authorize_call(caller, ticket, permit)
        except PermissionError:
            return JSONResponse({"error": "CALL_NOT_AUTHORIZED"}, status_code=403)
        except PrivateWriterAuthorizationUnavailable:
            return JSONResponse({"error": "CALL_AUTHORIZATION_UNAVAILABLE"}, status_code=503)
        except Exception:
            return JSONResponse({"error": "CALL_AUTHORIZATION_UNAVAILABLE"}, status_code=503)
        return None

    def authorize_lookup(caller: PrivateWriterCaller, ticket: ApplyTicket) -> Response | None:
        try:
            call_authorizer.authorize_lookup(caller, ticket)
        except PermissionError:
            return JSONResponse({"error": "CALL_NOT_AUTHORIZED"}, status_code=403)
        except Exception:
            return JSONResponse({"error": "CALL_AUTHORIZATION_UNAVAILABLE"}, status_code=503)
        return None

    async def authorize(request: Request) -> PrivateWriterCaller | Response:
        if not _private_loopback_request(request):
            return JSONResponse({"error": "PRIVATE_LOOPBACK_REQUIRED"}, status_code=403)
        try:
            return await authenticator.authenticate(request.headers.getlist("authorization"))
        except PrivateWriterAuthenticationError as exc:
            status = 503 if exc.code == "AUTHENTICATION_UNAVAILABLE" else 401
            return JSONResponse({"error": exc.code}, status_code=status)

    async def dispatch(request: Request) -> Response:
        caller = await authorize(request)
        if isinstance(caller, Response):
            return caller
        if not service.ready:
            return JSONResponse({"error": "SERVICE_NOT_READY"}, status_code=503)
        try:
            body = await _read_bounded_json(request)
            ticket, permit, payload = _dispatch_values(body)
        except OverflowError:
            return JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413)
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError,
            ValidationError,
            RecursionError,
        ):
            return JSONResponse({"error": "INVALID_REQUEST"}, status_code=400)
        authorization_error = await authorize_dispatch(caller, ticket, permit)
        if authorization_error is not None:
            return authorization_error
        try:
            result = await service.dispatch(ticket, permit, payload)
            return JSONResponse({"call": _call_result(result)})
        except ServiceError as exc:
            status = 409 if exc.code in _CONFLICT_CODES else 503
            return JSONResponse(
                {"error": exc.code, "outcome_unknown": exc.outcome_unknown},
                status_code=status,
            )
        except Exception:
            return JSONResponse(
                {"error": "WRITER_OPERATION_UNAVAILABLE", "outcome_unknown": True},
                status_code=503,
            )

    async def lookup(request: Request) -> Response:
        caller = await authorize(request)
        if isinstance(caller, Response):
            return caller
        if not service.ready:
            return JSONResponse({"error": "SERVICE_NOT_READY"}, status_code=503)
        try:
            body = await _read_bounded_json(request)
            ticket, permit = _lookup_values(body)
        except OverflowError:
            return JSONResponse({"error": "REQUEST_TOO_LARGE"}, status_code=413)
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError,
            ValidationError,
            RecursionError,
        ):
            return JSONResponse({"error": "INVALID_REQUEST"}, status_code=400)
        authorization_error = authorize_lookup(caller, ticket)
        if authorization_error is not None:
            return authorization_error
        try:
            result = await service.lookup(ticket, permit)
            return JSONResponse({"call": _call_result(result)})
        except ServiceError as exc:
            status = 409 if exc.code in _CONFLICT_CODES else 503
            return JSONResponse({"error": exc.code}, status_code=status)
        except Exception:
            return JSONResponse({"error": "OUTCOME_LOOKUP_UNAVAILABLE"}, status_code=503)

    return Starlette(
        debug=False,
        lifespan=lifespan,
        routes=[
            Route("/v1/calls/dispatch", dispatch, methods=["POST"]),
            Route("/v1/calls/lookup", lookup, methods=["POST"]),
        ],
    )


def create_private_writer_runtime_app(
        runtime: PrivateWriterRuntime,
        authenticator: PrivateWriterAuthenticator,
        *,
        call_authorizer: ConfiguredPrivateWriterAuthorizer,
        ) -> Starlette:
    """Require prepared runtime readiness and bind drain close to ASGI lifespan."""
    if type(runtime) is not PrivateWriterRuntime:
        raise ValueError("PRIVATE_WRITER_RUNTIME_REQUIRED")
    return create_private_writer_app(
        runtime.service, authenticator, call_authorizer=call_authorizer, runtime=runtime,
    )


__all__ = ["create_private_writer_app", "create_private_writer_runtime_app"]
