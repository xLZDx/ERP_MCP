from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

import httpx

from .adapters.onec.atom import parse_atom_payload
from .adapters.onec.client import OneCReadClient
from .adapters.onec.metadata import MetadataIndex, parse_metadata
from .models import Source
from .secrets import SecretProvider


class AdapterProfile(StrEnum):
    ODATA_JSON_V3 = "ODATA_JSON_V3"
    ODATA_ATOM_V3 = "ODATA_ATOM_V3"
    HTTP_QUERY_FALLBACK = "HTTP_QUERY_FALLBACK"
    UNSUPPORTED = "UNSUPPORTED"


class CompatibilityStatus(StrEnum):
    SUPPORTED = "SUPPORTED"
    SUPPORTED_WITH_FALLBACK = "SUPPORTED_WITH_FALLBACK"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class OneCCapabilities:
    source_id: str
    platform_version: str | None
    metadata_fingerprint: str
    metadata_supported: bool
    json_supported: bool
    atom_supported: bool
    expand_supported: bool | None
    entity_set_count: int
    adapter_profile: AdapterProfile
    compatibility_status: CompatibilityStatus
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["adapter_profile"] = self.adapter_profile.value
        data["compatibility_status"] = self.compatibility_status.value
        return data


class OneCCapabilityDetector:
    """Behavior-first 1C capability negotiation.

    Platform version is useful evidence, but the selected profile is based on what the
    concrete published endpoint actually supports.
    """

    def __init__(
        self,
        *,
        client: OneCReadClient,
        secrets: SecretProvider,
    ):
        self.client = client
        self.secrets = secrets

    async def _credentials(self, source: Source) -> tuple[str | None, str | None]:
        username = (
            await self.secrets.get(source.username_secret_ref)
            if source.username_secret_ref
            else None
        )
        password = (
            await self.secrets.get(source.password_secret_ref)
            if source.password_secret_ref
            else None
        )
        return username, password

    @staticmethod
    def _probe_entity(index: MetadataIndex, source: Source):
        for entity in index.entities:
            if source.entity_allowed(entity.name):
                return entity
        return None

    async def detect(self, source: Source) -> tuple[OneCCapabilities, MetadataIndex | None]:
        username, password = await self._credentials(source)
        evidence: dict[str, Any] = {}

        try:
            metadata_raw = await self.client.get_bytes(
                source,
                "$metadata",
                username=username,
                password=password,
                accept="application/xml",
            )
            index = parse_metadata(metadata_raw)
            metadata_supported = True
            metadata_fingerprint = hashlib.sha256(metadata_raw).hexdigest()
            evidence["metadata"] = "ok"
        except Exception as exc:  # noqa: BLE001 - probe failures become capability evidence
            index = None
            metadata_supported = False
            metadata_fingerprint = hashlib.sha256(
                f"metadata-error:{type(exc).__name__}".encode()
            ).hexdigest()
            evidence["metadata"] = type(exc).__name__

        json_supported = False
        atom_supported = False
        expand_supported: bool | None = None

        if index is not None:
            probe = self._probe_entity(index, source)
            if probe is None:
                evidence["read_probe"] = "no-allowed-entity"
            else:
                params = {"$top": 1}
                try:
                    raw = await self.client.get_bytes(
                        source,
                        probe.name,
                        username=username,
                        password=password,
                        params=params,
                        accept="application/json",
                    )
                    json.loads(raw)
                    json_supported = True
                    evidence["json_probe"] = f"ok:{probe.name}"
                except Exception as exc:  # noqa: BLE001 - probe failures become capability evidence
                    evidence["json_probe"] = type(exc).__name__

                try:
                    raw = await self.client.get_bytes(
                        source,
                        probe.name,
                        username=username,
                        password=password,
                        params=params,
                        accept="application/atom+xml",
                    )
                    parse_atom_payload(raw)
                    atom_supported = True
                    evidence["atom_probe"] = f"ok:{probe.name}"
                except Exception as exc:  # noqa: BLE001 - probe failures become capability evidence
                    evidence["atom_probe"] = type(exc).__name__

                if json_supported and probe.navigation_properties:
                    nav = probe.navigation_properties[0]
                    try:
                        raw = await self.client.get_bytes(
                            source,
                            probe.name,
                            username=username,
                            password=password,
                            params={"$top": 1, "$expand": nav},
                            accept="application/json",
                        )
                        json.loads(raw)
                        expand_supported = True
                        evidence["expand_probe"] = f"ok:{probe.name}.{nav}"
                    except httpx.HTTPStatusError as exc:
                        if exc.response.status_code in {400, 404, 405, 406, 501}:
                            expand_supported = False
                        evidence["expand_probe"] = (
                            f"http-{exc.response.status_code}:{probe.name}.{nav}"
                        )
                    except Exception as exc:  # noqa: BLE001 - probe failures become capability evidence
                        evidence["expand_probe"] = type(exc).__name__
                elif json_supported:
                    evidence["expand_probe"] = "unknown:no-navigation-property"

        if json_supported:
            profile = AdapterProfile.ODATA_JSON_V3
            status = CompatibilityStatus.SUPPORTED
        elif atom_supported:
            profile = AdapterProfile.ODATA_ATOM_V3
            status = CompatibilityStatus.SUPPORTED
        elif source.fallback_kind == "onec_http_query" and source.fallback_base_url:
            profile = AdapterProfile.HTTP_QUERY_FALLBACK
            status = CompatibilityStatus.SUPPORTED_WITH_FALLBACK
        else:
            profile = AdapterProfile.UNSUPPORTED
            status = CompatibilityStatus.UNSUPPORTED

        capabilities = OneCCapabilities(
            source_id=source.id,
            platform_version=source.platform_version_hint,
            metadata_fingerprint=metadata_fingerprint,
            metadata_supported=metadata_supported,
            json_supported=json_supported,
            atom_supported=atom_supported,
            expand_supported=expand_supported,
            entity_set_count=len(index.entities) if index else 0,
            adapter_profile=profile,
            compatibility_status=status,
            evidence=evidence,
        )
        return capabilities, index
