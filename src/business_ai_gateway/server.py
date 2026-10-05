from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from .auth import JWTTokenVerifier
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

    @mcp.tool()
    async def system_status() -> dict[str, Any]:
        """Return safe, non-secret gateway status."""
        principal = await ctx()
        sources = await runtime.registry.list_allowed(principal)
        return {
            "mode": "1c-production",
            "read_only": True,
            "subject": principal.subject,
            "accessible_sources": len(sources),
            "max_rows": settings.max_rows,
            "future_adapters": {"erp": "reserved", "ferma": "reserved"},
        }

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
        try:
            result = await runtime.onec.health(source)
            await runtime.audit.write(
                principal=principal,
                tool="source_health",
                source_id=source_id,
                outcome="success",
                started_at=started,
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
        try:
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
            await runtime.audit.write(
                principal=principal,
                tool="onec_read",
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=_count_items(result),
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
                detail_code=type(exc).__name__,
            )
            raise

    return mcp
