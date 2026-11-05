"""Application composition for authorized, read-only 1C metadata observations.

This boundary reuses the application's registered source, credentials and read-only OData
transport. Tenant/source entitlement and metadata-specific permission are required injected
authorities: this module does not infer a tenant from a subject, source ID, project label or
request field. Missing or ambiguous scope fails closed before metadata fetch.

The discovery path remains asynchronous and separate from the synchronous CaptureLoop connector.
An observed digest is evidence only; ``classify_observation`` can report a gap or drift candidate,
but never promotes a new accepted baseline.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
import math
from typing import Protocol
from urllib.parse import urlparse

from ..adapters.onec.adapter import OneCAdapter
from ..models import Source
from ..principal import Principal
from .backend_budget import BackendId, PhysicalBackendBudget
from .drift import CaptureOutcome, CaptureOutcomeKind, DriftDecision, classify
from .onec_discovery import (
    MetadataCompleteness,
    OneCFetchError,
    OneCMetadataDiscovery,
    ObservedMetadata,
)
from .ports import Scope


class RegisteredSourceAccess(Protocol):
    async def require_source(self, principal: Principal, source_id: str) -> Source: ...


class TenantScopeResolver(Protocol):
    async def resolve_scope(self, principal: Principal, source: Source) -> Scope:
        """Prove the principal's authoritative tenant-to-source entitlement or deny."""


class MetadataAuthorizer(Protocol):
    async def allow_source_metadata(
        self, principal: Principal, source: Source, *, tenant_id: str,
    ) -> bool: ...


class EntityMetadataAuthorizer(Protocol):
    def allow_entity(
        self, principal: Principal, source: Source, qualified_name: str, *, tenant_id: str,
    ) -> bool: ...


AuditMetadata = Callable[[str, Mapping[str, str]], Awaitable[None]]


