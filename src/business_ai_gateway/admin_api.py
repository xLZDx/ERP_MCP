from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from mcp.server.auth.provider import AccessToken
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth import JWTTokenVerifier
from .settings import Settings

ADMIN_ROLES = frozenset(
    {
        "PLATFORM_ADMIN",
        "SOURCE_ADMIN",
        "ACCESS_ADMIN",
        "PROFILE_ADMIN",
        "AUDITOR",
    }
)


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, UUID)):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _json_record(row) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in dict(row).items()}


@dataclass(frozen=True, slots=True)
class AdminRoleBinding:
    role_name: str
    source_id: str | None


@dataclass(frozen=True, slots=True)
class AdminContext:
    token: AccessToken
    groups: frozenset[str]
    bindings: tuple[AdminRoleBinding, ...]

    def has_role(self, *roles: str) -> bool:
        allowed = set(roles)
        return any(binding.role_name in allowed for binding in self.bindings)

    def source_scope(self, *roles: str) -> set[str] | None:
        allowed = set(roles) if roles else set(ADMIN_ROLES)
        matching = [binding for binding in self.bindings if binding.role_name in allowed]
        if not matching:
            return set()
        if any(binding.source_id is None for binding in matching):
            return None
        return {
            binding.source_id
            for binding in matching
            if binding.source_id is not None
        }


class AdminRepository:
    def __init__(self, db):
        self.db = db

    async def resolve_bindings(
        self, subject: str, groups: frozenset[str]
    ) -> tuple[AdminRoleBinding, ...]:
        rows = await self.db.require_pool().fetch(
            """
            SELECT DISTINCT role_name, source_id
            FROM bag.platform_role_bindings
            WHERE revoked_at IS NULL
              AND (expires_at IS NULL OR expires_at > now())
              AND (
                    (principal_kind='subject' AND principal_id=$1)
                 OR (principal_kind='group' AND principal_id=ANY($2::text[]))
              )
            ORDER BY role_name, source_id NULLS FIRST
            """,
            subject,
            list(groups),
        )
        return tuple(
            AdminRoleBinding(role_name=row["role_name"], source_id=row["source_id"])
            for row in rows
        )

    async def list_sources(self, ctx: AdminContext) -> list[dict[str, Any]]:
        scope = ctx.source_scope()
        if scope == set():
            return []
        if scope is None:
            rows = await self.db.require_pool().fetch(
                """
                SELECT source_id, project, kind, display_name, read_only, enabled,
                       platform_version_hint, created_at, updated_at
                FROM bag.sources
                ORDER BY source_id
                LIMIT 500
                """
            )
        else:
            rows = await self.db.require_pool().fetch(
                """
                SELECT source_id, project, kind, display_name, read_only, enabled,
                       platform_version_hint, created_at, updated_at
                FROM bag.sources
                WHERE source_id=ANY($1::text[])
                ORDER BY source_id
                LIMIT 500
                """,
                sorted(scope),
            )
        return [_json_record(row) for row in rows]

    async def list_companies(self, ctx: AdminContext) -> list[dict[str, Any]]:
        scope = ctx.source_scope()
        if scope == set():
            return []
        if scope is None:
            rows = await self.db.require_pool().fetch(
                """
                SELECT company_id, source_id, external_ref, display_name, legal_name,
                       country_code, enabled, is_default, created_at, updated_at
                FROM bag.companies
                ORDER BY source_id, display_name, company_id
                LIMIT 1000
                """
            )
        else:
            rows = await self.db.require_pool().fetch(
                """
                SELECT company_id, source_id, external_ref, display_name, legal_name,
                       country_code, enabled, is_default, created_at, updated_at
                FROM bag.companies
                WHERE source_id=ANY($1::text[])
                ORDER BY source_id, display_name, company_id
                LIMIT 1000
                """,
                sorted(scope),
            )
        return [_json_record(row) for row in rows]

    async def list_capabilities(self, ctx: AdminContext) -> list[dict[str, Any]]:
        scope = ctx.source_scope()
        if scope == set():
            return []
        sql = """
            SELECT source_id, discovered_at, metadata_fingerprint, platform_version,
                   compatibility_status, adapter_profile, metadata_supported,
                   json_supported, atom_supported, expand_supported, entity_set_count,
                   previous_metadata_fingerprint, drift_status, drift_detected_at,
                   drift_acknowledged_at, register_capabilities_json
            FROM bag.source_capabilities
        """
        args: tuple[Any, ...] = ()
        if scope is not None:
            sql += " WHERE source_id=ANY($1::text[])"
            args = (sorted(scope),)
        sql += " ORDER BY source_id LIMIT 500"
        rows = await self.db.require_pool().fetch(sql, *args)
        return [_json_record(row) for row in rows]

    async def list_grants(self, ctx: AdminContext) -> list[dict[str, Any]]:
        scope = ctx.source_scope("PLATFORM_ADMIN", "ACCESS_ADMIN", "AUDITOR")
        if scope == set():
            return []
        sql = """
            SELECT grant_id, principal_kind, principal_id, source_id, all_sources,
                   company_id, effect, expires_at, revoked_at, created_at
            FROM bag.access_grants
        """
        args: tuple[Any, ...] = ()
        if scope is not None:
            sql += " WHERE source_id=ANY($1::text[])"
            args = (sorted(scope),)
        sql += " ORDER BY created_at DESC, grant_id LIMIT 1000"
        rows = await self.db.require_pool().fetch(sql, *args)
        return [_json_record(row) for row in rows]

    async def list_profiles(self, ctx: AdminContext) -> list[dict[str, Any]]:
        scope = ctx.source_scope("PLATFORM_ADMIN", "PROFILE_ADMIN", "AUDITOR")
        if scope == set():
            return []
        sql = """
            SELECT profile_id, source_id, company_id, preset_id, profile_name,
                   profile_version, status, metadata_fingerprint,
                   capability_fingerprint, profile_fingerprint, created_by,
                   validated_by, created_at, validated_at, retired_at
            FROM bag.semantic_profiles
        """
        args: tuple[Any, ...] = ()
        if scope is not None:
            sql += " WHERE source_id=ANY($1::text[])"
            args = (sorted(scope),)
        sql += " ORDER BY source_id, company_id NULLS FIRST, profile_name, profile_version DESC"
        sql += " LIMIT 1000"
        rows = await self.db.require_pool().fetch(sql, *args)
        return [_json_record(row) for row in rows]

    async def list_audit(self, ctx: AdminContext) -> list[dict[str, Any]]:
        scope = ctx.source_scope("PLATFORM_ADMIN", "AUDITOR")
        if scope == set():
            return []
        sql = """
            SELECT event_id, occurred_at, request_id, principal_subject, client_id,
                   tool_name, source_id, company_id, outcome, returned_items,
                   duration_ms, detail_code, adapter_kind, adapter_version,
                   upstream_sha, policy_version, metadata_fingerprint,
                   response_bytes, truncated
            FROM bag.audit_events
        """
        args: tuple[Any, ...] = ()
        if scope is not None:
            sql += " WHERE source_id=ANY($1::text[])"
            args = (sorted(scope),)
        sql += " ORDER BY occurred_at DESC, event_id LIMIT 500"
        rows = await self.db.require_pool().fetch(sql, *args)
        return [_json_record(row) for row in rows]

    async def overview(self, ctx: AdminContext) -> dict[str, int]:
        sources = await self.list_sources(ctx)
        companies = await self.list_companies(ctx)
        capabilities = await self.list_capabilities(ctx)
        return {
            "sources": len(sources),
            "companies": len(companies),
            "drifted_sources": sum(
                1 for item in capabilities if item.get("drift_status") == "DRIFTED"
            ),
        }


