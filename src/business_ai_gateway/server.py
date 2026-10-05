from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl

from .audit import AuditCorrelationMiddleware
from .auth import JWTTokenVerifier
from .compatibility import (
    CapabilityUnsupported,
    MetadataDriftUnacknowledged,
    require_acknowledged_metadata,
)
from .principal import current_principal
from .runtime import Runtime
from .semantic import (
    ACCOUNT_TURNOVERS_CONCEPT,
    BANK_BALANCE_CONCEPT,
    INVENTORY_BALANCE_CONCEPT,
    PAYABLE_BALANCE_CONCEPT,
    RECEIVABLE_BALANCE_CONCEPT,
    SemanticProfileUnavailable,
    build_account_turnovers_arguments,
    build_bank_balance_arguments,
    build_company_filter,
    build_inventory_balance_arguments,
    build_settlement_balance_arguments,
    normalize_account_turnovers,
    normalize_bank_balance_rows,
    normalize_document_rows,
    normalize_inventory_balance_rows,
    normalize_settlement_balance_rows,
)
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

    async def resolve_source(
        principal, source_id, tool, started, query=None, company_id=None
    ):
        try:
            if company_id is None:
                source = await runtime.registry.require_source(principal, source_id)
            else:
                source = await runtime.registry.require_source_for_company(
                    principal, source_id, company_id
                )
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool=tool,
                source_id=source_id,
                outcome="denied",
                started_at=started,
                query=query,
                company_id=company_id,
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
                company_id=company_id,
                detail_code=type(exc).__name__,
            )
            raise
        return source

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
    async def companies_list(source_id: str) -> list[dict[str, Any]]:
        """List enabled 1C organizations covered by this principal's grants."""
        started = time.monotonic()
        principal = await ctx()
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
    async def accounting_balance_and_turnovers(
        source_id: str,
        company_id: str,
        start_period: str,
        end_period: str,
    ) -> dict[str, Any]:
        """Read company-filtered account balances/turnovers via its validated semantic profile."""
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal,
                tool="accounting_balance_and_turnovers",
                source_id=source_id,
                outcome="denied",
                started_at=started,
                company_id=None,
                detail_code="INVALID_COMPANY_ID",
            )
            raise ValueError("company_id must be a UUID") from exc
        query = {
            "company_id": str(parsed_company_id),
            "concept": ACCOUNT_TURNOVERS_CONCEPT,
            "start_period": start_period,
            "end_period": end_period,
        }
        source = await resolve_source(
            principal,
            source_id,
            "accounting_balance_and_turnovers",
            started,
            query,
            company_id=parsed_company_id,
        )
        capabilities = None
        try:
            company = await runtime.registry.require_company(
                principal, source_id, parsed_company_id
            )
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            profile = await runtime.registry.require_account_turnovers_mapping(
                source_id, parsed_company_id
            )
            mapping = profile["mapping"]
            register_set, method, arguments = build_account_turnovers_arguments(
                mapping,
                company_external_ref=company.external_ref,
                start_period=start_period,
                end_period=end_period,
            )
            result = await runtime.onec.register_read(
                source,
                register_set=register_set,
                method=method,
                arguments=arguments,
                top=settings.max_rows,
            )
            raw_rows = result.get("value", []) if isinstance(result, dict) else result
            normalized_rows = normalize_account_turnovers(raw_rows, mapping)
            response_bytes = len(
                json.dumps(normalized_rows, ensure_ascii=False, default=str).encode("utf-8")
            )
            await runtime.audit.write(
                principal=principal,
                tool="accounting_balance_and_turnovers",
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=len(normalized_rows),
                company_id=parsed_company_id,
                adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                response_bytes=response_bytes,
            )
            return {
                "source_id": source_id,
                "company_id": str(parsed_company_id),
                "concept": ACCOUNT_TURNOVERS_CONCEPT,
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                "value": normalized_rows,
                "page": result.get("page") if isinstance(result, dict) else None,
                "warnings": [],
            }
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="accounting_balance_and_turnovers",
                source_id=source_id,
                outcome=(
                    "denied"
                    if isinstance(
                        exc,
                        (
                            PermissionError,
                            CapabilityUnsupported,
                            MetadataDriftUnacknowledged,
                            SemanticProfileUnavailable,
                        ),
                    )
                    else "error"
                ),
                started_at=started,
                query=query,
                company_id=parsed_company_id,
                adapter_kind=(capabilities.adapter_profile.value if capabilities else None),
                metadata_fingerprint=(capabilities.metadata_fingerprint if capabilities else None),
                detail_code=getattr(exc, "code", type(exc).__name__),
            )
            raise

    @mcp.tool()
    async def inventory_balance(source_id: str, company_id: str, period: str) -> dict[str, Any]:
        """Read a point-in-time, company-scoped inventory balance via a validated profile."""
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal,
                tool="inventory_balance",
                source_id=source_id,
                outcome="denied",
                started_at=started,
                detail_code="INVALID_COMPANY_ID",
            )
            raise ValueError("company_id must be a UUID") from exc
        query = {
            "company_id": str(parsed_company_id),
            "concept": INVENTORY_BALANCE_CONCEPT,
            "period": period,
        }
        source = await resolve_source(
            principal,
            source_id,
            "inventory_balance",
            started,
            query,
            company_id=parsed_company_id,
        )
        capabilities = None
        try:
            company = await runtime.registry.require_company(
                principal, source_id, parsed_company_id
            )
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            profile = await runtime.registry.require_semantic_mapping(
                source_id, parsed_company_id, INVENTORY_BALANCE_CONCEPT
            )
            mapping = profile["mapping"]
            register_set, method, arguments = build_inventory_balance_arguments(
                mapping, company_external_ref=company.external_ref, period=period
            )
            result = await runtime.onec.register_read(
                source,
                register_set=register_set,
                method=method,
                arguments=arguments,
                top=settings.max_rows,
            )
            raw_rows = result.get("value", []) if isinstance(result, dict) else result
            normalized_rows = normalize_inventory_balance_rows(raw_rows, mapping)
            response_bytes = len(
                json.dumps(normalized_rows, ensure_ascii=False, default=str).encode("utf-8")
            )
            await runtime.audit.write(
                principal=principal,
                tool="inventory_balance",
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=len(normalized_rows),
                company_id=parsed_company_id,
                adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                response_bytes=response_bytes,
            )
            return {
                "source_id": source_id,
                "company_id": str(parsed_company_id),
                "concept": INVENTORY_BALANCE_CONCEPT,
                "period": period,
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                "value": normalized_rows,
                "page": result.get("page") if isinstance(result, dict) else None,
                "warnings": [],
            }
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="inventory_balance",
                source_id=source_id,
                outcome=(
                    "denied"
                    if isinstance(
                        exc,
                        (
                            PermissionError,
                            CapabilityUnsupported,
                            MetadataDriftUnacknowledged,
                            SemanticProfileUnavailable,
                        ),
                    )
                    else "error"
                ),
                started_at=started,
                query=query,
                company_id=parsed_company_id,
                adapter_kind=(capabilities.adapter_profile.value if capabilities else None),
                metadata_fingerprint=(capabilities.metadata_fingerprint if capabilities else None),
                detail_code=getattr(exc, "code", type(exc).__name__),
            )
            raise

    @mcp.tool()
    async def bank_balance(source_id: str, company_id: str, period: str) -> dict[str, Any]:
        """Read a point-in-time bank balance via an exact, validated source profile."""
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal,
                tool="bank_balance",
                source_id=source_id,
                outcome="denied",
                started_at=started,
                detail_code="INVALID_COMPANY_ID",
            )
            raise ValueError("company_id must be a UUID") from exc
        query = {
            "company_id": str(parsed_company_id),
            "concept": BANK_BALANCE_CONCEPT,
            "period": period,
        }
        source = await resolve_source(
            principal, source_id, "bank_balance", started, query, company_id=parsed_company_id
        )
        capabilities = None
        try:
            company = await runtime.registry.require_company(
                principal, source_id, parsed_company_id
            )
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            profile = await runtime.registry.require_semantic_mapping(
                source_id, parsed_company_id, BANK_BALANCE_CONCEPT
            )
            mapping = profile["mapping"]
            register_set, method, arguments = build_bank_balance_arguments(
                mapping, company_external_ref=company.external_ref, period=period
            )
            result = await runtime.onec.register_read(
                source,
                register_set=register_set,
                method=method,
                arguments=arguments,
                top=settings.max_rows,
            )
            raw_rows = result.get("value", []) if isinstance(result, dict) else result
            normalized_rows = normalize_bank_balance_rows(raw_rows, mapping)
            response_bytes = len(
                json.dumps(normalized_rows, ensure_ascii=False, default=str).encode("utf-8")
            )
            await runtime.audit.write(
                principal=principal,
                tool="bank_balance",
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=len(normalized_rows),
                company_id=parsed_company_id,
                adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                response_bytes=response_bytes,
            )
            return {
                "source_id": source_id,
                "company_id": str(parsed_company_id),
                "concept": BANK_BALANCE_CONCEPT,
                "period": period,
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                "value": normalized_rows,
                "page": result.get("page") if isinstance(result, dict) else None,
                "warnings": [],
            }
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="bank_balance",
                source_id=source_id,
                outcome=(
                    "denied"
                    if isinstance(
                        exc,
                        (
                            PermissionError,
                            CapabilityUnsupported,
                            MetadataDriftUnacknowledged,
                            SemanticProfileUnavailable,
                        ),
                    )
                    else "error"
                ),
                started_at=started,
                query=query,
                company_id=parsed_company_id,
                adapter_kind=(capabilities.adapter_profile.value if capabilities else None),
                metadata_fingerprint=(capabilities.metadata_fingerprint if capabilities else None),
                detail_code=getattr(exc, "code", type(exc).__name__),
            )
            raise

    async def read_settlement_balance(
        source_id: str,
        company_id: str,
        period: str,
        *,
        concept: str,
        tool_name: str,
    ) -> dict[str, Any]:
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal,
                tool=tool_name,
                source_id=source_id,
                outcome="denied",
                started_at=started,
                detail_code="INVALID_COMPANY_ID",
            )
            raise ValueError("company_id must be a UUID") from exc
        query = {"company_id": str(parsed_company_id), "concept": concept, "period": period}
        source = await resolve_source(
            principal, source_id, tool_name, started, query, company_id=parsed_company_id
        )
        capabilities = None
        try:
            company = await runtime.registry.require_company(
                principal, source_id, parsed_company_id
            )
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            profile = await runtime.registry.require_semantic_mapping(
                source_id, parsed_company_id, concept
            )
            mapping = profile["mapping"]
            register_set, method, arguments = build_settlement_balance_arguments(
                concept, mapping, company_external_ref=company.external_ref, period=period
            )
            result = await runtime.onec.register_read(
                source,
                register_set=register_set,
                method=method,
                arguments=arguments,
                top=settings.max_rows,
            )
            raw_rows = result.get("value", []) if isinstance(result, dict) else result
            rows = normalize_settlement_balance_rows(raw_rows, mapping, concept)
            response_bytes = len(json.dumps(rows, ensure_ascii=False, default=str).encode("utf-8"))
            await runtime.audit.write(
                principal=principal,
                tool=tool_name,
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=len(rows),
                company_id=parsed_company_id,
                adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                response_bytes=response_bytes,
            )
            return {
                "source_id": source_id,
                "company_id": str(parsed_company_id),
                "concept": concept,
                "period": period,
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                "value": rows,
                "page": result.get("page") if isinstance(result, dict) else None,
                "warnings": [],
            }
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool=tool_name,
                source_id=source_id,
                outcome=(
                    "denied"
                    if isinstance(
                        exc,
                        (
                            PermissionError,
                            CapabilityUnsupported,
                            MetadataDriftUnacknowledged,
                            SemanticProfileUnavailable,
                        ),
                    )
                    else "error"
                ),
                started_at=started,
                query=query,
                company_id=parsed_company_id,
                adapter_kind=(capabilities.adapter_profile.value if capabilities else None),
                metadata_fingerprint=(capabilities.metadata_fingerprint if capabilities else None),
                detail_code=getattr(exc, "code", type(exc).__name__),
            )
            raise

    @mcp.tool()
    async def receivable_balance(source_id: str, company_id: str, period: str) -> dict[str, Any]:
        """Read point-in-time receivable balances; this tool does not compute aging buckets."""
        return await read_settlement_balance(
            source_id,
            company_id,
            period,
            concept=RECEIVABLE_BALANCE_CONCEPT,
            tool_name="receivable_balance",
        )

    @mcp.tool()
    async def payable_balance(source_id: str, company_id: str, period: str) -> dict[str, Any]:
        """Read point-in-time payable balances; this tool does not compute aging buckets."""
        return await read_settlement_balance(
            source_id,
            company_id,
            period,
            concept=PAYABLE_BALANCE_CONCEPT,
            tool_name="payable_balance",
        )

    async def read_company_documents(
        source_id: str,
        company_id: str,
        *,
        concept: str,
        tool_name: str,
        top: int,
        skip: int,
    ) -> dict[str, Any]:
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal,
                tool=tool_name,
                source_id=source_id,
                outcome="denied",
                started_at=started,
                detail_code="INVALID_COMPANY_ID",
            )
            raise ValueError("company_id must be a UUID") from exc
        if top < 1 or skip < 0:
            raise ValueError("top must be positive and skip cannot be negative")
        bounded_top = min(top, settings.max_rows)
        query = {
            "company_id": str(parsed_company_id),
            "concept": concept,
            "top": bounded_top,
            "skip": skip,
        }
        source = await resolve_source(
            principal,
            source_id,
            tool_name,
            started,
            query,
            company_id=parsed_company_id,
        )
        capabilities = None
        try:
            company = await runtime.registry.require_company(
                principal, source_id, parsed_company_id
            )
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            profile = await runtime.registry.require_semantic_mapping(
                source_id, parsed_company_id, concept
            )
            mapping = profile["mapping"]
            company_filter = build_company_filter(mapping, company.external_ref)
            result = await runtime.onec.read(
                source,
                entity_set=mapping["entity_set"],
                select=list(mapping["output_fields"].values()),
                filter_expr=company_filter,
                orderby=f"{mapping['order_by']} desc",
                expand=None,
                top=bounded_top,
                skip=skip,
            )
            raw_rows = result.get("value", []) if isinstance(result, dict) else result
            normalized_rows = normalize_document_rows(raw_rows, mapping, concept)
            response_bytes = len(
                json.dumps(normalized_rows, ensure_ascii=False, default=str).encode("utf-8")
            )
            await runtime.audit.write(
                principal=principal,
                tool=tool_name,
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=len(normalized_rows),
                company_id=parsed_company_id,
                adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                response_bytes=response_bytes,
            )
            return {
                "source_id": source_id,
                "company_id": str(parsed_company_id),
                "concept": concept,
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                "value": normalized_rows,
                "page": result.get("page") if isinstance(result, dict) else None,
                "warnings": [],
            }
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool=tool_name,
                source_id=source_id,
                outcome=(
                    "denied"
                    if isinstance(
                        exc,
                        (
                            PermissionError,
                            CapabilityUnsupported,
                            MetadataDriftUnacknowledged,
                            SemanticProfileUnavailable,
                        ),
                    )
                    else "error"
                ),
                started_at=started,
                query=query,
                company_id=parsed_company_id,
                adapter_kind=(capabilities.adapter_profile.value if capabilities else None),
                metadata_fingerprint=(capabilities.metadata_fingerprint if capabilities else None),
                detail_code=getattr(exc, "code", type(exc).__name__),
            )
            raise

    @mcp.tool()
    async def sales_documents(
        source_id: str, company_id: str, top: int = 50, skip: int = 0
    ) -> dict[str, Any]:
        """List company-scoped sales documents using a validated semantic mapping."""
        return await read_company_documents(
            source_id,
            company_id,
            concept="sales",
            tool_name="sales_documents",
            top=top,
            skip=skip,
        )

    @mcp.tool()
    async def purchase_documents(
        source_id: str, company_id: str, top: int = 50, skip: int = 0
    ) -> dict[str, Any]:
        """List company-scoped purchase documents using a validated semantic mapping."""
        return await read_company_documents(
            source_id,
            company_id,
            concept="purchases",
            tool_name="purchase_documents",
            top=top,
            skip=skip,
        )

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
