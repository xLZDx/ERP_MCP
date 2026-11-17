"""Private capability-observation worker.

This process owns only the observation-writer database credential. It accepts a source id,
never caller-supplied capability data or an endpoint, and independently resolves and probes
the registered source before persisting an observation.
"""

from __future__ import annotations

import hmac
import json
import os
from contextlib import asynccontextmanager
from uuid import UUID

import asyncpg
import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .adapters.onec.adapter import OneCAdapter
from .adapters.onec.client import OneCReadClient
from .adapters.onec.sidecar_client import ODataSidecarClient
from .auth import JWTTokenVerifier
from .db import Database
from .models import Source, source_from_record
from .principal import Principal, claim_groups
from .registry import AccessDenied, Registry
from .secrets import build_secret_provider
from .settings import Settings

WRITER_DSN_ENV = "BAG_CAPABILITY_OBSERVATION_DATABASE_URL"
WORKER_TOKEN_ENV = "BAG_CAPABILITY_WORKER_API_TOKEN"
ACCEPTOR_URL_ENV = "BAG_CAPABILITY_ACCEPTOR_URL"
ACCEPTOR_TOKEN_ENV = "BAG_CAPABILITY_ACCEPTOR_API_TOKEN"
WORKER_TOKEN_HEADER = "x-capability-worker-token"
ACCEPTOR_PATH = "/internal/v1/accept-capability-observation"


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_id: str = Field(min_length=1, max_length=128)
    request_id: UUID


def _token_matches(candidate: str | None, expected: str) -> bool:
    return bool(candidate) and hmac.compare_digest(candidate, expected)


def _make_principal(token) -> Principal:
    claims = token.claims or {}
    return Principal(
        subject=str(token.subject or claims["sub"]),
        client_id=token.client_id,
        scopes=frozenset(token.scopes),
        groups=claim_groups(claims),
        claims=claims,
    )


