"""Private acceptance service for independently persisted capability observations."""

from __future__ import annotations

import hmac
import json
import os
from contextlib import asynccontextmanager
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .db import Database
from .settings import Settings

ACCEPTOR_DSN_ENV = "BAG_CAPABILITY_ACCEPTANCE_DATABASE_URL"
ACCEPTOR_TOKEN_ENV = "BAG_CAPABILITY_ACCEPTOR_API_TOKEN"
WORKER_DSN_ENV = "BAG_CAPABILITY_OBSERVATION_DATABASE_URL"
WORKER_TOKEN_HEADER = "x-capability-worker-token"


class AcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1, max_length=128)
    request_id: UUID
    observation_id: int = Field(gt=0)


def _token_matches(candidate: str | None, expected: str) -> bool:
    return bool(candidate) and hmac.compare_digest(candidate, expected)


class CapabilityAcceptor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.token = os.environ.get(ACCEPTOR_TOKEN_ENV, "")
        self.dsn = os.environ.get(ACCEPTOR_DSN_ENV, "")
        if not self.token or len(self.token) < 32 or not self.dsn:
            raise RuntimeError("capability acceptor service configuration is incomplete")
        if os.environ.get(WORKER_DSN_ENV):
            raise RuntimeError("acceptor process must not receive the observer database credential")
        if settings.environment == "production" and not settings.oauth_enabled:
            raise RuntimeError("production capability acceptance requires authenticated services")
        self.db = Database(self.dsn)

    async def start(self):
        await self.db.start()
        await self.db.assert_schema()
        if self.settings.environment == "production":
            await self.db.assert_capability_acceptor_role()

    async def close(self):
        await self.db.close()

    async def accept(self, body: AcceptRequest) -> dict:
        row = await self.db.require_pool().fetchrow(
            """
            SELECT * FROM bag.accept_capability_observation($1, $2::uuid, $3::bigint)
            """,
            body.source_id,
            body.request_id,
            body.observation_id,
        )
        if row is None:
            raise HTTPException(status_code=409, detail="CAPABILITY_OBSERVATION_NOT_ACCEPTED")
        return {
            "source_id": body.source_id,
            "request_id": str(body.request_id),
            "observation_id": body.observation_id,
            "drift_status": row["drift_status"],
            "previous_metadata_fingerprint": row["previous_metadata_fingerprint"],
            "drift_detected_at": row["drift_detected_at"].isoformat()
            if row["drift_detected_at"] is not None
            else None,
            "drift_acknowledged_at": row["drift_acknowledged_at"].isoformat()
            if row["drift_acknowledged_at"] is not None
            else None,
            "evidence": row["evidence_json"],
        }


settings = Settings()
acceptor = CapabilityAcceptor(settings)


@asynccontextmanager
async def lifespan(_app):
    await acceptor.start()
    try:
        yield
    finally:
        await acceptor.close()


async def _parse_request(request: Request) -> AcceptRequest:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="JSON_REQUIRED")
    raw_body = await request.body()
    if len(raw_body) > 8192:
        raise HTTPException(status_code=413, detail="REQUEST_TOO_LARGE")
    try:
        return AcceptRequest.model_validate(json.loads(raw_body))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="INVALID_REQUEST") from exc


async def healthz(_request: Request):
    return JSONResponse({"status": "ok"})


async def readyz(
    request: Request,
):
    worker_token = request.headers.get(WORKER_TOKEN_HEADER)
    if not _token_matches(worker_token, acceptor.token):
        raise HTTPException(status_code=401, detail="SERVICE_AUTH_REQUIRED")
    try:
        if not await acceptor.db.ping():
            raise HTTPException(status_code=503, detail="CAPABILITY_DATABASE_UNAVAILABLE")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - readiness reports only dependency state
        raise HTTPException(status_code=503, detail="CAPABILITY_DATABASE_UNAVAILABLE") from exc
    return JSONResponse({"status": "ready"})


async def accept_capability_observation(
    request: Request,
):
    worker_token = request.headers.get(WORKER_TOKEN_HEADER)
    if not _token_matches(worker_token, acceptor.token):
        raise HTTPException(status_code=401, detail="SERVICE_AUTH_REQUIRED")
    body = await _parse_request(request)
    return JSONResponse(await acceptor.accept(body))


async def http_exception_handler(_request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "REQUEST_REJECTED"
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)


app = Starlette(
    debug=False,
    routes=[
        Route("/healthz", healthz, methods=["GET"]),
        Route("/readyz", readyz, methods=["GET"]),
        Route(
            "/internal/v1/accept-capability-observation",
            accept_capability_observation,
            methods=["POST"],
        ),
    ],
    exception_handlers={HTTPException: http_exception_handler},
    lifespan=lifespan,
)
