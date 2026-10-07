"""Loopback ASGI app: bearer auth, strict request validation, exact binding match, company allow-list."""
from __future__ import annotations

import asyncio
import datetime as dt
import hmac
import json
import logging
from collections.abc import Callable
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .config import GUID_RE, ID_RE, BridgeConfig
from .errors import (
    COM_BAD_REQUEST,
    COM_BINDING_MISMATCH,
    COM_COMPANY_DENIED,
    COM_INTERNAL,
    COM_UNAUTHORIZED,
    COM_UNAVAILABLE,
    STATUS_BY_CODE,
    BridgeFault,
)
from .runtime import ComRuntime, dpapi_decrypt_file
from .session import BalanceJob, BindingSession

log = logging.getLogger("onec_com_bridge")

MAX_BODY_BYTES = 64 * 1024

_Id = Annotated[str, StringConstraints(pattern=ID_RE.pattern)]
_Guid = Annotated[str, StringConstraints(pattern=GUID_RE.pattern)]


class BalanceRequest(BaseModel):
    """The only caller-controlled input. There is deliberately no field for a path, secret, user, route or text."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    binding_id: _Id
    binding_version: Annotated[int, Field(ge=1)]
    source_id: _Id
    as_of: str
    company_external_ref: _Guid
    account_keys: Annotated[list[_Guid], Field(min_length=1, max_length=16)]
    max_rows: Annotated[int, Field(ge=1, le=5000)]

    @field_validator("as_of")
    @classmethod
    def _offset_datetime(cls, value: str) -> str:
        parsed = dt.datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("as_of needs an explicit offset")
        if not 1990 <= parsed.year <= 2100:
            raise ValueError("as_of is outside the supported range")
        return value

    @field_validator("account_keys")
    @classmethod
    def _distinct(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("account keys must be distinct")
        return value


def _error(code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=STATUS_BY_CODE[code])


def create_app(
    config: BridgeConfig,
    *,
    token: str,
    runtime: ComRuntime,
    secret_loader: Callable[[str], str] = dpapi_decrypt_file,
) -> Starlette:
    expected = token.encode("utf-8")
    sessions = {
        b.binding_id: BindingSession(b, runtime, secret_loader, config.call_timeout_seconds)
        for b in config.bindings
    }

    def authorised(request: Request) -> bool:
        header = request.headers.get("authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer":
            return False
        return hmac.compare_digest(supplied.encode("utf-8"), expected)

    async def healthz(_: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def identity(request: Request) -> Response:
        if not authorised(request):
            return _error(COM_UNAUTHORIZED)
        binding = config.binding(request.query_params.get("binding_id", ""))
        if binding is None:
            return _error(COM_BINDING_MISMATCH)
        return JSONResponse(
            {
                "binding_id": binding.binding_id,
                "binding_version": binding.version,
                "source_id": binding.source_id,
                "clone_identity": binding.clone_identity,
                "metadata_fingerprint": binding.metadata_fingerprint,
            }
        )

    async def balance(request: Request) -> Response:
        if not authorised(request):
            return _error(COM_UNAUTHORIZED)
        try:
            declared = request.headers.get("content-length", "")
            if not declared.isdigit() or int(declared) > MAX_BODY_BYTES:
                raise BridgeFault(COM_BAD_REQUEST)  # refused before any byte of the body is read
            body = await request.body()
            if len(body) > MAX_BODY_BYTES:
                raise BridgeFault(COM_BAD_REQUEST)
            try:
                payload: Any = json.loads(body)
                req = BalanceRequest.model_validate(payload)
            except (ValueError, ValidationError):
                raise BridgeFault(COM_BAD_REQUEST) from None
            binding = config.binding(req.binding_id)
            if (
                binding is None
                or binding.version != req.binding_version
                or binding.source_id != req.source_id
            ):
                raise BridgeFault(COM_BINDING_MISMATCH)
            if req.company_external_ref not in binding.allowed_company_refs:
                raise BridgeFault(COM_COMPANY_DENIED)  # before any COM call
            if binding.metadata_fingerprint is None:
                raise BridgeFault(COM_UNAVAILABLE)  # the response contract needs an attested fingerprint
            job = BalanceJob(
                as_of=dt.datetime.fromisoformat(req.as_of),
                company_ref=req.company_external_ref,
                account_keys=tuple(req.account_keys),
                max_rows=req.max_rows,
            )
            rows, truncated = await asyncio.to_thread(sessions[binding.binding_id].fetch, job)
        except BridgeFault as fault:
            log.info("balance refused code=%s", fault.code)
            return _error(fault.code)
        except Exception as exc:  # noqa: BLE001
            log.error("balance failed (%s)", type(exc).__name__)
            return _error(COM_INTERNAL)
        log.info("balance ok binding=%s rows=%d truncated=%s", binding.binding_id, len(rows), truncated)
        return JSONResponse(
            {
                "binding_id": binding.binding_id,
                "binding_version": binding.version,
                "source_id": binding.source_id,
                "base_identity": {
                    "clone_identity": binding.clone_identity,
                    "metadata_fingerprint": binding.metadata_fingerprint,
                },
                "rows": rows,
                "truncated": truncated,
            }
        )

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/v1/identity", identity, methods=["GET"]),
            Route("/v1/balance_by_analytics", balance, methods=["POST"]),
        ]
    )
