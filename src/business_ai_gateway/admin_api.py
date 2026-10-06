from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from mcp.server.auth.provider import AccessToken
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, RedirectResponse

from .admin_mutations import (
    AdminActor,
    AdminConflict,
    AdminMutationService,
    AdminNotFound,
    AdminValidationError,
)
from .admin_probe import AdminSourceProbe, SourceEgressDenied, SourceEgressPolicy
from .admin_session import AdminSessionManager
from .auth import JWTTokenVerifier
from .models import source_from_record
from .rate_limit import RateLimitExceeded
from .settings import Settings

ADMIN_ROLES = frozenset(
    {"PLATFORM_ADMIN", "SOURCE_ADMIN", "ACCESS_ADMIN", "PROFILE_ADMIN", "AUDITOR"}
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


def _request_id(request: Request) -> UUID:
    raw = request.headers.get("x-request-id")
    if raw:
        try:
            return UUID(raw)
        except ValueError:
            pass
    return uuid4()


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise AdminValidationError("request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise AdminValidationError("request body must be a JSON object")
    return body


@dataclass(frozen=True, slots=True)
class AdminRoleBinding:
    role_name: str
    source_id: str | None


@dataclass(frozen=True, slots=True)
class AdminContext:
    token: AccessToken
    groups: frozenset[str]
    bindings: tuple[AdminRoleBinding, ...]
    session_id: str | None = None
    csrf_token: str | None = None

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

    def can_admin_source(self, source_id: str, *roles: str) -> bool:
        scope = self.source_scope(*roles)
        return scope is None or source_id in scope


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

    async def _scoped_rows(
        self,
        *,
        ctx: AdminContext,
        roles: tuple[str, ...],
        global_sql: str,
        scoped_sql: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        scope = ctx.source_scope(*roles)
        if scope == set():
            return []
        pool = self.db.require_pool()
        if scope is None:
            rows = await pool.fetch(global_sql, limit)
        else:
            rows = await pool.fetch(scoped_sql, sorted(scope), limit)
        return [_json_record(row) for row in rows]

    async def list_sources(self, ctx: AdminContext) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=tuple(ADMIN_ROLES),
            global_sql="""
                SELECT source_id, project, kind, display_name, read_only, enabled,
                       platform_version_hint, row_version, created_at, updated_at
                FROM bag.sources ORDER BY source_id LIMIT $1
            """,
            scoped_sql="""
                SELECT source_id, project, kind, display_name, read_only, enabled,
                       platform_version_hint, row_version, created_at, updated_at
                FROM bag.sources
                WHERE source_id=ANY($1::text[])
                ORDER BY source_id LIMIT $2
            """,
            limit=500,
        )

    async def source_detail(
        self, ctx: AdminContext, source_id: str
    ) -> dict[str, Any] | None:
        if not ctx.can_admin_source(source_id):
            return None
        row = await self.db.require_pool().fetchrow(
            """
            SELECT source_id, project, kind, display_name, base_url,
                   username_secret_ref, password_secret_ref, read_only, enabled,
                   tags, entity_allow_patterns, entity_deny_patterns,
                   platform_version_hint, fallback_kind, fallback_base_url,
                   row_version, created_at, updated_at
            FROM bag.sources WHERE source_id=$1
            """,
            source_id,
        )
        return _json_record(row) if row is not None else None

    async def source_model(self, ctx: AdminContext, source_id: str):
        if not ctx.can_admin_source(source_id):
            return None
        row = await self.db.require_pool().fetchrow(
            "SELECT * FROM bag.sources WHERE source_id=$1 AND enabled=true",
            source_id,
        )
        return source_from_record(row) if row is not None else None

    async def company_detail(
        self, ctx: AdminContext, company_id: UUID
    ) -> dict[str, Any] | None:
        row = await self.db.require_pool().fetchrow(
            """
            SELECT company_id, source_id, external_ref, display_name, legal_name,
                   country_code, enabled, is_default, row_version,
                   created_at, updated_at
            FROM bag.companies WHERE company_id=$1
            """,
            company_id,
        )
        if row is None or not ctx.can_admin_source(row["source_id"]):
            return None
        return _json_record(row)

    async def list_companies(self, ctx: AdminContext) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=tuple(ADMIN_ROLES),
            global_sql="""
                SELECT company_id, source_id, external_ref, display_name, legal_name,
                       country_code, enabled, is_default, row_version, created_at, updated_at
                FROM bag.companies
                ORDER BY source_id, display_name, company_id LIMIT $1
            """,
            scoped_sql="""
                SELECT company_id, source_id, external_ref, display_name, legal_name,
                       country_code, enabled, is_default, row_version, created_at, updated_at
                FROM bag.companies
                WHERE source_id=ANY($1::text[])
                ORDER BY source_id, display_name, company_id LIMIT $2
            """,
            limit=1000,
        )

    async def list_capabilities(self, ctx: AdminContext) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=tuple(ADMIN_ROLES),
            global_sql="""
                SELECT source_id, discovered_at, metadata_fingerprint, platform_version,
                       compatibility_status, adapter_profile, metadata_supported,
                       json_supported, atom_supported, expand_supported, entity_set_count,
                       previous_metadata_fingerprint, drift_status, drift_detected_at,
                       drift_acknowledged_at, register_capabilities_json
                FROM bag.source_capabilities ORDER BY source_id LIMIT $1
            """,
            scoped_sql="""
                SELECT source_id, discovered_at, metadata_fingerprint, platform_version,
                       compatibility_status, adapter_profile, metadata_supported,
                       json_supported, atom_supported, expand_supported, entity_set_count,
                       previous_metadata_fingerprint, drift_status, drift_detected_at,
                       drift_acknowledged_at, register_capabilities_json
                FROM bag.source_capabilities
                WHERE source_id=ANY($1::text[])
                ORDER BY source_id LIMIT $2
            """,
            limit=500,
        )

    async def list_grants(self, ctx: AdminContext) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=("PLATFORM_ADMIN", "ACCESS_ADMIN", "AUDITOR"),
            global_sql="""
                SELECT grant_id, principal_kind, principal_id, source_id, all_sources,
                       company_id, effect, expires_at, revoked_at, created_at,
                       row_version, created_by_subject, create_reason,
                       revoked_by_subject, revoke_reason
                FROM bag.access_grants
                ORDER BY created_at DESC, grant_id LIMIT $1
            """,
            scoped_sql="""
                SELECT grant_id, principal_kind, principal_id, source_id, all_sources,
                       company_id, effect, expires_at, revoked_at, created_at,
                       row_version, created_by_subject, create_reason,
                       revoked_by_subject, revoke_reason
                FROM bag.access_grants
                WHERE source_id=ANY($1::text[])
                ORDER BY created_at DESC, grant_id LIMIT $2
            """,
            limit=1000,
        )

    async def list_platform_role_bindings(
        self, ctx: AdminContext
    ) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=("PLATFORM_ADMIN", "AUDITOR"),
            global_sql="""
                SELECT binding_id, principal_kind, principal_id, role_name,
                       source_id, expires_at, revoked_at, row_version,
                       created_by_subject, created_by_client, reason,
                       created_at, updated_at
                FROM bag.platform_role_bindings
                ORDER BY created_at DESC, binding_id LIMIT $1
            """,
            scoped_sql="""
                SELECT binding_id, principal_kind, principal_id, role_name,
                       source_id, expires_at, revoked_at, row_version,
                       created_by_subject, created_by_client, reason,
                       created_at, updated_at
                FROM bag.platform_role_bindings
                WHERE source_id=ANY($1::text[])
                ORDER BY created_at DESC, binding_id LIMIT $2
            """,
            limit=1000,
        )

    async def resolve_principal(
        self, ctx: AdminContext, *, principal_kind: str, principal_id: str
    ) -> dict[str, Any]:
        if principal_kind not in {"subject", "group"}:
            raise AdminValidationError("principal kind must be subject or group")
        principal_id = principal_id.strip()
        if not principal_id or len(principal_id) > 512:
            raise AdminValidationError("principal id is required and must be <=512 characters")

        grants = [
            item
            for item in await self.list_grants(ctx)
            if item["principal_kind"] == principal_kind
            and item["principal_id"] == principal_id
        ]
        assignments = [
            item
            for item in await self.list_business_role_assignments(ctx)
            if item["principal_kind"] == principal_kind
            and item["principal_id"] == principal_id
        ]
        overrides = [
            item
            for item in await self.list_capability_overrides(ctx)
            if item["principal_kind"] == principal_kind
            and item["principal_id"] == principal_id
        ]
        platform_roles: list[dict[str, Any]] = []
        if ctx.has_role("PLATFORM_ADMIN", "AUDITOR"):
            platform_roles = [
                item
                for item in await self.list_platform_role_bindings(ctx)
                if item["principal_kind"] == principal_kind
                and item["principal_id"] == principal_id
            ]
        return {
            "principal_kind": principal_kind,
            "principal_id": principal_id,
            "directory_status": "not_configured",
            "display_name": None,
            "platform_roles": platform_roles,
            "grants": grants,
            "business_role_assignments": assignments,
            "capability_overrides": overrides,
        }

    async def list_business_roles(self) -> list[dict[str, Any]]:
        rows = await self.db.require_pool().fetch(
            """
            SELECT r.role_id, r.display_name, r.description, r.built_in,
                   r.enabled, r.policy_version,
                   coalesce(
                     json_agg(c.capability_key ORDER BY c.capability_key)
                       FILTER (WHERE c.capability_key IS NOT NULL),
                     '[]'::json
                   ) AS capabilities
            FROM bag.business_roles r
            LEFT JOIN bag.business_role_capabilities c ON c.role_id=r.role_id
            GROUP BY r.role_id, r.display_name, r.description, r.built_in,
                     r.enabled, r.policy_version
            ORDER BY r.role_id
            """
        )
        return [_json_record(row) for row in rows]

    async def list_business_role_assignments(
        self, ctx: AdminContext
    ) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=("PLATFORM_ADMIN", "ACCESS_ADMIN", "AUDITOR"),
            global_sql="""
                SELECT assignment_id, principal_kind, principal_id, role_id,
                       source_id, company_id, expires_at, revoked_at,
                       row_version, created_by_subject, reason, created_at, updated_at
                FROM bag.business_role_assignments
                ORDER BY created_at DESC, assignment_id LIMIT $1
            """,
            scoped_sql="""
                SELECT assignment_id, principal_kind, principal_id, role_id,
                       source_id, company_id, expires_at, revoked_at,
                       row_version, created_by_subject, reason, created_at, updated_at
                FROM bag.business_role_assignments
                WHERE source_id=ANY($1::text[])
                ORDER BY created_at DESC, assignment_id LIMIT $2
            """,
            limit=1000,
        )

    async def list_capability_overrides(
        self, ctx: AdminContext
    ) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=("PLATFORM_ADMIN", "ACCESS_ADMIN", "AUDITOR"),
            global_sql="""
                SELECT override_id, principal_kind, principal_id, capability_key,
                       source_id, company_id, effect, expires_at, revoked_at,
                       row_version, created_by_subject, reason, created_at, updated_at
                FROM bag.capability_overrides
                ORDER BY created_at DESC, override_id LIMIT $1
            """,
            scoped_sql="""
                SELECT override_id, principal_kind, principal_id, capability_key,
                       source_id, company_id, effect, expires_at, revoked_at,
                       row_version, created_by_subject, reason, created_at, updated_at
                FROM bag.capability_overrides
                WHERE source_id=ANY($1::text[])
                ORDER BY created_at DESC, override_id LIMIT $2
            """,
            limit=1000,
        )

    async def list_company_scope_mappings(
        self, ctx: AdminContext
    ) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=("PLATFORM_ADMIN", "PROFILE_ADMIN", "AUDITOR"),
            global_sql="""
                SELECT m.scope_mapping_id, m.profile_id, p.source_id, p.company_id,
                       p.status AS profile_status, p.metadata_fingerprint,
                       m.entity_set, m.company_property, m.literal_kind,
                       m.created_by, m.created_at, m.updated_at
                FROM bag.company_scope_mappings m
                JOIN bag.semantic_profiles p ON p.profile_id=m.profile_id
                ORDER BY p.source_id, m.entity_set, m.scope_mapping_id LIMIT $1
            """,
            scoped_sql="""
                SELECT m.scope_mapping_id, m.profile_id, p.source_id, p.company_id,
                       p.status AS profile_status, p.metadata_fingerprint,
                       m.entity_set, m.company_property, m.literal_kind,
                       m.created_by, m.created_at, m.updated_at
                FROM bag.company_scope_mappings m
                JOIN bag.semantic_profiles p ON p.profile_id=m.profile_id
                WHERE p.source_id=ANY($1::text[])
                ORDER BY p.source_id, m.entity_set, m.scope_mapping_id LIMIT $2
            """,
            limit=1000,
        )

    async def list_profiles(self, ctx: AdminContext) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=("PLATFORM_ADMIN", "PROFILE_ADMIN", "AUDITOR"),
            global_sql="""
                SELECT profile_id, source_id, company_id, preset_id, profile_name,
                       profile_version, status, metadata_fingerprint,
                       capability_fingerprint, profile_fingerprint, created_by,
                       validated_by, created_at, validated_at, retired_at
                FROM bag.semantic_profiles
                ORDER BY source_id, company_id NULLS FIRST, profile_name,
                         profile_version DESC LIMIT $1
            """,
            scoped_sql="""
                SELECT profile_id, source_id, company_id, preset_id, profile_name,
                       profile_version, status, metadata_fingerprint,
                       capability_fingerprint, profile_fingerprint, created_by,
                       validated_by, created_at, validated_at, retired_at
                FROM bag.semantic_profiles
                WHERE source_id=ANY($1::text[])
                ORDER BY source_id, company_id NULLS FIRST, profile_name,
                         profile_version DESC LIMIT $2
            """,
            limit=1000,
        )

    async def list_access_audit(self, ctx: AdminContext) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=("PLATFORM_ADMIN", "AUDITOR"),
            global_sql="""
                SELECT event_id, occurred_at, request_id, principal_subject, client_id,
                       tool_name, source_id, company_id, outcome, returned_items,
                       duration_ms, detail_code, adapter_kind, adapter_version,
                       upstream_sha, policy_version, metadata_fingerprint,
                       response_bytes, truncated
                FROM bag.audit_events ORDER BY occurred_at DESC, event_id LIMIT $1
            """,
            scoped_sql="""
                SELECT event_id, occurred_at, request_id, principal_subject, client_id,
                       tool_name, source_id, company_id, outcome, returned_items,
                       duration_ms, detail_code, adapter_kind, adapter_version,
                       upstream_sha, policy_version, metadata_fingerprint,
                       response_bytes, truncated
                FROM bag.audit_events
                WHERE source_id=ANY($1::text[])
                ORDER BY occurred_at DESC, event_id LIMIT $2
            """,
            limit=500,
        )

    async def list_admin_audit(self, ctx: AdminContext) -> list[dict[str, Any]]:
        return await self._scoped_rows(
            ctx=ctx,
            roles=("PLATFORM_ADMIN", "AUDITOR"),
            global_sql="""
                SELECT event_id, occurred_at, request_id, actor_subject, actor_client_id,
                       action, target_type, target_id, source_id, company_id, reason,
                       idempotency_key, policy_version, before_fingerprint,
                       after_fingerprint, safe_change_json, outcome, detail_code
                FROM bag.admin_audit_events
                ORDER BY occurred_at DESC, event_id LIMIT $1
            """,
            scoped_sql="""
                SELECT event_id, occurred_at, request_id, actor_subject, actor_client_id,
                       action, target_type, target_id, source_id, company_id, reason,
                       idempotency_key, policy_version, before_fingerprint,
                       after_fingerprint, safe_change_json, outcome, detail_code
                FROM bag.admin_audit_events
                WHERE source_id=ANY($1::text[])
                ORDER BY occurred_at DESC, event_id LIMIT $2
            """,
            limit=500,
        )

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
        read_db = runtime.admin_db or runtime.db
        self.repository = AdminRepository(read_db)
        self.mutations = (
            AdminMutationService(
                runtime.admin_db,
                production=settings.environment == "production",
            )
            if settings.admin_mutations_enabled and runtime.admin_db is not None
            else None
        )
        self.probe = AdminSourceProbe(
            runtime,
            SourceEgressPolicy(
                allowed_hosts=settings.admin_source_allowed_hosts,
                allowed_cidrs=settings.admin_source_allowed_cidrs,
            ),
        )
        self.verifier = JWTTokenVerifier(
            settings,
            audience=settings.admin_oauth_audience,
            required_scope=settings.admin_oauth_required_scope,
            resource=settings.admin_oauth_audience,
        )
        self.sessions = (
            AdminSessionManager(settings, runtime.redis, self.verifier)
            if settings.admin_ui_enabled
            else None
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
        session_id = None
        csrf_token = None

        if scheme.lower() == "bearer" and raw_token.strip():
            token = await self.verifier.verify_token(raw_token.strip())
        elif self.sessions is not None:
            session = await self.sessions.resolve(request)
            if session is None:
                return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)
            token = await self.verifier.verify_token(session.access_token)
            session_id = session.session_id
            csrf_token = session.csrf_token
        else:
            return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)

        if token is None:
            return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)

        await self.runtime.start()
        try:
            await self.runtime.rate_limit.check(
                subject=token.subject or "",
                source_id="__admin__",
                tool="admin_api",
            )
        except RateLimitExceeded:
            return JSONResponse({"error": "RATE_LIMITED"}, status_code=429)
        except Exception:  # noqa: BLE001 - admin API fails closed on limiter dependency loss
            return JSONResponse({"error": "ADMIN_DEPENDENCY_UNAVAILABLE"}, status_code=503)

        groups = self._groups(token)
        bindings = await self.repository.resolve_bindings(token.subject or "", groups)
        if not bindings:
            return JSONResponse({"error": "PLATFORM_ROLE_DENIED"}, status_code=403)
        return AdminContext(
            token=token,
            groups=groups,
            bindings=bindings,
            session_id=session_id,
            csrf_token=csrf_token,
        )

    async def csrf_guard(self, request: Request):
        if self.sessions is None:
            return None
        scheme, _, bearer = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() == "bearer" and bearer.strip():
            return None
        if not request.cookies.get(self.sessions.SESSION_COOKIE):
            return None
        session = await self.sessions.resolve(request)
        if session is None:
            return JSONResponse({"error": "AUTH_REQUIRED"}, status_code=401)
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied or not secrets.compare_digest(supplied, session.csrf_token):
            return JSONResponse({"error": "CSRF_DENIED"}, status_code=403)
        return None

    @staticmethod
    def _denied() -> JSONResponse:
        return JSONResponse({"error": "PLATFORM_ROLE_DENIED"}, status_code=403)

    @staticmethod
    def _disabled() -> JSONResponse:
        return JSONResponse({"error": "ADMIN_MUTATIONS_DISABLED"}, status_code=503)

    @staticmethod
    def _mutation_error(exc: Exception) -> JSONResponse:
        if isinstance(exc, AdminConflict):
            status_code = 409
        elif isinstance(exc, AdminNotFound):
            status_code = 404
        elif isinstance(exc, (AdminValidationError, ValueError, TypeError)):
            status_code = 400
        elif isinstance(exc, SourceEgressDenied):
            status_code = 403
        else:
            status_code = 500
        code = getattr(exc, "code", "INVALID_REQUEST" if status_code == 400 else "ADMIN_DEPENDENCY_FAILED")
        return JSONResponse({"error": code}, status_code=status_code)

    @staticmethod
    def _actor(ctx: AdminContext) -> AdminActor:
        return AdminActor(
            subject=ctx.token.subject or "",
            client_id=ctx.token.client_id,
        )

    async def admin_root(self, _request: Request):
        return RedirectResponse("/admin/", status_code=302)

    async def admin_ui(self, _request: Request):
        static_path = Path(__file__).resolve().parent / "static" / "admin.html"
        return FileResponse(
            static_path,
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                    "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                    "form-action 'self'"
                ),
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
            },
        )

    async def login(self, request: Request):
        if self.sessions is None:
            return JSONResponse({"error": "ADMIN_UI_DISABLED"}, status_code=404)
        try:
            return await self.sessions.login(request)
        except Exception:  # noqa: BLE001 - redact OIDC/session dependency failures
            return JSONResponse({"error": "OIDC_LOGIN_UNAVAILABLE"}, status_code=503)

    async def callback(self, request: Request):
        if self.sessions is None:
            return JSONResponse({"error": "ADMIN_UI_DISABLED"}, status_code=404)
        try:
            return await self.sessions.callback(request)
        except Exception:  # noqa: BLE001 - never expose token-exchange internals
            return JSONResponse({"error": "OIDC_LOGIN_FAILED"}, status_code=401)

    async def logout(self, request: Request):
        if self.sessions is None:
            return JSONResponse({"error": "ADMIN_UI_DISABLED"}, status_code=404)
        guard = await self.csrf_guard(request)
        if guard is not None:
            return guard
        return await self.sessions.logout(request)

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
                "mutations_enabled": self.mutations is not None,
                "csrf_token": ctx.csrf_token,
                "session_authenticated": ctx.session_id is not None,
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

    async def platform_role_bindings(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if not ctx.has_role("PLATFORM_ADMIN", "AUDITOR"):
            return self._denied()
        return JSONResponse(
            {"items": await self.repository.list_platform_role_bindings(ctx)}
        )

    async def principal_resolve(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if not ctx.has_role("PLATFORM_ADMIN", "ACCESS_ADMIN", "AUDITOR"):
            return self._denied()
        try:
            result = await self.repository.resolve_principal(
                ctx,
                principal_kind=request.query_params.get("kind", ""),
                principal_id=request.query_params.get("id", ""),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def business_roles(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        return JSONResponse({"items": await self.repository.list_business_roles()})

    async def business_role_assignments(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if not ctx.has_role("PLATFORM_ADMIN", "ACCESS_ADMIN", "AUDITOR"):
            return self._denied()
        return JSONResponse(
            {"items": await self.repository.list_business_role_assignments(ctx)}
        )

    async def capability_overrides(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if not ctx.has_role("PLATFORM_ADMIN", "ACCESS_ADMIN", "AUDITOR"):
            return self._denied()
        return JSONResponse(
            {"items": await self.repository.list_capability_overrides(ctx)}
        )

    async def company_scope_mappings(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if not ctx.has_role("PLATFORM_ADMIN", "PROFILE_ADMIN", "AUDITOR"):
            return self._denied()
        return JSONResponse(
            {"items": await self.repository.list_company_scope_mappings(ctx)}
        )

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
        result = {"access": await self.repository.list_access_audit(ctx)}
        if self.runtime.admin_db is not None:
            result["admin"] = await self.repository.list_admin_audit(ctx)
        else:
            result["admin"] = []
        return JSONResponse(result)

    async def source_detail_view(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        item = await self.repository.source_detail(ctx, request.path_params["source_id"])
        if item is None:
            return JSONResponse({"error": "SOURCE_NOT_FOUND"}, status_code=404)
        return JSONResponse(item)

    async def company_detail_view(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        try:
            company_id = UUID(request.path_params["company_id"])
        except ValueError:
            return JSONResponse({"error": "COMPANY_NOT_FOUND"}, status_code=404)
        item = await self.repository.company_detail(ctx, company_id)
        if item is None:
            return JSONResponse({"error": "COMPANY_NOT_FOUND"}, status_code=404)
        return JSONResponse(item)

    async def source_update(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        source_id = request.path_params["source_id"]
        if not ctx.can_admin_source(source_id, "PLATFORM_ADMIN", "SOURCE_ADMIN"):
            return self._denied()
        try:
            body = await _json_body(request)
            if str(body.get("source_id", source_id)) != source_id:
                raise AdminValidationError("source_id is immutable")
            await self.probe.probe(
                base_url=str(body.get("base_url", "")),
                username_secret_ref=str(body.get("username_secret_ref", "")),
                password_secret_ref=str(body.get("password_secret_ref", "")),
                display_name=str(body.get("display_name", "")),
                platform_version_hint=body.get("platform_version_hint"),
            )
            result = await self.mutations.update_source(
                actor=self._actor(ctx),
                source_id=source_id,
                expected_version=int(body.get("expected_version", 0)),
                display_name=str(body.get("display_name", "")),
                base_url=str(body.get("base_url", "")),
                username_secret_ref=str(body.get("username_secret_ref", "")),
                password_secret_ref=str(body.get("password_secret_ref", "")),
                tags=[str(item) for item in body.get("tags", [])],
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def company_update(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        try:
            company_id = UUID(request.path_params["company_id"])
            current = await self.repository.company_detail(ctx, company_id)
            if current is None:
                return self._denied()
            if not ctx.can_admin_source(
                current["source_id"], "PLATFORM_ADMIN", "SOURCE_ADMIN"
            ):
                return self._denied()
            body = await _json_body(request)
            if "source_id" in body and body["source_id"] != current["source_id"]:
                raise AdminValidationError("company source_id is immutable")
            if "external_ref" in body and body["external_ref"] != current["external_ref"]:
                raise AdminValidationError("company external_ref is immutable")
            result = await self.mutations.update_company(
                actor=self._actor(ctx),
                company_id=company_id,
                expected_version=int(body.get("expected_version", 0)),
                display_name=str(body.get("display_name", "")),
                legal_name=body.get("legal_name"),
                country_code=body.get("country_code"),
                enabled=bool(body.get("enabled", True)),
                is_default=bool(body.get("is_default", False)),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def capability_refresh(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        source_id = request.path_params["source_id"]
        if not ctx.can_admin_source(source_id, "PLATFORM_ADMIN", "SOURCE_ADMIN"):
            return self._denied()
        actor = self._actor(ctx)
        request_id = _request_id(request)
        reason = "capability refresh"
        try:
            body = await _json_body(request)
            reason = str(body.get("reason", ""))
            source = await self.repository.source_model(ctx, source_id)
            if source is None:
                return JSONResponse({"error": "SOURCE_NOT_FOUND"}, status_code=404)
            await self.probe.policy.validate(source.base_url)
            capabilities = await self.runtime.onec.capabilities(source, refresh=True)
            drift = await self.runtime.registry.save_capabilities(capabilities)
            result = capabilities.as_dict()
            result.update(drift)
            await self.mutations.record_admin_event(
                actor=actor,
                action="capability.refresh",
                target_type="source_capability",
                target_id=source_id,
                source_id=source_id,
                company_id=None,
                reason=reason,
                request_id=request_id,
                outcome="success",
                safe_change={
                    "metadata_fingerprint": capabilities.metadata_fingerprint,
                    "adapter_profile": capabilities.adapter_profile.value,
                    "drift_status": drift["drift_status"],
                },
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            try:
                await self.mutations.record_admin_event(
                    actor=actor,
                    action="capability.refresh",
                    target_type="source_capability",
                    target_id=source_id,
                    source_id=source_id,
                    company_id=None,
                    reason=reason or "capability refresh failed",
                    request_id=request_id,
                    outcome="error",
                    detail_code=getattr(exc, "code", type(exc).__name__),
                )
            except Exception:  # noqa: BLE001 - preserve original safe API error
                _ = None
            return self._mutation_error(exc)

    async def source_probe(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if not ctx.has_role("PLATFORM_ADMIN", "SOURCE_ADMIN"):
            return self._denied()
        try:
            body = await _json_body(request)
            result = await self.probe.probe(
                base_url=str(body.get("base_url", "")),
                username_secret_ref=str(body.get("username_secret_ref", "")),
                password_secret_ref=str(body.get("password_secret_ref", "")),
                display_name=str(body.get("display_name", "Admin source probe")),
                platform_version_hint=body.get("platform_version_hint"),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def source_create(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        if ctx.source_scope("PLATFORM_ADMIN", "SOURCE_ADMIN") is not None:
            return self._denied()
        try:
            body = await _json_body(request)
            # Re-probe immediately before registration; browser probe results are never trusted.
            await self.probe.probe(
                base_url=str(body.get("base_url", "")),
                username_secret_ref=str(body.get("username_secret_ref", "")),
                password_secret_ref=str(body.get("password_secret_ref", "")),
                display_name=str(body.get("display_name", "")),
                platform_version_hint=body.get("platform_version_hint"),
            )
            result = await self.mutations.create_source(
                actor=self._actor(ctx),
                source_id=str(body.get("source_id", "")),
                display_name=str(body.get("display_name", "")),
                base_url=str(body.get("base_url", "")),
                username_secret_ref=str(body.get("username_secret_ref", "")),
                password_secret_ref=str(body.get("password_secret_ref", "")),
                tags=[str(item) for item in body.get("tags", [])],
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result, status_code=201)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def company_create(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        try:
            body = await _json_body(request)
            source_id = str(body.get("source_id", ""))
            if not ctx.can_admin_source(
                source_id, "PLATFORM_ADMIN", "SOURCE_ADMIN"
            ):
                return self._denied()
            result = await self.mutations.create_company(
                actor=self._actor(ctx),
                source_id=source_id,
                external_ref=str(body.get("external_ref", "")),
                display_name=str(body.get("display_name", "")),
                legal_name=body.get("legal_name"),
                country_code=body.get("country_code"),
                is_default=bool(body.get("is_default", False)),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result, status_code=201)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def grant_create(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        try:
            body = await _json_body(request)
            source_id = str(body.get("source_id", ""))
            if not ctx.can_admin_source(source_id, "PLATFORM_ADMIN", "ACCESS_ADMIN"):
                return self._denied()
            company_raw = body.get("company_id")
            result = await self.mutations.create_grant(
                actor=self._actor(ctx),
                principal_kind=str(body.get("principal_kind", "")),
                principal_id=str(body.get("principal_id", "")),
                source_id=source_id,
                company_id=UUID(str(company_raw)) if company_raw else None,
                effect=str(body.get("effect", "allow")),
                expires_at=body.get("expires_at"),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result, status_code=201)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def grant_revoke(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        if not ctx.has_role("PLATFORM_ADMIN", "ACCESS_ADMIN"):
            return self._denied()
        try:
            body = await _json_body(request)
            grant_id = UUID(request.path_params["grant_id"])
            # Scope is rechecked against the stored grant before mutation.
            rows = await self.repository.list_grants(ctx)
            if not any(str(item["grant_id"]) == str(grant_id) for item in rows):
                return self._denied()
            result = await self.mutations.revoke_grant(
                actor=self._actor(ctx),
                grant_id=grant_id,
                expected_version=int(body.get("expected_version", 0)),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def platform_role_create(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        if ctx.source_scope("PLATFORM_ADMIN") is not None:
            return self._denied()
        try:
            body = await _json_body(request)
            result = await self.mutations.create_platform_role(
                actor=self._actor(ctx),
                principal_kind=str(body.get("principal_kind", "")),
                principal_id=str(body.get("principal_id", "")),
                role_name=str(body.get("role_name", "")),
                source_id=body.get("source_id"),
                expires_at=body.get("expires_at"),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result, status_code=201)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def platform_role_revoke(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        if ctx.source_scope("PLATFORM_ADMIN") is not None:
            return self._denied()
        try:
            body = await _json_body(request)
            result = await self.mutations.revoke_platform_role(
                actor=self._actor(ctx),
                binding_id=UUID(request.path_params["binding_id"]),
                expected_version=int(body.get("expected_version", 0)),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def business_role_assign(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        try:
            body = await _json_body(request)
            source_id = str(body.get("source_id", ""))
            if not ctx.can_admin_source(source_id, "PLATFORM_ADMIN", "ACCESS_ADMIN"):
                return self._denied()
            company_raw = body.get("company_id")
            result = await self.mutations.assign_business_role(
                actor=self._actor(ctx),
                principal_kind=str(body.get("principal_kind", "")),
                principal_id=str(body.get("principal_id", "")),
                role_id=str(body.get("role_id", "")),
                source_id=source_id,
                company_id=UUID(str(company_raw)) if company_raw else None,
                expires_at=body.get("expires_at"),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result, status_code=201)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def business_role_revoke(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        if not ctx.has_role("PLATFORM_ADMIN", "ACCESS_ADMIN"):
            return self._denied()
        try:
            assignment_id = UUID(request.path_params["assignment_id"])
            rows = await self.repository.list_business_role_assignments(ctx)
            if not any(str(item["assignment_id"]) == str(assignment_id) for item in rows):
                return self._denied()
            body = await _json_body(request)
            result = await self.mutations.revoke_business_role(
                actor=self._actor(ctx),
                assignment_id=assignment_id,
                expected_version=int(body.get("expected_version", 0)),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def capability_override_create(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        try:
            body = await _json_body(request)
            source_id = str(body.get("source_id", ""))
            if not ctx.can_admin_source(source_id, "PLATFORM_ADMIN", "ACCESS_ADMIN"):
                return self._denied()
            company_raw = body.get("company_id")
            result = await self.mutations.create_capability_override(
                actor=self._actor(ctx),
                principal_kind=str(body.get("principal_kind", "")),
                principal_id=str(body.get("principal_id", "")),
                capability_key=str(body.get("capability_key", "")),
                source_id=source_id,
                company_id=UUID(str(company_raw)) if company_raw else None,
                effect=str(body.get("effect", "")),
                expires_at=body.get("expires_at"),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result, status_code=201)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def capability_override_revoke(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        if not ctx.has_role("PLATFORM_ADMIN", "ACCESS_ADMIN"):
            return self._denied()
        try:
            override_id = UUID(request.path_params["override_id"])
            rows = await self.repository.list_capability_overrides(ctx)
            if not any(str(item["override_id"]) == str(override_id) for item in rows):
                return self._denied()
            body = await _json_body(request)
            result = await self.mutations.revoke_capability_override(
                actor=self._actor(ctx),
                override_id=override_id,
                expected_version=int(body.get("expected_version", 0)),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def semantic_profile_create(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        try:
            body = await _json_body(request)
            source_id = str(body.get("source_id", ""))
            if not ctx.can_admin_source(source_id, "PLATFORM_ADMIN", "PROFILE_ADMIN"):
                return self._denied()
            company_raw = body.get("company_id")
            result = await self.mutations.create_semantic_profile(
                actor=self._actor(ctx),
                source_id=source_id,
                company_id=UUID(str(company_raw)) if company_raw else None,
                preset_id=str(body.get("preset_id", "")),
                profile_name=str(body.get("profile_name", "")),
                profile_definition=body.get("profile_definition") or {},
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result, status_code=201)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def semantic_mapping_create(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        if not ctx.has_role("PLATFORM_ADMIN", "PROFILE_ADMIN"):
            return self._denied()
        try:
            profile_id = UUID(request.path_params["profile_id"])
            visible = await self.repository.list_profiles(ctx)
            if not any(str(item["profile_id"]) == str(profile_id) for item in visible):
                return self._denied()
            body = await _json_body(request)
            result = await self.mutations.add_semantic_mapping(
                actor=self._actor(ctx),
                profile_id=profile_id,
                canonical_concept=str(body.get("canonical_concept", "")),
                mapping_data=body.get("mapping") or {},
                evidence_data=body.get("evidence") or {},
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result, status_code=201)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def semantic_profile_validate(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        if not ctx.has_role("PLATFORM_ADMIN", "PROFILE_ADMIN"):
            return self._denied()
        try:
            profile_id = UUID(request.path_params["profile_id"])
            visible = await self.repository.list_profiles(ctx)
            if not any(str(item["profile_id"]) == str(profile_id) for item in visible):
                return self._denied()
            body = await _json_body(request)
            result = await self.mutations.validate_semantic_profile(
                actor=self._actor(ctx),
                profile_id=profile_id,
                validation_evidence_data=body.get("validation_evidence") or {},
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def semantic_profile_retire(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        if not ctx.has_role("PLATFORM_ADMIN", "PROFILE_ADMIN"):
            return self._denied()
        try:
            profile_id = UUID(request.path_params["profile_id"])
            visible = await self.repository.list_profiles(ctx)
            if not any(str(item["profile_id"]) == str(profile_id) for item in visible):
                return self._denied()
            body = await _json_body(request)
            result = await self.mutations.retire_semantic_profile(
                actor=self._actor(ctx),
                profile_id=profile_id,
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def company_scope_mapping_create(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        if not ctx.has_role("PLATFORM_ADMIN", "PROFILE_ADMIN"):
            return self._denied()
        try:
            body = await _json_body(request)
            profile_id = UUID(str(body.get("profile_id", "")))
            visible = await self.repository.list_profiles(ctx)
            if not any(str(item["profile_id"]) == str(profile_id) for item in visible):
                return self._denied()
            result = await self.mutations.create_company_scope_mapping(
                actor=self._actor(ctx),
                profile_id=profile_id,
                entity_set=str(body.get("entity_set", "")),
                company_property=str(body.get("company_property", "")),
                literal_kind=str(body.get("literal_kind", "")),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result, status_code=201)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)

    async def drift_ack(self, request: Request):
        ctx = await self.authenticate(request)
        if isinstance(ctx, JSONResponse):
            return ctx
        if self.mutations is None:
            return self._disabled()
        source_id = request.path_params["source_id"]
        if not ctx.can_admin_source(source_id, "PLATFORM_ADMIN", "SOURCE_ADMIN"):
            return self._denied()
        try:
            body = await _json_body(request)
            result = await self.mutations.acknowledge_drift(
                actor=self._actor(ctx),
                source_id=source_id,
                expected_fingerprint=str(body.get("expected_fingerprint", "")),
                reason=str(body.get("reason", "")),
                request_id=_request_id(request),
                idempotency_key=request.headers.get("idempotency-key", ""),
            )
            return JSONResponse(result)
        except Exception as exc:  # noqa: BLE001 - redact API boundary failures
            return self._mutation_error(exc)


def register_admin_routes(mcp, settings: Settings, runtime):
    if not settings.admin_api_enabled:
        return None
    api = AdminAPI(settings, runtime)
    routes = (
        ("/admin/v1/me", ["GET"], api.me),
        ("/admin/v1/overview", ["GET"], api.overview_view),
        ("/admin/v1/sources", ["GET"], api.sources),
        ("/admin/v1/sources/{source_id}", ["GET"], api.source_detail_view),
        ("/admin/v1/companies", ["GET"], api.companies),
        ("/admin/v1/companies/{company_id}", ["GET"], api.company_detail_view),
        ("/admin/v1/capabilities", ["GET"], api.capabilities),
        ("/admin/v1/grants", ["GET"], api.grants),
        (
            "/admin/v1/platform-role-bindings",
            ["GET"],
            api.platform_role_bindings,
        ),
        ("/admin/v1/principals/resolve", ["GET"], api.principal_resolve),
        ("/admin/v1/business-roles", ["GET"], api.business_roles),
        (
            "/admin/v1/business-role-assignments",
            ["GET"],
            api.business_role_assignments,
        ),
        ("/admin/v1/capability-overrides", ["GET"], api.capability_overrides),
        (
            "/admin/v1/company-scope-mappings",
            ["GET"],
            api.company_scope_mappings,
        ),
        ("/admin/v1/semantic-profiles", ["GET"], api.profiles),
        ("/admin/v1/audit", ["GET"], api.audit),
        ("/admin/v1/semantic-profiles", ["POST"], api.semantic_profile_create),
        (
            "/admin/v1/semantic-profiles/{profile_id}/mappings",
            ["POST"],
            api.semantic_mapping_create,
        ),
        (
            "/admin/v1/semantic-profiles/{profile_id}/validate",
            ["POST"],
            api.semantic_profile_validate,
        ),
        (
            "/admin/v1/semantic-profiles/{profile_id}/retire",
            ["POST"],
            api.semantic_profile_retire,
        ),
        ("/admin/v1/source-probes", ["POST"], api.source_probe),
        ("/admin/v1/sources", ["POST"], api.source_create),
        ("/admin/v1/sources/{source_id}", ["PATCH"], api.source_update),
        (
            "/admin/v1/sources/{source_id}/capability-refresh",
            ["POST"],
            api.capability_refresh,
        ),
        ("/admin/v1/companies", ["POST"], api.company_create),
        ("/admin/v1/companies/{company_id}", ["PATCH"], api.company_update),
        ("/admin/v1/grants", ["POST"], api.grant_create),
        ("/admin/v1/grants/{grant_id}/revoke", ["POST"], api.grant_revoke),
        ("/admin/v1/platform-role-bindings", ["POST"], api.platform_role_create),
        (
            "/admin/v1/platform-role-bindings/{binding_id}/revoke",
            ["POST"],
            api.platform_role_revoke,
        ),
        (
            "/admin/v1/business-role-assignments",
            ["POST"],
            api.business_role_assign,
        ),
        (
            "/admin/v1/business-role-assignments/{assignment_id}/revoke",
            ["POST"],
            api.business_role_revoke,
        ),
        (
            "/admin/v1/capability-overrides",
            ["POST"],
            api.capability_override_create,
        ),
        (
            "/admin/v1/capability-overrides/{override_id}/revoke",
            ["POST"],
            api.capability_override_revoke,
        ),
        (
            "/admin/v1/company-scope-mappings",
            ["POST"],
            api.company_scope_mapping_create,
        ),
        (
            "/admin/v1/sources/{source_id}/drift-acknowledgements",
            ["POST"],
            api.drift_ack,
        ),
    )
    for path, methods, handler in routes:
        if any(method in {"POST", "PUT", "PATCH", "DELETE"} for method in methods):
            async def guarded(request, _handler=handler):
                guard = await api.csrf_guard(request)
                if guard is not None:
                    return guard
                return await _handler(request)

            mcp.custom_route(path, methods=methods)(guarded)
        else:
            mcp.custom_route(path, methods=methods)(handler)

    if settings.admin_ui_enabled:
        mcp.custom_route("/admin", methods=["GET"])(api.admin_root)
        mcp.custom_route("/admin/", methods=["GET"])(api.admin_ui)
        mcp.custom_route("/admin/login", methods=["GET"])(api.login)
        mcp.custom_route("/admin/callback", methods=["GET"])(api.callback)
        mcp.custom_route("/admin/logout", methods=["POST"])(api.logout)
    return api
