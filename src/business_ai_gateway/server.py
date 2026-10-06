from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from .audit import AuditCorrelationMiddleware
from .auth import JWTTokenVerifier
from .compatibility import MetadataDriftUnacknowledged, require_acknowledged_metadata
from .principal import current_principal
from .runtime import Runtime
from .settings import Settings


def _count_items(payload: Any) -> int | None:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict) and isinstance(payload.get("value"), list):
        return len(payload["value"])
    return None


def build_mcp(settings: Settings, runtime: Runtime) -> MCPServer:
    @asynccontextmanager
    async def lifespan(_server):
        await runtime.start()
        try:
            yield {"runtime": runtime}
        finally:
            await runtime.close()

    kwargs: dict[str, Any] = {"lifespan": lifespan}
    if settings.oauth_enabled:
        kwargs["token_verifier"] = JWTTokenVerifier(settings)
        kwargs["auth"] = AuthSettings(
            issuer_url=AnyHttpUrl(settings.oauth_issuer),
            resource_server_url=AnyHttpUrl(settings.public_mcp_url),
            required_scopes=[settings.oauth_required_scope],
            validate_token_resource=True,
        )

    kwargs["middleware"] = [AuditCorrelationMiddleware()]
    mcp = MCPServer("ERP_MCP — 1C Production", **kwargs)

    async def ctx():
        principal = current_principal(oauth_enabled=settings.oauth_enabled)
        if settings.oauth_required_scope not in principal.scopes:
            raise PermissionError("required scope missing")
        return principal

    async def resolve_source(principal, source_id, tool, started, query=None):
        try:
            source = await runtime.registry.require_source(principal, source_id)
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool=tool,
                source_id=source_id,
                outcome="denied",
                started_at=started,
                query=query,
                detail_code=type(exc).__name__,
            )
            raise
        try:
            await runtime.rate_limit.check(
                subject=principal.subject,
                source_id=source_id,
                tool=tool,
            )
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool=tool,
                source_id=source_id,
                outcome="denied",
                started_at=started,
                query=query,
                detail_code=type(exc).__name__,
            )
            raise
        return source

    async def resolve_company_source(
        principal,
        source_id,
        company_id,
        tool,
        started,
        query=None,
    ):
        try:
            source, company = await runtime.registry.require_company_source(
                principal, source_id, company_id
            )
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool=tool,
                source_id=source_id,
                company_id=company_id,
                outcome="denied",
                started_at=started,
                query=query,
                detail_code=type(exc).__name__,
            )
            raise
        try:
            await runtime.rate_limit.check(
                subject=principal.subject,
                source_id=source_id,
                tool=tool,
            )
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool=tool,
                source_id=source_id,
                company_id=company_id,
                outcome="denied",
                started_at=started,
                query=query,
                detail_code=type(exc).__name__,
            )
            raise
        return source, company

    async def require_business_capability(
        principal,
        capability,
        source_id,
        tool,
        started,
        *,
        company_id=None,
        query=None,
    ):
        if not settings.business_capability_enforcement_enabled:
            return None
        try:
            return await runtime.capability_policy.require(
                principal,
                capability,
                source_id=source_id,
                company_id=company_id,
            )
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool=tool,
                source_id=source_id,
                company_id=company_id,
                outcome="denied",
                started_at=started,
                query=query,
                policy_version=runtime.capability_policy.POLICY_VERSION,
                detail_code=getattr(exc, "code", type(exc).__name__),
            )
            raise

    @mcp.tool()
    async def system_status() -> dict[str, Any]:
        """Return safe, non-secret gateway status."""
        started = time.monotonic()
        principal = await ctx()
        try:
            sources = await runtime.registry.list_allowed(principal)
            result = {
                "mode": "1c-production",
                "read_only": True,
                "subject": principal.subject,
                "accessible_sources": len(sources),
                "max_rows": settings.max_rows,
                "capability_negotiation": True,
                "adapter_profiles": [
                    "ODATA_JSON_V3",
                    "ODATA_ATOM_V3",
                    "HTTP_QUERY_FALLBACK",
                ],
                "future_adapters": {"erp": "reserved", "ferma": "reserved"},
            }
            await runtime.audit.write(
                principal=principal,
                tool="system_status",
                source_id=None,
                outcome="success",
                started_at=started,
            )
            return result
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="system_status",
                source_id=None,
                outcome="error",
                started_at=started,
                detail_code=type(exc).__name__,
            )
            raise

    @mcp.tool()
    async def sources_list() -> list[dict[str, Any]]:
        """List registered sources visible to the authenticated principal."""
        started = time.monotonic()
        principal = await ctx()
        try:
            sources = await runtime.registry.list_allowed(principal)
            result = [
                {
                    "id": source.id,
                    "project": source.project,
                    "kind": source.kind,
                    "display_name": source.display_name,
                    "tags": list(source.tags),
                    "read_only": source.read_only,
                }
                for source in sources
            ]
            await runtime.audit.write(
                principal=principal,
                tool="sources_list",
                source_id=None,
                outcome="success",
                started_at=started,
                returned_items=len(result),
            )
            return result
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="sources_list",
                source_id=None,
                outcome="error",
                started_at=started,
                detail_code=type(exc).__name__,
            )
            raise

    @mcp.tool()
    async def source_health(source_id: str) -> dict[str, Any]:
        """Check one authorized registered 1C OData source."""
        started = time.monotonic()
        principal = await ctx()
        source = await resolve_source(
            principal, source_id, "source_health", started
        )
        policy_version = await require_business_capability(
            principal, "source.status.read", source_id, "source_health", started
        )
        try:
            result = await runtime.onec.health(source)
            await runtime.audit.write(
                principal=principal,
                tool="source_health",
                source_id=source_id,
                outcome="success",
                started_at=started,
                policy_version=policy_version,
            )
            return result
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="source_health",
                source_id=source_id,
                outcome="error",
                started_at=started,
                detail_code=type(exc).__name__,
            )
            raise

    @mcp.tool()
    async def companies_list(source_id: str) -> list[dict[str, Any]]:
        """List enabled 1C organizations covered by this principal's grants."""
        started = time.monotonic()
        principal = await ctx()
        policy_version = await require_business_capability(
            principal, "company.list", source_id, "companies_list", started
        )
        try:
            await runtime.rate_limit.check(
                subject=principal.subject,
                source_id=source_id,
                tool="companies_list",
            )
            companies = await runtime.registry.list_allowed_companies(principal, source_id)
            result = [
                {
                    "company_id": str(company.id),
                    "source_id": company.source_id,
                    "external_ref": company.external_ref,
                    "display_name": company.display_name,
                    "legal_name": company.legal_name,
                    "country_code": company.country_code,
                    "default": company.is_default,
                }
                for company in companies
            ]
            await runtime.audit.write(
                principal=principal,
                tool="companies_list",
                source_id=source_id,
                outcome="success",
                started_at=started,
                returned_items=len(result),
                policy_version=policy_version,
            )
            return result
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="companies_list",
                source_id=source_id,
                outcome="error",
                started_at=started,
                detail_code=type(exc).__name__,
            )
            raise

    @mcp.tool()
    async def onec_capabilities(
        source_id: str,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Detect and persist the safest compatible transport profile for a 1C source."""
        started = time.monotonic()
        principal = await ctx()
        source = await resolve_source(
            principal,
            source_id,
            "onec_capabilities",
            started,
            {"refresh": refresh},
        )
        policy_version = await require_business_capability(
            principal,
            "metadata.read",
            source_id,
            "onec_capabilities",
            started,
            query={"refresh": refresh},
        )
        try:
            capabilities = await runtime.onec.capabilities(source, refresh=refresh)
            drift = await runtime.registry.save_capabilities(capabilities)
            result = capabilities.as_dict()
            result.update(drift)
            await runtime.audit.write(
                principal=principal,
                tool="onec_capabilities",
                source_id=source_id,
                outcome="success",
                started_at=started,
                query={"refresh": refresh},
                adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                policy_version=policy_version,
                detail_code=(
                    "METADATA_DRIFTED" if drift["drift_status"] == "DRIFTED" else None
                ),
            )
            return result
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="onec_capabilities",
                source_id=source_id,
                outcome="error",
                started_at=started,
                query={"refresh": refresh},
                detail_code=type(exc).__name__,
            )
            raise

    @mcp.tool()
    async def onec_metadata_summary(
        source_id: str,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Summarize live OData EntitySets for one authorized 1C source."""
        started = time.monotonic()
        principal = await ctx()
        source = await resolve_source(
            principal,
            source_id,
            "onec_metadata_summary",
            started,
            {"refresh": refresh},
        )
        policy_version = await require_business_capability(
            principal,
            "metadata.read",
            source_id,
            "onec_metadata_summary",
            started,
            query={"refresh": refresh},
        )
        try:
            if refresh:
                await runtime.onec.metadata(source, refresh=True)
            result = await runtime.onec.summary(source)
            await runtime.audit.write(
                principal=principal,
                tool="onec_metadata_summary",
                source_id=source_id,
                outcome="success",
                started_at=started,
                policy_version=policy_version,
            )
            return result
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="onec_metadata_summary",
                source_id=source_id,
                outcome="error",
                started_at=started,
                detail_code=type(exc).__name__,
            )
            raise

    @mcp.tool()
    async def onec_find_entities(
        source_id: str,
        contains: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search allowed EntitySets and fields in live 1C metadata."""
        started = time.monotonic()
        principal = await ctx()
        query = {"contains": contains, "limit": limit}
        source = await resolve_source(
            principal, source_id, "onec_find_entities", started, query
        )
        policy_version = await require_business_capability(
            principal,
            "metadata.read",
            source_id,
            "onec_find_entities",
            started,
            query=query,
        )
        try:
            result = await runtime.onec.find(source, contains, limit)
            await runtime.audit.write(
                principal=principal,
                tool="onec_find_entities",
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=len(result),
                policy_version=policy_version,
            )
            return result
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="onec_find_entities",
                source_id=source_id,
                outcome="error",
                started_at=started,
                query=query,
                detail_code=type(exc).__name__,
            )
            raise

    @mcp.tool()
    async def onec_company_read(
        source_id: str,
        company_id: str,
        entity_set: str,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        expand: list[str] | None = None,
        top: int = 50,
        skip: int = 0,
    ) -> dict[str, Any] | list[Any]:
        """Read one EntitySet through a validated company-scope semantic mapping."""
        started = time.monotonic()
        principal = await ctx()
        company_uuid = UUID(company_id)
        query = {
            "entity_set": entity_set,
            "select": select,
            "filter_expr": filter_expr,
            "orderby": orderby,
            "expand": expand,
            "top": top,
            "skip": skip,
        }
        source, company = await resolve_company_source(
            principal,
            source_id,
            company_uuid,
            "onec_company_read",
            started,
            query,
        )
        policy_version = await require_business_capability(
            principal,
            "accounting.read",
            source_id,
            "onec_company_read",
            started,
            company_id=company_uuid,
            query=query,
        )
        try:
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            mapping = await runtime.company_scope.mapping(
                source=source,
                company=company,
                entity_set=entity_set,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                drift_status=drift["drift_status"],
            )
            index = await runtime.onec.metadata(source)
            runtime.company_scope.verify_metadata_property(
                index,
                entity_set=entity_set,
                property_name=mapping.company_property,
            )
            company_filter = runtime.company_scope.filter_for(mapping, company)
            bounded_filter = runtime.company_scope.combine(company_filter, filter_expr)
            result = await runtime.onec.read(
                source,
                entity_set=entity_set,
                select=select,
                filter_expr=bounded_filter,
                orderby=orderby,
                expand=expand,
                top=top,
                skip=skip,
            )
            response_bytes = len(
                json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
            )
            await runtime.audit.write(
                principal=principal,
                tool="onec_company_read",
                source_id=source_id,
                company_id=company_uuid,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=_count_items(result),
                adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                policy_version=policy_version,
                response_bytes=response_bytes,
                detail_code=f"PROFILE:{mapping.profile_fingerprint}",
            )
            return result
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="onec_company_read",
                source_id=source_id,
                company_id=company_uuid,
                outcome="error",
                started_at=started,
                query=query,
                policy_version=policy_version,
                detail_code=getattr(exc, "code", type(exc).__name__),
            )
            raise

    @mcp.tool()
    async def onec_read(
        source_id: str,
        entity_set: str,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        expand: list[str] | None = None,
        top: int = 50,
        skip: int = 0,
    ) -> dict[str, Any] | list[Any]:
        """Read one authorized 1C OData EntitySet. This tool cannot mutate 1C."""
        started = time.monotonic()
        principal = await ctx()
        query = {
            "entity_set": entity_set,
            "select": select,
            "filter_expr": filter_expr,
            "orderby": orderby,
            "expand": expand,
            "top": top,
            "skip": skip,
        }
        source = await resolve_source(
            principal, source_id, "onec_read", started, query
        )
        policy_version = await require_business_capability(
            principal,
            "accounting.read",
            source_id,
            "onec_read",
            started,
            query=query,
        )
        try:
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            result = await runtime.onec.read(
                source,
                entity_set=entity_set,
                select=select,
                filter_expr=filter_expr,
                orderby=orderby,
                expand=expand,
                top=top,
                skip=skip,
            )
            response_bytes = len(
                json.dumps(result, ensure_ascii=False, default=str).encode("utf-8")
            )
            await runtime.audit.write(
                principal=principal,
                tool="onec_read",
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=_count_items(result),
                adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                response_bytes=response_bytes,
                policy_version=policy_version,
                detail_code=(
                    "METADATA_DRIFTED" if drift["drift_status"] == "DRIFTED" else None
                ),
            )
            return result
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="onec_read",
                source_id=source_id,
                outcome="error",
                started_at=started,
                query=query,
                detail_code=(
                    "METADATA_DRIFTED"
                    if isinstance(exc, MetadataDriftUnacknowledged)
                    else type(exc).__name__
                ),
            )
            raise

    return mcp