class CapabilityObservationWorker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.writer_dsn = os.environ.get(WRITER_DSN_ENV, "")
        self.worker_token = os.environ.get(WORKER_TOKEN_ENV, "")
        self.acceptor_url = os.environ.get(ACCEPTOR_URL_ENV, "").rstrip("/")
        self.acceptor_token = os.environ.get(ACCEPTOR_TOKEN_ENV, "")
        if not self.writer_dsn or not self.worker_token or not self.acceptor_url or not self.acceptor_token:
            raise RuntimeError("capability observer service configuration is incomplete")
        if os.environ.get("BAG_CAPABILITY_ACCEPTANCE_DATABASE_URL"):
            raise RuntimeError("observer process must not receive the acceptor database credential")
        if settings.environment == "production":
            if not settings.oauth_enabled:
                raise RuntimeError("production capability observation requires OAuth authentication")
            if not self.acceptor_url.startswith("https://"):
                raise RuntimeError("production capability acceptor URL must use HTTPS")
        if len(self.worker_token) < 32 or len(self.acceptor_token) < 32:
            raise RuntimeError("capability service tokens must contain at least 32 characters")

        self.reader_db = Database(settings.database_url)
        self.writer_db = Database(self.writer_dsn)
        self.registry = Registry(
            self.reader_db,
            production=settings.environment == "production",
            allowed_source_hosts=settings.source_host_allowlist_items,
        )
        self.secrets = build_secret_provider(settings)
        self.onec_client = OneCReadClient(
            timeout_seconds=settings.http_timeout_seconds,
            max_response_bytes=settings.max_response_bytes,
            allowed_egress_cidrs=settings.source_egress_cidr_items,
        )
        self.sidecar = (
            ODataSidecarClient(
                base_url=settings.odata_sidecar_url,
                token=settings.odata_sidecar_token.get_secret_value(),
                timeout_seconds=settings.http_timeout_seconds,
                max_response_bytes=settings.max_response_bytes,
                max_rows=settings.max_rows,
                allowed_egress_cidrs=settings.sidecar_egress_cidr_items,
            )
            if settings.odata_sidecar_url and settings.odata_sidecar_token
            else None
        )
        self.onec = OneCAdapter(settings, self.secrets, self.onec_client, self.sidecar)
        self.user_verifier = JWTTokenVerifier(settings) if settings.oauth_enabled else None
        self.admin_verifier = (
            JWTTokenVerifier(
                settings,
                audience=settings.admin_oauth_audience,
                required_scope=settings.admin_oauth_required_scope,
                resource=settings.admin_oauth_audience,
            )
            if settings.oauth_enabled and settings.admin_oauth_audience
            else None
        )
        self.acceptor_http = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            verify=True,
            follow_redirects=False,
            trust_env=False,
        )

    async def start(self):
        await self.reader_db.start()
        await self.reader_db.assert_schema()
        await self.writer_db.start()
        await self.writer_db.assert_schema()
        if self.settings.environment == "production":
            await self.writer_db.assert_capability_writer_role()

    async def close(self):
        await self.acceptor_http.aclose()
        if self.sidecar is not None:
            await self.sidecar.close()
        await self.onec_client.close()
        await self.writer_db.close()
        await self.reader_db.close()

    async def _authorize_and_resolve_source(
        self, source_id: str, authorization: str | None
    ) -> Source:
        if not self.settings.oauth_enabled:
            if self.settings.environment == "production":
                raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
            principal = Principal(
                subject="development-local",
                client_id="development",
                scopes=frozenset({"onec:read"}),
                groups=frozenset({"development"}),
                claims={},
            )
            try:
                return await self.registry.require_source(principal, source_id)
            except AccessDenied as exc:
                raise HTTPException(status_code=403, detail="SOURCE_ACCESS_DENIED") from exc

        scheme, _, raw_token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not raw_token.strip():
            raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
        token = await self.user_verifier.verify_token(raw_token.strip())
        if token is not None:
            try:
                principal = _make_principal(token)
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail="GROUP_CLAIMS_INVALID") from exc
            try:
                return await self.registry.require_source(principal, source_id)
            except AccessDenied as exc:
                raise HTTPException(status_code=403, detail="SOURCE_ACCESS_DENIED") from exc

        if self.admin_verifier is None:
            raise HTTPException(status_code=401, detail="TOKEN_REJECTED")
        admin_token = await self.admin_verifier.verify_token(raw_token.strip())
        if admin_token is None:
            raise HTTPException(status_code=401, detail="TOKEN_REJECTED")
        try:
            groups = claim_groups(admin_token.claims or {})
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="GROUP_CLAIMS_INVALID") from exc
        row = await self.reader_db.require_pool().fetchrow(
            """
            SELECT s.*
            FROM bag.sources AS s
            WHERE s.source_id = $1 AND s.enabled = TRUE
              AND EXISTS (
                SELECT 1 FROM bag.platform_role_bindings AS b
                WHERE b.revoked_at IS NULL
                  AND (b.expires_at IS NULL OR b.expires_at > now())
                  AND b.role_name IN ('PLATFORM_ADMIN','SOURCE_ADMIN')
                  AND (b.source_id IS NULL OR b.source_id = s.source_id)
                  AND (
                    (b.principal_kind='subject' AND b.principal_id=$2)
                    OR (b.principal_kind='group' AND b.principal_id=ANY($3::text[]))
                  )
              )
            """,
            source_id,
            admin_token.subject or "",
            list(groups),
        )
        if row is None:
            raise HTTPException(status_code=403, detail="SOURCE_ADMIN_ACCESS_DENIED")
        source = source_from_record(row)
        try:
            source.validate_runtime(
                production=self.settings.environment == "production",
                allowed_source_hosts=self.settings.source_host_allowlist_items,
            )
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="SOURCE_POLICY_DENIED") from exc
        return source

    async def refresh(
        self, body: RefreshRequest, *, authorization: str | None
    ) -> dict:
        source = await self._authorize_and_resolve_source(body.source_id, authorization)
        if source.row_version is None:
            raise HTTPException(status_code=503, detail="SOURCE_VERSION_UNAVAILABLE")
        try:
            reservation_id = await self.writer_db.require_pool().fetchval(
                """
                SELECT bag.reserve_capability_probe($1, $2::uuid, $3::bigint)
                """,
                source.id,
                body.request_id,
                source.row_version,
            )
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            raise HTTPException(status_code=503, detail="CAPABILITY_OBSERVER_UNAVAILABLE") from exc
        if type(reservation_id) is not int or reservation_id <= 0:
            raise HTTPException(status_code=503, detail="CAPABILITY_OBSERVER_UNAVAILABLE")

        capabilities = await self.onec.capabilities(source, refresh=True)
        if capabilities.source_id != source.id:
            raise HTTPException(status_code=503, detail="CAPABILITY_OBSERVER_UNAVAILABLE")

        try:
            observation_id = await self.writer_db.require_pool().fetchval(
                """
                SELECT bag.record_capability_observation(
                    $1, $2::uuid, $3::bigint, $4::bigint, $5, $6, $7, $8, $9, $10, $11,
                    $12, $13, $14::jsonb, $15::jsonb
                )
                """,
                source.id,
                body.request_id,
                reservation_id,
                source.row_version,
                capabilities.metadata_fingerprint,
                capabilities.platform_version,
                capabilities.compatibility_status.value,
                capabilities.adapter_profile.value,
                capabilities.metadata_supported,
                capabilities.json_supported,
                capabilities.atom_supported,
                capabilities.expand_supported,
                capabilities.entity_set_count,
                json.dumps(capabilities.evidence, ensure_ascii=False),
                json.dumps(capabilities.register_capabilities, ensure_ascii=False),
            )
        except (asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
            raise HTTPException(status_code=503, detail="CAPABILITY_OBSERVER_UNAVAILABLE") from exc
        if type(observation_id) is not int or observation_id <= 0:
            raise HTTPException(status_code=503, detail="CAPABILITY_OBSERVER_UNAVAILABLE")
        try:
            response = await self.acceptor_http.post(
                self.acceptor_url + ACCEPTOR_PATH,
                headers={WORKER_TOKEN_HEADER: self.acceptor_token},
                json={
                    "source_id": source.id,
                    "request_id": str(body.request_id),
                    "observation_id": int(observation_id),
                },
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(status_code=503, detail="CAPABILITY_ACCEPTANCE_UNAVAILABLE") from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="CAPABILITY_ACCEPTANCE_UNAVAILABLE") from exc
        accepted = response.json()
        if (
            not isinstance(accepted, dict)
            or accepted.get("source_id") != source.id
            or accepted.get("request_id") != str(body.request_id)
            or accepted.get("observation_id") != int(observation_id)
        ):
            raise HTTPException(status_code=503, detail="CAPABILITY_ACCEPTANCE_UNAVAILABLE")
        return {
            "source_id": source.id,
            "request_id": str(body.request_id),
            "observation_id": int(observation_id),
            "status": accepted["drift_status"],
        }


settings = Settings()
worker = CapabilityObservationWorker(settings)


@asynccontextmanager
async def lifespan(_app):
    await worker.start()
    try:
        yield
    finally:
        await worker.close()


async def _parse_request(request: Request) -> RefreshRequest:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="JSON_REQUIRED")
    raw_body = await request.body()
    if len(raw_body) > 8192:
        raise HTTPException(status_code=413, detail="REQUEST_TOO_LARGE")
    try:
        return RefreshRequest.model_validate(json.loads(raw_body))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail="INVALID_REQUEST") from exc


