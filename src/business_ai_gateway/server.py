from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field

from .adapters.onec.com_contract import COM_MAX_ROWS, ComBalanceRequest
from .adapters.onec.rsv_bridge import METADATA_TOOLS
from .adapters.onec.rsv_bridge import UPSTREAM_SHA as RSV_UPSTREAM_SHA
from .analytics_balance import (
    ANALYTICS_BALANCE_CONCEPT,
    AnalyticsBalanceDenied,
    AnalyticsBalanceError,
    ComRouteUnsupported,
    build_analytics_balance_arguments,
    normalize_com_balance_rows,
    normalize_odata_balance_rows,
    select_route,
)
from .audit import AuditCorrelationMiddleware, AuditUnavailable
from .auth import JWTTokenVerifier
from .compatibility import (
    CapabilityUnsupported,
    MetadataDriftUnacknowledged,
    require_acknowledged_metadata,
)
from .duplicate_counterparties import (
    DUPLICATE_CONCEPT,
    DUPLICATE_FAILURE_REASONS,
    DuplicateResponseTooLarge,
    build_activity_query,
    build_catalog_query,
    evaluate_duplicate_candidates,
    rows_truncated,
)
from .duplicate_counterparties import (
    MAX_ROWS as MAX_DUPLICATE_ROWS,
)
from .external_evidence import EvidenceRejected
from .fixture_profiles import SYNTHETIC_PROFILE_KIND, profile_provenance
from .principal import current_principal
from .runtime import Runtime
from .semantic import (
    ACCOUNT_TURNOVERS_CONCEPT,
    ACCOUNTING_POSTING_ROWS_CONCEPT,
    BANK_BALANCE_CONCEPT,
    CASH_MOVEMENTS_CONCEPT,
    INVENTORY_BALANCE_CONCEPT,
    INVENTORY_MOVEMENTS_CONCEPT,
    PAYABLE_BALANCE_CONCEPT,
    RECEIVABLE_BALANCE_CONCEPT,
    SemanticProfileUnavailable,
    build_account_turnovers_arguments,
    build_accounting_posting_rows_query,
    build_bank_balance_arguments,
    build_cash_movements_query,
    build_company_filter,
    build_inventory_balance_arguments,
    build_inventory_movement_query,
    build_settlement_balance_arguments,
    normalize_account_turnovers,
    normalize_accounting_posting_rows,
    normalize_bank_balance_rows,
    normalize_cash_movement_rows,
    normalize_document_rows,
    normalize_inventory_balance_rows,
    normalize_inventory_movement_rows,
    normalize_settlement_balance_rows,
)
from .settings import Settings
from .settlement_collector import (
    MAX_OPEN_ITEM_ROWS,
    OPEN_ITEMS_FAILURE_REASONS,
    PAYABLE_OPEN_ITEMS_CONCEPT,
    RECEIVABLE_OPEN_ITEMS_CONCEPT,
    build_open_items_query,
    evaluate_open_items,
    parse_as_of,
)
from .supplier_debt_summary import summarize_supplier_5211, supplier_filter_batches, supplier_refs

CHATGPT_READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    openWorldHint=True,
)

CHATGPT_SERVER_INSTRUCTIONS = (
    "ERP_MCP is a read-only ERP/1C data gateway. Use only sources and companies returned for "
    "the authenticated principal. Never invent identifiers, broaden company scope, request or "
    "expose credentials, or imply that synthetic/test evidence is native 1C reconciliation. "
    "For supplier balances on account 521.1, first try accounting_balance_by_analytics "
    "with an explicit timezone offset in as_of; if supplier_summary is COMPLETE, show "
    "each counterparty credit and debit separately, and state the account-only and "
    "machine-evidence limitations. Never silently net advances, invent dates, or "
    "treat this report as payable aging. If a capability/profile is unavailable, "
    "report the refusal instead of guessing business data."
)

BUSINESS_CAPABILITY_BY_TOOL = {
    "source_health": "source.status.read",
    "rsv_metadata": "metadata.read",
    "companies_list": "company.list",
    "onec_capabilities": "metadata.read",
    "onec_metadata_summary": "metadata.read",
    "onec_find_entities": "metadata.read",
    "accounting_balance_and_turnovers": "accounting.read",
    "accounting_balance_by_analytics": "accounting.read",
    "inventory_balance": "inventory.read",
    "inventory_movements": "inventory.read",
    "accounting_posting_rows": "accounting.read",
    "cash_movements": "cash.read",
    "bank_balance": "bank.read",
    "receivable_balance": "ar.read",
    "payable_balance": "ap.read",
    "receivable_aging": "ar.read",
    "payable_aging": "ap.read",
    "counterparty_duplicate_candidates": "accounting.read",
    "sales_documents": "sales.read",
    "purchase_documents": "purchases.read",
    # Arbitrary EntitySet/filter OData reads are deliberately isolated from
    # semantic accounting capabilities and have no seeded business-role grant.
    "onec_read": "onec.raw.read",
}


def _count_items(payload: Any) -> int | None:
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict) and isinstance(payload.get("value"), list):
        return len(payload["value"])
    return None