class AdminAPI:
    def __init__(self, settings: Settings, runtime):
        self.settings = settings
        self.runtime = runtime
        self.repository = AdminRepository(runtime.db)
        self.verifier = JWTTokenVerifier(
            settings,
            audience=settings.admin_oauth_audience,
            required_scope=settings.admin_oauth_required_scope,
            resource=settings.admin_oauth_audience,
        )

    @staticmethod
    def _groups(token: AccessToken) -> frozenset[str]:
        claims = token.claims or {}
        raw = claims.get("groups") or []
        if isinstance(raw, str):
            raw = [raw]
        return frozenset(str(value) for value in raw)

    async def authenticate(self, request: Request) -> AdminContext | JSONResponse:
        header = request.headers.get("authorization", "")
        scheme, _, raw_token = header.partition(" ")
        if scheme.lower() != "bearer" or not raw_token.strip():
            return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)

        token = await self.verifier.verify_token(raw_token.strip())
        if token is None:
            return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)

        await self.runtime.start()
        groups = self._groups(token)
        bindings = await self.repository.resolve_bindings(token.subject or "", groups)
        if not bindings:
            return JSONResponse({"error": "PLATFORM_ROLE_DENIED"}, status_code=403)
        return AdminContext(token=token, groups=groups, bindings=bindings)

    @staticmethod
    def _denied() -> JSONResponse:
        return JSONResponse({"error": "PLATFORM_ROLE_DENIED"}, status_code=403)

    async def me(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        return JSONResponse(
            {
                "subject": ctx.token.subject,
                "client_id": ctx.token.client_id,
                "groups": sorted(ctx.groups),
                "roles": [
                    {"role": binding.role_name, "source_id": binding.source_id}
                    for binding in ctx.bindings
                ],
            }
        )

    async def overview_view(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        return JSONResponse(await self.repository.overview(ctx))

    async def sources(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        return JSONResponse({"items": await self.repository.list_sources(ctx)})

    async def companies(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        return JSONResponse({"items": await self.repository.list_companies(ctx)})

    async def capabilities(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        return JSONResponse({"items": await self.repository.list_capabilities(ctx)})

    async def grants(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if not ctx.has_role("PLATFORM_ADMIN", "ACCESS_ADMIN", "AUDITOR"):
            return self._denied()
        return JSONResponse({"items": await self.repository.list_grants(ctx)})

    async def profiles(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if not ctx.has_role("PLATFORM_ADMIN", "PROFILE_ADMIN", "AUDITOR"):
            return self._denied()
        return JSONResponse({"items": await self.repository.list_profiles(ctx)})

    async def audit(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if not ctx.has_role("PLATFORM_ADMIN", "AUDITOR"):
            return self._denied()
        return JSONResponse({"items": await self.repository.list_audit(ctx)})


def register_admin_routes(mcp, settings: Settings, runtime):
    if not settings.admin_api_enabled:
        return None
    api = AdminAPI(settings, runtime)
    mcp.custom_route("/admin/v1/me", methods=["GET"])(api.me)
    mcp.custom_route("/admin/v1/overview", methods=["GET"])(api.overview_view)
    mcp.custom_route("/admin/v1/sources", methods=["GET"])(api.sources)
    mcp.custom_route("/admin/v1/companies", methods=["GET"])(api.companies)
    mcp.custom_route("/admin/v1/capabilities", methods=["GET"])(api.capabilities)
    mcp.custom_route("/admin/v1/grants", methods=["GET"])(api.grants)
    mcp.custom_route("/admin/v1/semantic-profiles", methods=["GET"])(api.profiles)
    mcp.custom_route("/admin/v1/audit", methods=["GET"])(api.audit)
    return api