async def healthz(_request: Request):
    return JSONResponse({"status": "ok"})


async def readyz(
    request: Request,
):
    worker_token = request.headers.get(WORKER_TOKEN_HEADER)
    if not _token_matches(worker_token, worker.worker_token):
        raise HTTPException(status_code=401, detail="SERVICE_AUTH_REQUIRED")
    try:
        reader_ready = await worker.reader_db.ping()
        writer_ready = await worker.writer_db.ping()
        acceptor_ready = await worker.acceptor_http.get(
            worker.acceptor_url + "/readyz",
            headers={WORKER_TOKEN_HEADER: worker.acceptor_token},
        )
        acceptor_ready.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="CAPABILITY_DEPENDENCY_UNAVAILABLE") from exc
    except Exception:  # noqa: BLE001 - readiness reports only dependency state
        raise HTTPException(status_code=503, detail="CAPABILITY_DEPENDENCY_UNAVAILABLE") from exc
    if not reader_ready or not writer_ready:
        raise HTTPException(status_code=503, detail="CAPABILITY_DATABASE_UNAVAILABLE")
    return JSONResponse({"status": "ready"})


async def observe_capabilities(
    request: Request,
):
    worker_token = request.headers.get(WORKER_TOKEN_HEADER)
    if not _token_matches(worker_token, worker.worker_token):
        raise HTTPException(status_code=401, detail="SERVICE_AUTH_REQUIRED")
    body = await _parse_request(request)
    result = await worker.refresh(
        body,
        authorization=request.headers.get("authorization"),
    )
    return JSONResponse(result)


async def http_exception_handler(_request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, str) else "REQUEST_REJECTED"
    return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)


app = Starlette(
    debug=False,
    routes=[
        Route("/healthz", healthz, methods=["GET"]),
        Route("/readyz", readyz, methods=["GET"]),
        Route("/internal/v1/observe-capabilities", observe_capabilities, methods=["POST"]),
    ],
    exception_handlers={HTTPException: http_exception_handler},
    lifespan=lifespan,
)
