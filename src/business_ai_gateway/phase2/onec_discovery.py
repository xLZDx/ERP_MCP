"""Phase 2 connector contracts: registered-source discovery, read only.

No arbitrary caller URL, executable, SQL or secret parameters. Server must
supply an authorized loader bound to its own source registry and policy.
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .structural_hash import StructuralFingerprint, fingerprint_edmx

_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ObservedMetadata:
    source_id: str
    fingerprint: StructuralFingerprint
    completeness: str = "COMPLETE"
    trust: str = "OBSERVED_ONLY"


class OneCMetadataDiscovery:
    """Never makes its own network connection or accepts a URL from the user.

    allow_source_metadata: trusted ACL adapter for source-wide metadata (not
    a company-level grant). fetch_registered_metadata: existing read-only
    1C adapter that resolves endpoint and secret refs from server registry.
    """

    def __init__(
        self,
        *,
        allow_source_metadata: Callable[[str, str], Awaitable[bool]],
        fetch_registered_metadata: Callable[[str], Awaitable[bytes]],
        max_metadata_bytes: int = 20_000_000,
    ):
        if not callable(allow_source_metadata) or not callable(fetch_registered_metadata):
            raise TypeError("TRUSTED_CONNECTOR_CALLBACKS_REQUIRED")
        if not 0 < max_metadata_bytes <= 20_000_000:
            raise ValueError("METADATA_BUDGET_INVALID")
        self._allowed = allow_source_metadata
        self._fetch = fetch_registered_metadata
        self.max_metadata_bytes = max_metadata_bytes

    async def observe(self, *, authenticated_subject: str, source_id: str) -> ObservedMetadata:
        if not authenticated_subject or not _SOURCE_ID.fullmatch(source_id):
            raise PermissionError("INVALID_SCOPE")
        if not await self._allowed(authenticated_subject, source_id):
            raise PermissionError("SOURCE_METADATA_ACCESS_DENIED")
        raw = await self._fetch(source_id)
        if not isinstance(raw, bytes):
            raise TypeError("INVALID_METADATA_RESPONSE")
        result = fingerprint_edmx(raw, max_bytes=self.max_metadata_bytes)
        return ObservedMetadata(source_id=source_id, fingerprint=result)