def _metadata_entity_fields(metadata: Any, entity_set: str) -> set[str]:
    for entity in getattr(metadata, "entities", ()):
        if getattr(entity, "name", None) == entity_set:
            return set(getattr(entity, "properties", ()))
    return set()


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
    mcp = MCPServer(
        "ERP_MCP — 1C Production",
        title="ERP_MCP — secure read-only 1C/ERP gateway",
        description="Company-scoped read-only ERP/1C data, metadata and accounting tools.",
        instructions=CHATGPT_SERVER_INSTRUCTIONS,
        **kwargs,
    )

    async def ctx():
        principal = current_principal(oauth_enabled=settings.oauth_enabled)
        if settings.oauth_required_scope not in principal.scopes:
            raise PermissionError("required scope missing")
        return principal

    async def resolve_source(principal, source_id, tool, started, query=None, company_id=None):
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
        capability = BUSINESS_CAPABILITY_BY_TOOL.get(tool)
        if settings.business_capability_enforcement_enabled:
            if capability is None:
                raise PermissionError("business capability is not mapped for this operation")
            try:
                await runtime.capability_policy.require(
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
        # Durable access receipt before any external adapter/secret/capability call. This is
        # policy authorization success, NOT a successful business read; completion is separate.
        try:
            await runtime.audit.write(
                principal=principal, tool=tool, source_id=source_id, company_id=company_id,
                outcome='success', started_at=started, query=query,
                detail_code='ACCESS_AUTHORIZED', policy_version='predispatch-audit-v1',
                record_tool_outcome=False,
            )
        except Exception as exc:  # noqa: BLE001 -- provider boundary must sanitize every append failure
            # Do not retain provider traceback locals in the public SDK failure.
            exc.__traceback__ = None
            raise AuditUnavailable('AUDIT_UNAVAILABLE') from None
        return source

    async def deny_unconfirmed_semantic_capability(
        *,
        source_id: str,
        metadata_fingerprint: str,
        concept: str,
        entity_set: str,
        reason: str,
        expected_properties: list[str],
        missing_properties: list[str] | None = None,
        message: str,
    ) -> None:
        await runtime.registry.record_semantic_capability_evidence(
            source_id=source_id,
            concept=concept,
            entity_set=entity_set,
            metadata_fingerprint=metadata_fingerprint,
            reason=reason,
            expected_properties=expected_properties,
            missing_properties=missing_properties,
        )
        raise CapabilityUnsupported(message)

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def source_health(source_id: str) -> dict[str, Any]:
        """Check one authorized registered 1C OData source."""
        started = time.monotonic()
        principal = await ctx()
        source = await resolve_source(principal, source_id, "source_health", started)
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def external_evidence_manifest(
        source_id: Annotated[str, Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')],
        company_id: Annotated[str, Field(min_length=36, max_length=36)],
        evidence_id: Annotated[str, Field(pattern=r'^[a-f0-9]{32}$')],
    ) -> dict[str, Any]:
        """Read an approved private evidence's safe manifest only; no upload, raw facts or accounting PASS."""
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError:
            await runtime.audit.write(principal=principal, tool='external_evidence_manifest',
                source_id=source_id, outcome='denied', started_at=started, detail_code='INVALID_COMPANY_ID')
            raise ValueError('INVALID_COMPANY_ID') from None
        query = {'company_id': str(parsed_company_id), 'evidence_id': evidence_id}
        await resolve_source(principal, source_id, 'external_evidence_manifest', started, query,
                             company_id=parsed_company_id)
        try:
            provider = getattr(runtime, 'evidence_provider', None)
            if provider is None:
                raise EvidenceRejected('CAPABILITY_UNSUPPORTED')
            manifest = await provider.read_manifest_after_access_gate(source_id, parsed_company_id, evidence_id)
            await runtime.audit.write(principal=principal, tool='external_evidence_manifest',
                source_id=source_id, company_id=parsed_company_id, outcome='success', started_at=started,
                query=query, detail_code='EVIDENCE_MANIFEST_COMPLETE',
                profile_fingerprint=manifest['profile_fingerprint'], returned_items=manifest['fact_count'])
            return {'manifest': manifest, 'business_acceptance': 'NOT_EVALUATED', 'native_approval_inferred': False}
        except EvidenceRejected as exc:
            known = {'CAPABILITY_UNSUPPORTED', 'EVIDENCE_REQUIRED', 'EVIDENCE_REFERENCE_INVALID',
                     'EVIDENCE_APPROVAL_INVALID', 'EVIDENCE_APPROVAL_STALE', 'EVIDENCE_PROFILE_UNCONFIRMED',
                     'EVIDENCE_RETENTION_UNCONFIRMED', 'EVIDENCE_STORAGE_INTEGRITY_INVALID',
                     'EVIDENCE_FINGERPRINT_MISMATCH', 'EVIDENCE_READ_TIMEOUT'}
            code = str(exc) if str(exc) in known else 'EVIDENCE_READ_REJECTED'
            operation_error = code in {'EVIDENCE_READ_TIMEOUT', 'EVIDENCE_STORAGE_INTEGRITY_INVALID',
                                      'EVIDENCE_FINGERPRINT_MISMATCH'}
            await runtime.audit.write(principal=principal, tool='external_evidence_manifest',
                source_id=source_id, company_id=parsed_company_id,
                outcome='error' if operation_error else 'denied', started_at=started,
                query=query, detail_code=code)
            status = ('CAPABILITY_UNSUPPORTED' if code == 'CAPABILITY_UNSUPPORTED' else
                      'EVIDENCE_REQUIRED' if code == 'EVIDENCE_REQUIRED' else
                      'ERROR' if operation_error else 'INCONCLUSIVE')
            return {'status': status, 'reason': code, 'business_acceptance': 'NOT_EVALUATED',
                    'native_approval_inferred': False}

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def rsv_metadata(
        source_id: str,
        operation: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Read allowlisted RSV metadata only; business data/query tools are never proxied."""
        started = time.monotonic()
        principal = await ctx()
        source = await resolve_source(principal, source_id, "rsv_metadata", started)
        try:
            if source.kind != "onec_auto" or getattr(runtime, "rsv_bridge", None) is None:
                raise CapabilityUnsupported("CAPABILITY_UNSUPPORTED")
            if operation not in METADATA_TOOLS:
                raise CapabilityUnsupported("CAPABILITY_UNSUPPORTED")
            if settings.environment == "production" and not settings.rsv_bridge_config_secret_ref:
                raise CapabilityUnsupported("CAPABILITY_UNSUPPORTED")
            result = await runtime.onec.rsv_metadata(
                source,
                operation=operation,
                arguments=arguments,
                max_response_bytes=settings.max_response_bytes,
            )
            response_bytes = len(
                json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            await runtime.audit.write(
                principal=principal,
                tool="rsv_metadata",
                source_id=source_id,
                outcome="success",
                started_at=started,
                adapter_kind="RSV_DATA_METADATA",
                upstream_sha=RSV_UPSTREAM_SHA,
                adapter_version=f"sha256:{result['adapter']['executable_sha256']}",
                response_bytes=response_bytes,
                returned_items=_count_items(result.get("data")),
            )
            return result
        except Exception as exc:
            denied = isinstance(exc, (CapabilityUnsupported, PermissionError, ValueError))
            await runtime.audit.write(
                principal=principal,
                tool="rsv_metadata",
                source_id=source_id,
                outcome="denied" if denied else "error",
                started_at=started,
                adapter_kind="RSV_DATA_METADATA",
                upstream_sha=RSV_UPSTREAM_SHA,
                detail_code=getattr(exc, "code", type(exc).__name__),
            )
            raise

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def companies_list(source_id: str) -> list[dict[str, Any]]:
        """List enabled 1C organizations covered by this principal's grants."""
        started = time.monotonic()
        principal = await ctx()
        try:
            if settings.business_capability_enforcement_enabled:
                await runtime.capability_policy.require(
                    principal,
                    "company.list",
                    source_id=source_id,
                )
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
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
                detail_code=("METADATA_DRIFTED" if drift["drift_status"] == "DRIFTED" else None),
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def onec_find_entities(
        source_id: str,
        contains: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search allowed EntitySets and fields in live 1C metadata."""
        started = time.monotonic()
        principal = await ctx()
        query = {"contains": contains, "limit": limit}
        source = await resolve_source(principal, source_id, "onec_find_entities", started, query)
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
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
                detail_code=profile.get("audit_detail_code"),
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
                **profile_provenance(profile),
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def accounting_balance_by_analytics(
        source_id: str, company_id: str, as_of: str
    ) -> dict[str, Any]:
        """Read validated account balances by analytics. as_of requires ISO 8601 with offset.

        Example: 2026-08-31T23:59:59+03:00 for end of August in Moldova.
        When the validated profile covers only account 521.1, returns a supplier_summary
        with counterparty names and SEPARATE gross debit and credit balances. This is NOT
        total AP across all accounts or an aging report. Machine-validated evidence is
        never represented as a human-signed 1C report. OData vs COM is selected server-side.
        """
        tool = "accounting_balance_by_analytics"
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal, tool=tool, source_id=source_id, outcome="denied",
                started_at=started, company_id=None, detail_code="INVALID_COMPANY_ID",
            )
            raise ValueError("company_id must be a UUID") from exc
        query = {
            "company_id": str(parsed_company_id),
            "concept": ANALYTICS_BALANCE_CONCEPT,
            "as_of": as_of,
        }
        source = await resolve_source(
            principal, source_id, tool, started, query, company_id=parsed_company_id
        )
        capabilities = None
        decision = None
        try:
            company = await runtime.registry.require_company(
                principal, source_id, parsed_company_id
            )
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            profile = await runtime.registry.require_semantic_mapping(
                source_id, parsed_company_id, ANALYTICS_BALANCE_CONCEPT
            )
            mapping = profile["mapping"]
            register_set, method, arguments = build_analytics_balance_arguments(
                mapping, company_external_ref=company.external_ref, as_of=as_of
            )
            decision = select_route(
                capabilities,
                mapping,
                getattr(runtime, "com_bindings", None) or (),
                source=source,
                company_external_ref=company.external_ref,
            )
            if decision.route == "odata":
                result = await runtime.onec.register_read(
                    source,
                    register_set=register_set,
                    method=method,
                    arguments=arguments,
                    top=settings.max_rows,
                )
                page = result.get("page") if isinstance(result, dict) else None
                raw_rows = result.get("value") if isinstance(result, dict) else None
                if (
                    not isinstance(page, dict)
                    or type(page.get("has_more")) is not bool
                    or not isinstance(raw_rows, list)
                    or len(raw_rows) > settings.max_rows
                ):
                    raise AnalyticsBalanceError("SOURCE_PAGE_INVALID")
                # a full page is never presented as complete, whatever the source flag says
                truncated = page["has_more"] or len(raw_rows) >= settings.max_rows
                rows = normalize_odata_balance_rows(
                    raw_rows, mapping, company_external_ref=company.external_ref
                )
                adapter_kind = capabilities.adapter_profile.value
            else:
                binding = decision.binding
                client_factory = getattr(runtime, "com_client", None)
                client = await client_factory() if client_factory else None
                if client is None:
                    raise ComRouteUnsupported("com_bridge_not_configured")
                max_rows = min(settings.max_rows, COM_MAX_ROWS)
                response = await client.balance_by_analytics(
                    ComBalanceRequest(
                        binding_id=binding.binding_id,
                        binding_version=binding.version,
                        source_id=source.id,
                        as_of=datetime.fromisoformat(arguments["Period"]),
                        company_external_ref=str(uuid.UUID(company.external_ref)),
                        account_keys=tuple(
                            str(uuid.UUID(item["account_key"])) for item in mapping["accounts"]
                        ),
                        max_rows=max_rows,
                    )
                )
                if (
                    response.binding_id != binding.binding_id
                    or response.binding_version != binding.version
                    or response.source_id != binding.source_id
                    or response.metadata_fingerprint != binding.metadata_fingerprint
                    or response.clone_identity != binding.clone_identity
                    or type(response.truncated) is not bool
                    or len(response.rows) > max_rows
                ):
                    raise AnalyticsBalanceError("COM_PROVENANCE_MISMATCH")
                truncated = response.truncated or len(response.rows) >= max_rows
                rows = normalize_com_balance_rows(
                    list(response.rows), mapping, company_external_ref=company.external_ref
                )
                adapter_kind = "COM_BRIDGE"
            provenance = profile_provenance(profile)  # may raise: build it before the success audit
            supplier_summary = None
            # A safe presentation of the EXISTING validated 521.1 analytics profile.
            # This does not authorize a missing payable.balance / payable.open_items profile.
            mapped_accounts = mapping.get("accounts", [])
            is_exact_5211_profile = (
                isinstance(mapped_accounts, list) and len(mapped_accounts) == 1
                and isinstance(mapped_accounts[0], dict)
                and mapped_accounts[0].get("code") == "521.1"
            )
            if (is_exact_5211_profile
                    and (not rows or all(
                        isinstance(r, dict) and r.get("account") == "521.1" for r in rows
                    ))):
                names: dict[str, str] = {}
                name_lookup_status = "NO_SUPPLIERS" if not rows else "NOT_RUN"
                if rows and not truncated and len(rows) < settings.max_rows:
                    try:
                        refs = supplier_refs(rows)
                        if not source.entity_allowed("Catalog_Контрагенты"):
                            name_lookup_status = "DENIED_BY_SOURCE_POLICY"
                        elif refs:
                            # Every subquery inherits the independently enforced raw catalog
                            # ACL, rate limiter and durable pre-dispatch/completion audit.
                            incomplete = False
                            for batch_refs, predicate in supplier_filter_batches(
                                refs, max_filter_chars=settings.max_filter_chars
                            ):
                                top = min(len(batch_refs) + 1, settings.max_rows)
                                cat = await onec_read(
                                    source_id=source_id, entity_set="Catalog_Контрагенты",
                                    select=["Ref_Key", "Description"],
                                    filter_expr=predicate, orderby=None, expand=None,
                                    top=top, skip=0,
                                )
                                cp = cat.get("page") if isinstance(cat, dict) else None
                                cv = cat.get("value") if isinstance(cat, dict) else cat
                                if not isinstance(cv, list) or len(cv) > top:
                                    raise AnalyticsBalanceError("SUPPLIER_CATALOG_RESPONSE_INVALID")
                                if isinstance(cp, dict):
                                    page_complete = (
                                        cp.get("has_more") is False
                                        and cp.get("truncated") is False
                                    )
                                else:
                                    # Direct OData/Atom has no page envelope. The exact GUID
                                    # query requests one extra row to detect truncation.
                                    page_complete = cp is None and len(cv) < top
                                if not page_complete:
                                    incomplete = True
                                    break
                                allowed_refs = set(batch_refs)
                                for item in cv:
                                    if (not isinstance(item, dict)
                                            or not isinstance(item.get("Ref_Key"), str)
                                            or not isinstance(item.get("Description"), str)):
                                        raise AnalyticsBalanceError("SUPPLIER_CATALOG_RESPONSE_INVALID")
                                    try:
                                        canonical_ref = str(uuid.UUID(item["Ref_Key"]))
                                    except ValueError as exc:
                                        raise AnalyticsBalanceError(
                                            "SUPPLIER_CATALOG_RESPONSE_INVALID"
                                        ) from exc
                                    name = item["Description"]
                                    if (canonical_ref not in allowed_refs
                                            or len(name.encode("utf-8")) > 4096
                                            or (canonical_ref in names
                                                and names[canonical_ref] != name)):
                                        raise AnalyticsBalanceError(
                                            "SUPPLIER_CATALOG_RESPONSE_INVALID"
                                        )
                                    names[canonical_ref] = name
                            name_lookup_status = (
                                "INCOMPLETE" if incomplete else
                                "COMPLETE" if len(names) == len(refs) else "PARTIAL"
                            )
                    except AuditUnavailable:
                        # Never turn a failed durable audit into an apparently successful read.
                        raise
                    except PermissionError:
                        # A mid-batch policy revocation cannot disclose names from earlier batches.
                        names.clear()
                        name_lookup_status = "DENIED_BY_POLICY"
                    # Other failures (including mandatory audit append or metadata drift)
                    # must fail closed, never become a misleading successful report.
                try:
                    supplier_summary = summarize_supplier_5211(
                        rows, names=names, truncated=truncated, max_rows=settings.max_rows
                    )
                except (ValueError, TypeError):
                    supplier_summary = {
                        "account": "521.1", "status": "UNAVAILABLE",
                        "reason": "SOURCE_DATA_INVALID",
                    }
                supplier_summary["name_lookup_status"] = name_lookup_status
            response_payload = {
                "source_id": source_id,
                "company_id": str(parsed_company_id),
                "concept": ANALYTICS_BALANCE_CONCEPT,
                "as_of": arguments["Period"],
                "rows": rows,
                "row_count": len(rows),
                "supplier_summary": supplier_summary,
                "truncated": truncated,
                "route": decision.route,
                "route_reason": decision.reason,
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                **provenance,
            }
            response_bytes = len(json.dumps(
                response_payload, ensure_ascii=False,
            ).encode("utf-8"))
            if response_bytes > settings.max_response_bytes:
                raise AnalyticsBalanceError("RESPONSE_TOO_LARGE")
            detail = f"route={decision.route};reason={decision.reason}"
            if decision.binding is not None:
                detail += f";binding={decision.binding.binding_id}@{decision.binding.version}"
            if profile.get("audit_detail_code"):
                detail += f";profile={profile['audit_detail_code']}"
            await runtime.audit.write(
                principal=principal,
                tool=tool,
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=len(rows),
                company_id=parsed_company_id,
                adapter_kind=adapter_kind,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                detail_code=detail,
                response_bytes=response_bytes,
                truncated=truncated,
            )
            return response_payload
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            detail = str(code)
            if getattr(exc, "reason", None) and isinstance(exc, ComRouteUnsupported):
                detail += f";reason={exc.reason}"
            if decision is not None:
                detail += f";route={decision.route}"
                if decision.binding is not None:
                    detail += f";binding={decision.binding.binding_id}@{decision.binding.version}"
            await runtime.audit.write(
                principal=principal,
                tool=tool,
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
                            AnalyticsBalanceDenied,
                        ),
                    )
                    else "error"
                ),
                started_at=started,
                query=query,
                company_id=parsed_company_id,
                adapter_kind=(capabilities.adapter_profile.value if capabilities else None),
                metadata_fingerprint=(capabilities.metadata_fingerprint if capabilities else None),
                detail_code=detail,
            )
            raise

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
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
                detail_code=profile.get("audit_detail_code"),
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
                **profile_provenance(profile),
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def inventory_movements(
        source_id: str,
        company_id: str,
        start_period: str,
        end_period: str,
        top: int = 100,
        skip: int = 0,
    ) -> dict[str, Any]:
        """Read company-scoped inventory register records; quantity sign follows mapped record type."""
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal,
                tool="inventory_movements",
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
            "concept": INVENTORY_MOVEMENTS_CONCEPT,
            "start_period": start_period,
            "end_period": end_period,
            "top": bounded_top,
            "skip": skip,
        }
        source = await resolve_source(
            principal,
            source_id,
            "inventory_movements",
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
                source_id, parsed_company_id, INVENTORY_MOVEMENTS_CONCEPT
            )
            mapping = profile["mapping"]
            entity_set, select, filter_expr = build_inventory_movement_query(
                mapping,
                company_external_ref=company.external_ref,
                start_period=start_period,
                end_period=end_period,
            )
            metadata = await runtime.onec.metadata(source)
            if entity_set not in metadata.names:
                await deny_unconfirmed_semantic_capability(
                    source_id=source_id,
                    metadata_fingerprint=capabilities.metadata_fingerprint,
                    concept=INVENTORY_MOVEMENTS_CONCEPT,
                    entity_set=entity_set,
                    reason="ENTITY_SET_ABSENT",
                    expected_properties=sorted(
                        set(select) | {mapping["company_scope"]["field"]}
                    ),
                    message="configured inventory movement EntitySet is absent from live metadata",
                )
            live_fields = _metadata_entity_fields(metadata, entity_set)
            required_fields = set(select) | {mapping["company_scope"]["field"]}
            missing_fields = sorted(required_fields - live_fields)
            if missing_fields:
                await deny_unconfirmed_semantic_capability(
                    source_id=source_id,
                    metadata_fingerprint=capabilities.metadata_fingerprint,
                    concept=INVENTORY_MOVEMENTS_CONCEPT,
                    entity_set=entity_set,
                    reason="PROPERTY_ABSENT" if live_fields else "PROPERTIES_UNCONFIRMED",
                    expected_properties=sorted(required_fields),
                    missing_properties=missing_fields,
                    message="configured inventory movement fields are absent from live metadata",
                )
            result = await runtime.onec.read(
                source,
                entity_set=entity_set,
                select=select,
                filter_expr=filter_expr,
                orderby=f"{mapping['order_by']} asc",
                expand=None,
                top=bounded_top,
                skip=skip,
            )
            raw_rows = result.get("value", []) if isinstance(result, dict) else result
            normalized_rows = normalize_inventory_movement_rows(raw_rows, mapping)
            response_bytes = len(
                json.dumps(normalized_rows, ensure_ascii=False, default=str).encode("utf-8")
            )
            await runtime.audit.write(
                principal=principal,
                tool="inventory_movements",
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=len(normalized_rows),
                company_id=parsed_company_id,
                adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                detail_code=profile.get("audit_detail_code"),
                response_bytes=response_bytes,
            )
            return {
                "source_id": source_id,
                "company_id": str(parsed_company_id),
                "concept": INVENTORY_MOVEMENTS_CONCEPT,
                "period": {"from": start_period, "to_exclusive": end_period},
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                "value": normalized_rows,
                "page": result.get("page") if isinstance(result, dict) else None,
                **profile_provenance(profile),
            }
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="inventory_movements",
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def accounting_posting_rows(
        source_id: str,
        company_id: str,
        start_period: str,
        end_period: str,
        top: int = 100,
        skip: int = 0,
    ) -> dict[str, Any]:
        """Read profile-mapped accounting register rows; this is not a reconciliation report."""
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal,
                tool="accounting_posting_rows",
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
            "concept": ACCOUNTING_POSTING_ROWS_CONCEPT,
            "start_period": start_period,
            "end_period": end_period,
            "top": bounded_top,
            "skip": skip,
        }
        source = await resolve_source(
            principal,
            source_id,
            "accounting_posting_rows",
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
                source_id, parsed_company_id, ACCOUNTING_POSTING_ROWS_CONCEPT
            )
            mapping = profile["mapping"]
            entity_set, select, filter_expr = build_accounting_posting_rows_query(
                mapping,
                company_external_ref=company.external_ref,
                start_period=start_period,
                end_period=end_period,
            )
            metadata = await runtime.onec.metadata(source)
            if entity_set not in metadata.names:
                await deny_unconfirmed_semantic_capability(
                    source_id=source_id,
                    metadata_fingerprint=capabilities.metadata_fingerprint,
                    concept=ACCOUNTING_POSTING_ROWS_CONCEPT,
                    entity_set=entity_set,
                    reason="ENTITY_SET_ABSENT",
                    expected_properties=sorted(
                        set(select) | {mapping["company_scope"]["field"]}
                    ),
                    message="configured accounting register EntitySet is absent from live metadata",
                )
            live_fields = _metadata_entity_fields(metadata, entity_set)
            required_fields = set(select) | {mapping["company_scope"]["field"]}
            missing_fields = sorted(required_fields - live_fields)
            if missing_fields:
                await deny_unconfirmed_semantic_capability(
                    source_id=source_id,
                    metadata_fingerprint=capabilities.metadata_fingerprint,
                    concept=ACCOUNTING_POSTING_ROWS_CONCEPT,
                    entity_set=entity_set,
                    reason="PROPERTY_ABSENT" if live_fields else "PROPERTIES_UNCONFIRMED",
                    expected_properties=sorted(required_fields),
                    missing_properties=missing_fields,
                    message="configured accounting posting fields are absent from live metadata",
                )
            result = await runtime.onec.read(
                source,
                entity_set=entity_set,
                select=select,
                filter_expr=filter_expr,
                orderby=(
                    f"{mapping['output_fields']['period']} asc,"
                    f"{mapping['output_fields']['recorder_ref']} asc,"
                    f"{mapping['output_fields']['line_number']} asc"
                ),
                expand=None,
                top=bounded_top,
                skip=skip,
            )
            raw_rows = result.get("value", []) if isinstance(result, dict) else result
            value = normalize_accounting_posting_rows(raw_rows, mapping)
            await runtime.audit.write(
                principal=principal,
                tool="accounting_posting_rows",
                source_id=source_id,
                outcome="success",
                started_at=started,
                query=query,
                returned_items=len(value),
                company_id=parsed_company_id,
                adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                detail_code=profile.get("audit_detail_code"),
            )
            return {
                "source_id": source_id,
                "company_id": str(parsed_company_id),
                "concept": ACCOUNTING_POSTING_ROWS_CONCEPT,
                "period": {"from": start_period, "to_exclusive": end_period},
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                "value": value,
                "page": result.get("page") if isinstance(result, dict) else None,
                **profile_provenance(
                    profile, ["Rows are not a native accounting report reconciliation."]
                ),
            }
        except Exception as exc:
            await runtime.audit.write(
                principal=principal,
                tool="accounting_posting_rows",
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def cash_movements(
        source_id: str,
        company_id: str,
        start_period: str,
        end_period: str,
        top: int = 100,
        skip: int = 0,
    ) -> dict[str, Any]:
        """Read profile-confirmed company cash movements; signs follow mapped record types."""
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal, tool="cash_movements", source_id=source_id,
                outcome="denied", started_at=started, detail_code="INVALID_COMPANY_ID",
            )
            raise ValueError("company_id must be a UUID") from exc
        if top < 1 or skip < 0:
            raise ValueError("top must be positive and skip cannot be negative")
        bounded_top = min(top, settings.max_rows)
        query = {
            "company_id": str(parsed_company_id), "concept": CASH_MOVEMENTS_CONCEPT,
            "start_period": start_period, "end_period": end_period,
            "top": bounded_top, "skip": skip,
        }
        source = await resolve_source(
            principal, source_id, "cash_movements", started, query,
            company_id=parsed_company_id,
        )
        capabilities = None
        try:
            company = await runtime.registry.require_company(principal, source_id, parsed_company_id)
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            profile = await runtime.registry.require_semantic_mapping(
                source_id, parsed_company_id, CASH_MOVEMENTS_CONCEPT
            )
            mapping = profile["mapping"]
            entity_set, select, filter_expr = build_cash_movements_query(
                mapping, company_external_ref=company.external_ref,
                start_period=start_period, end_period=end_period,
            )
            metadata = await runtime.onec.metadata(source)
            live_fields = _metadata_entity_fields(metadata, entity_set)
            if entity_set not in metadata.names:
                await deny_unconfirmed_semantic_capability(
                    source_id=source_id,
                    metadata_fingerprint=capabilities.metadata_fingerprint,
                    concept=CASH_MOVEMENTS_CONCEPT,
                    entity_set=entity_set,
                    reason="ENTITY_SET_ABSENT",
                    expected_properties=sorted(
                        set(select) | {mapping["company_scope"]["field"]}
                    ),
                    message="configured cash movement EntitySet is absent from live metadata",
                )
            required_fields = set(select) | {mapping["company_scope"]["field"]}
            missing_fields = sorted(required_fields - live_fields)
            if missing_fields:
                await deny_unconfirmed_semantic_capability(
                    source_id=source_id,
                    metadata_fingerprint=capabilities.metadata_fingerprint,
                    concept=CASH_MOVEMENTS_CONCEPT,
                    entity_set=entity_set,
                    reason="PROPERTY_ABSENT" if live_fields else "PROPERTIES_UNCONFIRMED",
                    expected_properties=sorted(required_fields),
                    missing_properties=missing_fields,
                    message="configured cash movement fields are absent from live metadata",
                )
            fields = mapping["output_fields"]
            result = await runtime.onec.read(
                source, entity_set=entity_set, select=select, filter_expr=filter_expr,
                orderby=(
                    f"{fields['period']} asc,{fields['recorder_ref']} asc,"
                    f"{fields['line_number']} asc"
                ),
                expand=None, top=bounded_top, skip=skip,
            )
            raw_rows = result.get("value", []) if isinstance(result, dict) else result
            value = normalize_cash_movement_rows(raw_rows, mapping)
            await runtime.audit.write(
                principal=principal, tool="cash_movements", source_id=source_id,
                outcome="success", started_at=started, query=query, returned_items=len(value),
                company_id=parsed_company_id, adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                detail_code=profile.get("audit_detail_code"),
            )
            return {
                "source_id": source_id, "company_id": str(parsed_company_id),
                "concept": CASH_MOVEMENTS_CONCEPT,
                "period": {"from": start_period, "to_exclusive": end_period},
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                "value": value, "page": result.get("page") if isinstance(result, dict) else None,
                **profile_provenance(profile),
            }
        except Exception as exc:
            await runtime.audit.write(
                principal=principal, tool="cash_movements", source_id=source_id,
                outcome=("denied" if isinstance(exc, (
                    PermissionError, CapabilityUnsupported, MetadataDriftUnacknowledged,
                    SemanticProfileUnavailable,
                )) else "error"),
                started_at=started, query=query, company_id=parsed_company_id,
                adapter_kind=(capabilities.adapter_profile.value if capabilities else None),
                metadata_fingerprint=(capabilities.metadata_fingerprint if capabilities else None),
                detail_code=getattr(exc, "code", type(exc).__name__),
            )
            raise

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
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
                detail_code=profile.get("audit_detail_code"),
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
                **profile_provenance(profile),
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
                detail_code=profile.get("audit_detail_code"),
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
                **profile_provenance(profile),
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def receivable_balance(source_id: str, company_id: str, period: str) -> dict[str, Any]:
        """Read point-in-time receivable balances; this tool does not compute aging buckets."""
        return await read_settlement_balance(
            source_id,
            company_id,
            period,
            concept=RECEIVABLE_BALANCE_CONCEPT,
            tool_name="receivable_balance",
        )

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def payable_balance(source_id: str, company_id: str, period: str) -> dict[str, Any]:
        """Read payables ONLY with separately validated payable.balance semantics.

        If no exact mapping is validated, fail closed; do not silently substitute 521.1
        for all supplier liabilities. For an account-521.1-only snapshot, use
        accounting_balance_by_analytics with an offset-aware as_of timestamp.
        """
        return await read_settlement_balance(
            source_id,
            company_id,
            period,
            concept=PAYABLE_BALANCE_CONCEPT,
            tool_name="payable_balance",
        )

    async def read_open_items_aging(
        source_id: str, company_id: str, as_of: str, *, concept: str, tool_name: str, top: int
    ) -> dict[str, Any]:
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal, tool=tool_name, source_id=source_id, outcome="denied",
                started_at=started, detail_code="INVALID_COMPANY_ID",
            )
            raise ValueError("company_id must be a UUID") from exc
        if top < 1:
            raise ValueError("top must be positive")
        as_of_date = parse_as_of(as_of)
        row_limit = min(top, settings.max_rows, MAX_OPEN_ITEM_ROWS)
        query = {
            "company_id": str(parsed_company_id), "concept": concept,
            "as_of": as_of_date.isoformat(), "top": row_limit,
        }
        source = await resolve_source(
            principal, source_id, tool_name, started, query, company_id=parsed_company_id
        )
        capabilities = None
        profile = None
        try:
            company = await runtime.registry.require_company(principal, source_id, parsed_company_id)
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            profile = await runtime.registry.require_semantic_mapping(
                source_id, parsed_company_id, concept
            )
            mapping = profile["mapping"]
            entity_set, select, filter_expr, orderby = build_open_items_query(
                concept, mapping, company_external_ref=company.external_ref
            )
            metadata = await runtime.onec.metadata(source)
            live_fields = _metadata_entity_fields(metadata, entity_set)
            if entity_set not in metadata.names or set(select) - live_fields:
                await deny_unconfirmed_semantic_capability(
                    source_id=source_id,
                    metadata_fingerprint=capabilities.metadata_fingerprint,
                    concept=concept,
                    entity_set=entity_set,
                    reason="ENTITY_SET_ABSENT" if entity_set not in metadata.names
                    else "PROPERTY_ABSENT",
                    expected_properties=sorted(select),
                    missing_properties=sorted(set(select) - live_fields),
                    message="configured open-item record set is absent from live metadata",
                )
            result = await runtime.onec.read(
                source, entity_set=entity_set, select=select, filter_expr=filter_expr,
                orderby=orderby, expand=None, top=row_limit, skip=0,
            )
            raw_rows = result.get("value") if isinstance(result, dict) else result
            page = result.get("page") if isinstance(result, dict) else None
            source_truncated = isinstance(page, dict) and page.get("truncated", False) is not False
            payload = evaluate_open_items(
                concept, mapping, raw_rows, source_id=source_id,
                company_id=str(parsed_company_id), company_external_ref=company.external_ref,
                as_of=as_of_date, row_limit=row_limit,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                synthetic=profile.get("profile_kind") == SYNTHETIC_PROFILE_KIND,
                source_truncated=source_truncated,
            )
            conclusive = payload["status"] in {"PASS", "FINDING"}
            marker = profile.get("audit_detail_code")
            # Source-data integrity failures are never audited as success; the synthetic
            # marker stays visible as "<marker>:<reason>" (the reason is a fixed code).
            detail_code = marker if conclusive else (
                f"{marker}:{payload['reason']}" if marker else payload["reason"]
            )
            response_bytes = len(
                json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            )
            await runtime.audit.write(
                principal=principal, tool=tool_name, source_id=source_id,
                outcome=(
                    "error" if payload["reason"] in OPEN_ITEMS_FAILURE_REASONS else "success"
                ),
                started_at=started, query=query, returned_items=len(payload["rows"]),
                company_id=parsed_company_id, adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                detail_code=detail_code,
                response_bytes=response_bytes, truncated=bool(payload["truncated"]),
            )
            return {
                "source_id": source_id, "company_id": str(parsed_company_id),
                "concept": concept, "as_of": as_of_date.isoformat(),
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                **payload,
                **profile_provenance(profile),
            }
        except Exception as exc:
            await runtime.audit.write(
                principal=principal, tool=tool_name, source_id=source_id,
                outcome=("denied" if isinstance(exc, (
                    PermissionError, CapabilityUnsupported, MetadataDriftUnacknowledged,
                    SemanticProfileUnavailable,
                )) else "error"),
                started_at=started, query=query, company_id=parsed_company_id,
                adapter_kind=(capabilities.adapter_profile.value if capabilities else None),
                metadata_fingerprint=(capabilities.metadata_fingerprint if capabilities else None),
                profile_fingerprint=(profile["profile_fingerprint"] if profile else None),
                detail_code=(
                    f"{profile['audit_detail_code']}:" if profile and profile.get("audit_detail_code")
                    else ""
                ) + getattr(exc, "code", type(exc).__name__),
            )
            raise

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def receivable_aging(
        source_id: str, company_id: str, as_of: str, top: int = 2000
    ) -> dict[str, Any]:
        """Aging of open receivable items from a confirmed settlement record set (read-only)."""
        return await read_open_items_aging(
            source_id, company_id, as_of, concept=RECEIVABLE_OPEN_ITEMS_CONCEPT,
            tool_name="receivable_aging", top=top,
        )

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def payable_aging(
        source_id: str, company_id: str, as_of: str, top: int = 2000
    ) -> dict[str, Any]:
        """Aging ONLY with independently validated payable.open_items records.

        Confirm due dates, document/payment allocations and complete opening items.
        Account 521.1 balances cannot by themselves prove overdue days or aging.
        """
        return await read_open_items_aging(
            source_id, company_id, as_of, concept=PAYABLE_OPEN_ITEMS_CONCEPT,
            tool_name="payable_aging", top=top,
        )

    async def read_duplicate_candidates(
        source_id: str, company_id: str, *, tool_name: str, top: int
    ) -> dict[str, Any]:
        concept = DUPLICATE_CONCEPT
        started = time.monotonic()
        principal = await ctx()
        try:
            parsed_company_id = uuid.UUID(company_id)
        except ValueError as exc:
            await runtime.audit.write(
                principal=principal, tool=tool_name, source_id=source_id, outcome="denied",
                started_at=started, detail_code="INVALID_COMPANY_ID",
            )
            raise ValueError("company_id must be a UUID") from exc
        if top < 1:
            raise ValueError("top must be positive")
        row_limit = min(top, settings.max_rows, MAX_DUPLICATE_ROWS)
        # The audit query never carries counterparty names or codes (contract section 10).
        query = {"company_id": str(parsed_company_id), "concept": concept, "top": row_limit}
        source = await resolve_source(
            principal, source_id, tool_name, started, query, company_id=parsed_company_id
        )
        capabilities = None
        profile = None
        try:
            company = await runtime.registry.require_company(principal, source_id, parsed_company_id)
            capabilities = await runtime.onec.capabilities(source)
            drift = await runtime.registry.save_capabilities(capabilities)
            require_acknowledged_metadata(drift)
            profile = await runtime.registry.require_semantic_mapping(
                source_id, parsed_company_id, concept
            )
            mapping = profile["mapping"]
            # The 1C register carries the company's external reference, not the gateway UUID.
            activity_query = build_activity_query(mapping, company.external_ref, row_limit)
            catalog_query = build_catalog_query(mapping, row_limit)
            metadata = await runtime.onec.metadata(source)
            for planned in (activity_query, catalog_query):
                entity_set = planned["entity_set"]
                select = planned["select"]
                live_fields = _metadata_entity_fields(metadata, entity_set)
                if entity_set not in metadata.names or set(select) - live_fields:
                    await deny_unconfirmed_semantic_capability(
                        source_id=source_id,
                        metadata_fingerprint=capabilities.metadata_fingerprint,
                        concept=concept,
                        entity_set=entity_set,
                        reason="ENTITY_SET_ABSENT" if entity_set not in metadata.names
                        else "PROPERTY_ABSENT",
                        expected_properties=sorted(select),
                        missing_properties=sorted(set(select) - live_fields),
                        message="configured duplicate-counterparty entity is absent from live metadata",
                    )
            # Source entity policy for BOTH planned reads is checked before the first upstream read.
            if not all(source.entity_allowed(p["entity_set"]) for p in (activity_query, catalog_query)):
                raise PermissionError("EntitySet denied by source policy")

            def _flags(result: Any) -> tuple[Any, bool]:
                rows = result.get("value") if isinstance(result, dict) else result
                page = result.get("page") if isinstance(result, dict) else None
                return rows, isinstance(page, dict) and page.get("truncated", False) is not False

            result = await runtime.onec.read(
                source, entity_set=activity_query["entity_set"], select=activity_query["select"],
                filter_expr=activity_query["filter_expr"], orderby=activity_query["orderby"],
                expand=None, top=row_limit, skip=0,
            )
            activity_rows, activity_truncated = _flags(result)
            catalog_rows, catalog_truncated = None, False
            # A truncated or malformed activity read stops the scan before the catalog read.
            if isinstance(activity_rows, list) and not rows_truncated(
                activity_rows, row_limit, activity_truncated
            ):
                result = await runtime.onec.read(
                    source, entity_set=catalog_query["entity_set"], select=catalog_query["select"],
                    filter_expr=None, orderby=catalog_query["orderby"],
                    expand=None, top=row_limit, skip=0,
                )
                catalog_rows, catalog_truncated = _flags(result)
            payload = evaluate_duplicate_candidates(
                mapping, company_id=company.external_ref, row_limit=row_limit,
                activity_rows=activity_rows, activity_truncated=activity_truncated,
                catalog_rows=catalog_rows, catalog_truncated=catalog_truncated,
            )
            conclusive = payload["status"] in {"PASS", "FINDING"}
            marker = profile.get("audit_detail_code")
            detail_code = marker if conclusive else (
                f"{marker}:{payload['reason']}" if marker else payload["reason"]
            )
            response = {
                "source_id": source_id, "company_id": str(parsed_company_id),
                "concept": concept,
                "profile_fingerprint": profile["profile_fingerprint"],
                "metadata_fingerprint": capabilities.metadata_fingerprint,
                **payload,
                **profile_provenance(profile),
            }
            response_bytes = len(
                json.dumps(response, ensure_ascii=False, default=str).encode("utf-8")
            )
            if response_bytes > settings.max_response_bytes:
                raise DuplicateResponseTooLarge()
            await runtime.audit.write(
                principal=principal, tool=tool_name, source_id=source_id,
                outcome=("error" if payload["reason"] in DUPLICATE_FAILURE_REASONS else "success"),
                started_at=started, query=query, returned_items=payload["group_count"],
                company_id=parsed_company_id, adapter_kind=capabilities.adapter_profile.value,
                metadata_fingerprint=capabilities.metadata_fingerprint,
                profile_fingerprint=profile["profile_fingerprint"],
                detail_code=detail_code,
                response_bytes=response_bytes, truncated=bool(payload["truncated"]),
            )
            return response
        except Exception as exc:
            await runtime.audit.write(
                principal=principal, tool=tool_name, source_id=source_id,
                outcome=("denied" if isinstance(exc, (
                    PermissionError, CapabilityUnsupported, MetadataDriftUnacknowledged,
                    SemanticProfileUnavailable,
                )) else "error"),
                started_at=started, query=query, company_id=parsed_company_id,
                adapter_kind=(capabilities.adapter_profile.value if capabilities else None),
                metadata_fingerprint=(capabilities.metadata_fingerprint if capabilities else None),
                profile_fingerprint=(profile["profile_fingerprint"] if profile else None),
                detail_code=(
                    f"{profile['audit_detail_code']}:" if profile and profile.get("audit_detail_code")
                    else ""
                ) + getattr(exc, "code", type(exc).__name__),
            )
            raise

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
    async def counterparty_duplicate_candidates(
        source_id: str, company_id: str, top: int = 2000
    ) -> dict[str, Any]:
        """List potential duplicate counterparties by normalized name for one company.

        Read-only: returns candidate groups for human review and never merges or changes anything.
        """
        return await read_duplicate_candidates(
            source_id, company_id, tool_name="counterparty_duplicate_candidates", top=top
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
                detail_code=profile.get("audit_detail_code"),
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
                **profile_provenance(profile),
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
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

    @mcp.tool(annotations=CHATGPT_READ_ONLY_ANNOTATIONS)
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
        source = await resolve_source(principal, source_id, "onec_read", started, query)
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
                detail_code=("METADATA_DRIFTED" if drift["drift_status"] == "DRIFTED" else None),
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

    # ADR-0008 §5: the caller cannot pass route/bridge/path/secret/query text. Unknown arguments
    # are rejected (not silently dropped) and the published schema says additionalProperties=false.
    analytics_tool = mcp._tool_manager.get_tool("accounting_balance_by_analytics")
    if analytics_tool is None:
        raise RuntimeError("accounting_balance_by_analytics tool is not registered")
    analytics_model = analytics_tool.fn_metadata.arg_model
    analytics_model.model_config["extra"] = "forbid"
    analytics_model.model_rebuild(force=True)
    analytics_tool.parameters["additionalProperties"] = False

    return mcp