class RegisteredOneCMetadataComposition:
    """Bind Phase 2 discovery to the authenticated application's registered-source boundary.

    ``scope_resolver`` and both metadata authorizers must come from trusted application policy.
    The constructor intentionally has no fallback tenant mapping or permissive default.
    """

    def __init__(
        self,
        *,
        registry: RegisteredSourceAccess,
        onec: OneCAdapter,
        scope_resolver: TenantScopeResolver,
        metadata_authorizer: MetadataAuthorizer,
        entity_authorizer: EntityMetadataAuthorizer,
        audit: AuditMetadata,
        backend_budget: PhysicalBackendBudget,
        max_metadata_bytes: int = 20_000_000,
        scope_resolution_timeout_seconds: float = 10.0,
    ) -> None:
        if not all(callable(getattr(registry, name, None)) for name in ("require_source",)):
            raise TypeError("REGISTERED_SOURCE_ACCESS_REQUIRED")
        if not callable(getattr(scope_resolver, "resolve_scope", None)):
            raise TypeError("TENANT_SCOPE_RESOLVER_REQUIRED")
        if not callable(getattr(metadata_authorizer, "allow_source_metadata", None)):
            raise TypeError("METADATA_AUTHORIZER_REQUIRED")
        if not callable(getattr(entity_authorizer, "allow_entity", None)):
            raise TypeError("ENTITY_METADATA_AUTHORIZER_REQUIRED")
        if not callable(audit):
            raise TypeError("METADATA_AUDIT_REQUIRED")
        if not isinstance(backend_budget, PhysicalBackendBudget):
            raise TypeError("BACKEND_BUDGET_REQUIRED")
        if (type(scope_resolution_timeout_seconds) not in (int, float)
                or not math.isfinite(scope_resolution_timeout_seconds)
                or scope_resolution_timeout_seconds <= 0):
            raise ValueError("SCOPE_RESOLUTION_TIMEOUT_INVALID")
        self._registry = registry
        self._onec = onec
        self._scope_resolver = scope_resolver
        self._metadata_authorizer = metadata_authorizer
        self._entity_authorizer = entity_authorizer
        self._audit = audit
        self._budget = backend_budget
        self._max_metadata_bytes = max_metadata_bytes
        self._scope_resolution_timeout = float(scope_resolution_timeout_seconds)

    async def observe(self, principal: Principal, source_id: str) -> ObservedMetadata:
        """Fetch and fingerprint one authorized registered-source ``$metadata`` document."""
        if (type(principal) is not Principal or type(principal.subject) is not str
                or not principal.subject.strip() or "onec:read" not in principal.scopes):
            raise PermissionError("AUTHENTICATED_PRINCIPAL_REQUIRED")
        try:
            async with asyncio.timeout(self._scope_resolution_timeout):
                source = await self._registry.require_source(principal, source_id)
                self._check_source(source, source_id)
                scope = await self._scope_resolver.resolve_scope(principal, source)
        except TimeoutError as exc:
            raise PermissionError("SOURCE_SCOPE_RESOLUTION_TIMEOUT") from exc
        self._check_source(source, source_id)
        if (type(scope) is not Scope or type(scope.source_id) is not str
                or scope.source_id != source.id
                or not isinstance(scope.tenant_id, str) or not scope.tenant_id.strip()
                or scope.tenant_id != scope.tenant_id.strip()):
            raise PermissionError("TENANT_SOURCE_SCOPE_DENIED")

        parsed = urlparse(source.base_url)
        if not parsed.hostname:
            raise PermissionError("REGISTERED_BACKEND_ID_INVALID")
        backend_id = BackendId.normalize(parsed.hostname)

        async def allow_source_metadata(
            authenticated_subject: str, requested_source_id: str, *, tenant_id: str,
        ) -> bool:
            if (authenticated_subject != principal.subject or requested_source_id != source.id
                    or tenant_id != scope.tenant_id):
                return False
            current = await self._registry.require_source(principal, source.id)
            if current != source:
                return False
            allowed = await self._metadata_authorizer.allow_source_metadata(
                principal, current, tenant_id=tenant_id)
            return allowed is True

        async def fetch_registered_metadata(
            requested_source_id: str, max_bytes: int, *, tenant_id: str,
        ) -> bytes:
            if requested_source_id != source.id or tenant_id != scope.tenant_id:
                raise PermissionError("TENANT_SOURCE_SCOPE_DENIED")
            current = await self._registry.require_source(principal, source.id)
            if current != source:
                raise PermissionError("REGISTERED_SOURCE_CHANGED")
            allowed = await self._metadata_authorizer.allow_source_metadata(
                principal, current, tenant_id=tenant_id)
            if allowed is not True:
                raise PermissionError("SOURCE_METADATA_ACCESS_DENIED")
            username, password = await self._onec.credentials(current)
            # Credential resolution may await an external provider; re-check the grant and
            # registered endpoint immediately before dispatch so revocation/config changes
            # during that await fail closed.
            current = await self._registry.require_source(principal, source.id)
            if current != source:
                raise PermissionError("REGISTERED_SOURCE_CHANGED")
            allowed = await self._metadata_authorizer.allow_source_metadata(
                principal, current, tenant_id=tenant_id)
            if allowed is not True:
                raise PermissionError("SOURCE_METADATA_ACCESS_DENIED")
            raw = await self._onec.client.get_bytes(
                current, "$metadata", username=username, password=password,
                accept="application/xml",
            )
            # The source or grant can change while the network request is in flight. Discard
            # the response rather than assigning its digest to a source no longer authorized.
            current_after_fetch = await self._registry.require_source(principal, source.id)
            if current_after_fetch != source:
                raise OneCFetchError("SOURCE_CHANGED_DURING_FETCH")
            try:
                async with asyncio.timeout(self._scope_resolution_timeout):
                    scope_after_fetch = await self._scope_resolver.resolve_scope(
                        principal, current_after_fetch)
            except TimeoutError as exc:
                raise OneCFetchError("SCOPE_REVALIDATION_TIMEOUT") from exc
            if (type(scope_after_fetch) is not Scope
                    or scope_after_fetch.source_id != source.id
                    or scope_after_fetch.tenant_id != scope.tenant_id):
                raise OneCFetchError("SCOPE_CHANGED_DURING_FETCH")
            allowed_after_fetch = await self._metadata_authorizer.allow_source_metadata(
                principal, current_after_fetch, tenant_id=tenant_id)
            if allowed_after_fetch is not True:
                raise OneCFetchError("METADATA_ACCESS_REVOKED_DURING_FETCH")
            if not isinstance(raw, bytes) or len(raw) > max_bytes:
                raise ValueError("METADATA_RESPONSE_INVALID")
            return raw

        def entity_allowed(
            authenticated_subject: str, requested_source_id: str, qualified_name: str, *,
            tenant_id: str,
        ) -> bool:
            if (authenticated_subject != principal.subject or requested_source_id != source.id
                    or tenant_id != scope.tenant_id):
                return False
            return self._entity_authorizer.allow_entity(
                principal, source, qualified_name, tenant_id=tenant_id) is True

        discovery = OneCMetadataDiscovery(
            allow_source_metadata=allow_source_metadata,
            fetch_registered_metadata=fetch_registered_metadata,
            audit=self._audit,
            entity_allowed=entity_allowed,
            backend_budget=self._budget,
            max_metadata_bytes=self._max_metadata_bytes,
        )
        try:
            return await discovery.observe(
                authenticated_subject=principal.subject,
                source_id=source.id,
                tenant_id=scope.tenant_id,
                backend_id=backend_id,
            )
        except OneCFetchError as exc:
            if exc.code not in {
                "SOURCE_CHANGED_DURING_FETCH",
                "SCOPE_CHANGED_DURING_FETCH",
                "METADATA_ACCESS_REVOKED_DURING_FETCH",
                "SCOPE_REVALIDATION_TIMEOUT",
            }:
                raise
            return ObservedMetadata(
                source_id=source.id,
                fingerprint=None,
                completeness=(
                    {
                        "SOURCE_CHANGED_DURING_FETCH": (
                            MetadataCompleteness.PARTIAL_SOURCE_CHANGED),
                        "SCOPE_CHANGED_DURING_FETCH": (
                            MetadataCompleteness.PARTIAL_SCOPE_CHANGED),
                        "METADATA_ACCESS_REVOKED_DURING_FETCH": (
                            MetadataCompleteness.PARTIAL_ACCESS_REVOKED),
                        "SCOPE_REVALIDATION_TIMEOUT": (
                            MetadataCompleteness.PARTIAL_CONSISTENCY_UNVERIFIED),
                    }[exc.code]
                ),
            )

    @staticmethod
    def _check_source(source: Source, requested_source_id: str) -> None:
        if (type(source) is not Source or source.id != requested_source_id
                or source.project != "onec" or source.kind not in {"onec_odata", "onec_auto"}
                or source.enabled is not True or source.read_only is not True):
            raise PermissionError("REGISTERED_READ_ONLY_ONEC_SOURCE_REQUIRED")


def classify_observation(
    observation: ObservedMetadata, previous_accepted_hash: str | None,
) -> DriftDecision:
    """Surface partial coverage or structural drift without accepting a new baseline."""
    if not isinstance(observation, ObservedMetadata):
        raise TypeError("OBSERVED_METADATA_REQUIRED")
    if observation.completeness is not MetadataCompleteness.COMPLETE:
        return classify(CaptureOutcome(CaptureOutcomeKind.OK_PARTIAL), previous_accepted_hash)
    assert observation.fingerprint is not None
    return classify(
        CaptureOutcome(CaptureOutcomeKind.OK_COMPLETE,
                       observation.fingerprint.structural_sha256),
        previous_accepted_hash,
    )
