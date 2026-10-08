"""Phase 2 connector contracts: registered-source discovery, read only.

No arbitrary caller URL, executable, SQL or secret parameters. Server must
supply an authorized loader bound to its own source registry and policy.
"""
from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from .structural_hash import StructuralFingerprint, fingerprint_edmx

_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class OneCFetchError(RuntimeError):
    """Sanitized fetch failure carrying only a code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ObservedMetadata:
    source_id: str
    fingerprint: StructuralFingerprint
    completeness: str = "COMPLETE"
    trust: str = "OBSERVED_ONLY"
    # Objects removed from fingerprint.objects because entity_allowed did not say True.
    withheld_objects: int = 0


class OneCMetadataDiscovery:
    """Never makes its own network connection or accepts a URL from the user.

    All callbacks except audit receive keyword tenant_id; a grant is per (tenant, source).
    allow_source_metadata: trusted ACL adapter for source-wide metadata (not
    a company-level grant); only a result `is True` grants access.
    fetch_registered_metadata(source_id, max_bytes): existing read-only 1C
    adapter that resolves endpoint and secret refs from server registry.
    audit(event, details): mandatory; awaited BEFORE the adapter is called, and
    any failure to write the audit record denies the request (fail-closed).
    entity_allowed(subject, source_id, qualified_name): objects for which it does
    not return exactly True are removed before the result is returned.
    """

    def __init__(
        self,
        *,
        allow_source_metadata: Callable[..., Awaitable[bool]],
        fetch_registered_metadata: Callable[..., Awaitable[bytes]],
        audit: Callable[[str, Mapping[str, str]], Awaitable[None]],
        entity_allowed: Callable[..., bool],
        max_metadata_bytes: int = 20_000_000,
        callback_timeout_seconds: float = 10.0,
        fetch_timeout_seconds: float = 60.0,
    ):
        if not all(callable(cb) for cb in (
            allow_source_metadata, fetch_registered_metadata, audit, entity_allowed
        )):
            raise TypeError("TRUSTED_CONNECTOR_CALLBACKS_REQUIRED")
        if not 0 < max_metadata_bytes <= 20_000_000:
            raise ValueError("METADATA_BUDGET_INVALID")
        for seconds in (callback_timeout_seconds, fetch_timeout_seconds):
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
                raise ValueError("ONEC_TIMEOUT_INVALID")
        self._allowed = allow_source_metadata
        self._fetch = fetch_registered_metadata
        self._audit = audit
        self._entity_allowed = entity_allowed
        self.max_metadata_bytes = max_metadata_bytes
        self._callback_timeout = float(callback_timeout_seconds)
        self._fetch_timeout = float(fetch_timeout_seconds)

    async def observe(
        self, *, authenticated_subject: str, source_id: str, tenant_id: str
    ) -> ObservedMetadata:
        if (not isinstance(authenticated_subject, str) or not authenticated_subject.strip()
                or not isinstance(tenant_id, str) or not tenant_id.strip()
                or tenant_id != tenant_id.strip()
                or not isinstance(source_id, str) or source_id != source_id.strip()
                or not _SOURCE_ID.fullmatch(source_id)):
            raise PermissionError("INVALID_SCOPE")
        granted: object = None
        timed_out = False
        try:
            async with asyncio.timeout(self._callback_timeout):
                granted = await self._allowed(authenticated_subject, source_id, tenant_id=tenant_id)
        except TimeoutError:
            timed_out = True
        if timed_out or granted is not True:
            raise PermissionError("SOURCE_METADATA_ACCESS_DENIED")
        audit_failed = False
        try:
            async with asyncio.timeout(self._callback_timeout):
                await self._audit("onec.metadata.fetch", {
                    "subject": authenticated_subject, "tenant_id": tenant_id,
                    "source_id": source_id,
                })
        except Exception:  # noqa: BLE001 - any audit-sink failure/timeout must fail closed
            audit_failed = True
        if audit_failed:  # raised outside the except block: no chained audit-sink detail
            raise PermissionError("AUDIT_WRITE_FAILED")
        raw: object = None
        fetch_timed_out = False
        try:
            async with asyncio.timeout(self._fetch_timeout):
                raw = await self._fetch(source_id, self.max_metadata_bytes, tenant_id=tenant_id)
        except TimeoutError:
            fetch_timed_out = True
        if fetch_timed_out:
            raise OneCFetchError("ONEC_FETCH_TIMEOUT")
        if not isinstance(raw, bytes):
            raise TypeError("INVALID_METADATA_RESPONSE")
        # Parsing/hashing up to 20 MB is CPU-bound: keep it off the event loop.
        result = await asyncio.to_thread(
            fingerprint_edmx, raw, tenant_id=tenant_id, source_id=source_id,
            max_bytes=self.max_metadata_bytes,
        )
        allowed = tuple(
            (name, digest) for name, digest in result.objects
            if self._entity_allowed(authenticated_subject, source_id, name,
                                    tenant_id=tenant_id) is True
        )
        withheld = len(result.objects) - len(allowed)
        # Whole-document hashes would leak hidden-object changes: the subject view only
        # carries hashes scoped to visible objects. Impact analysis must run on the
        # unfiltered fingerprint inside the trusted boundary, never on this view.
        return ObservedMetadata(
            source_id=source_id, fingerprint=result.scoped_to_visible(allowed),
            completeness="PARTIAL_ACL_FILTERED" if withheld else "COMPLETE",
            withheld_objects=withheld,
        )
