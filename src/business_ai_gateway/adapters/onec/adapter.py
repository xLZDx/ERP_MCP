from __future__ import annotations

import json
import time
from dataclasses import replace

from ...compatibility import (
    AdapterProfile,
    CapabilityUnsupported,
    OneCCapabilities,
    OneCCapabilityDetector,
)
from ...models import Source
from ...secrets import SecretProvider
from ...settings import Settings
from .atom import parse_atom_payload
from .client import OneCReadClient
from .metadata import MetadataIndex, parse_metadata
from .rsv_bridge import RSVDataBridgeClient
from .sidecar_client import ODataSidecarClient


def normalize_json_payload(payload):
    if isinstance(payload, dict) and "d" in payload:
        data = payload["d"]
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return {"value": data["results"]}
        if isinstance(data, dict):
            return {"value": [data]}
    return payload


class OneCAdapter:
    def __init__(
        self,
        settings: Settings,
        secrets: SecretProvider,
        client: OneCReadClient,
        sidecar: ODataSidecarClient | None = None,
        rsv_bridge: RSVDataBridgeClient | None = None,
    ):
        self.settings = settings
        self.secrets = secrets
        self.client = client
        self.sidecar = sidecar
        self.rsv_bridge = rsv_bridge
        self._metadata: dict[str, MetadataIndex] = {}
        self._capabilities: dict[str, OneCCapabilities] = {}
        self._metadata_expires_at: dict[str, float] = {}
        self._capabilities_expires_at: dict[str, float] = {}
        self._source_cache_identity: dict[str, tuple[str, str | None, str | None]] = {}
        self._clock = time.monotonic
        self._detector = OneCCapabilityDetector(client=client, secrets=secrets)

    def _invalidate_changed_source(self, source: Source) -> None:
        identity = (source.base_url, source.username_secret_ref, source.password_secret_ref)
        previous = self._source_cache_identity.get(source.id)
        if previous is not None and previous != identity:
            self._metadata.pop(source.id, None)
            self._metadata_expires_at.pop(source.id, None)
            self._capabilities.pop(source.id, None)
            self._capabilities_expires_at.pop(source.id, None)
        self._source_cache_identity[source.id] = identity

    async def credentials(self, source: Source) -> tuple[str | None, str | None]:
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
        if (username is None) != (password is None):
            raise RuntimeError("1C username/password secret refs must be paired")
        return username, password

    async def health(self, source: Source):
        username, password = await self.credentials(source)
        return await self.client.head_metadata(source, username=username, password=password)

    async def capabilities(
        self,
        source: Source,
        *,
        refresh: bool = False,
    ) -> OneCCapabilities:
        self._invalidate_changed_source(source)
        now = self._clock()
        capability_fresh = self._capabilities_expires_at.get(source.id, 0) > now
        metadata_fresh = (
            source.id not in self._metadata
            or self._metadata_expires_at.get(source.id, 0) > now
        )
        if not refresh and source.id in self._capabilities and capability_fresh and metadata_fresh:
            return self._capabilities[source.id]
        capabilities, index = await self._detector.detect(source)
        if capabilities.adapter_profile == AdapterProfile.ODATA_JSON_V3 and self.sidecar is not None:
            username, password = await self.credentials(source)
            if username is not None and password is not None:
                try:
                    register_profile = await self.sidecar.register_capabilities(
                        source, username=username, password=password
                    )
                    if register_profile.get("metadata_fingerprint") != capabilities.metadata_fingerprint:
                        register_profile = {
                            "schema_version": 1,
                            "source_id": source.id,
                            "evidence_source": "live-metadata",
                            "status": "stale-metadata-fingerprint",
                            "metadata_fingerprint": register_profile.get("metadata_fingerprint"),
                            "registers": [],
                        }
                    capabilities = replace(capabilities, register_capabilities=register_profile)
                except Exception as exc:  # noqa: BLE001
                    capabilities = replace(
                        capabilities,
                        register_capabilities={
                            "schema_version": 1,
                            "source_id": source.id,
                            "evidence_source": "live-metadata",
                            "status": f"discovery-failed:{type(exc).__name__}",
                            "metadata_fingerprint": capabilities.metadata_fingerprint,
                            "registers": [],
                        },
                    )
        self._capabilities[source.id] = capabilities
        self._capabilities_expires_at[source.id] = (
            self._clock() + self.settings.metadata_cache_ttl_seconds
        )
        if index is not None:
            self._metadata[source.id] = index
            self._metadata_expires_at[source.id] = (
                self._clock() + self.settings.metadata_cache_ttl_seconds
            )
        else:
            self._metadata.pop(source.id, None)
            self._metadata_expires_at.pop(source.id, None)
        return capabilities

    async def metadata(self, source: Source, *, refresh: bool = False) -> MetadataIndex:
        self._invalidate_changed_source(source)
        if (
            not refresh
            and source.id in self._metadata
            and self._metadata_expires_at.get(source.id, 0) > self._clock()
        ):
            return self._metadata[source.id]
        username, password = await self.credentials(source)
        raw = await self.client.get_bytes(
            source,
            "$metadata",
            username=username,
            password=password,
            accept="application/xml",
        )
        index = parse_metadata(raw)
        self._metadata[source.id] = index
        self._metadata_expires_at[source.id] = (
            self._clock() + self.settings.metadata_cache_ttl_seconds
        )
        # A newly fetched schema must be paired with a newly computed fingerprint.
        self._capabilities.pop(source.id, None)
        self._capabilities_expires_at.pop(source.id, None)
        return index

    async def summary(self, source: Source):
        index = await self.metadata(source)
        groups: dict[str, int] = {}
        for item in index.entities:
            prefix = item.name.split("_", 1)[0]
            groups[prefix] = groups.get(prefix, 0) + 1
        return {
            "source_id": source.id,
            "entity_set_count": len(index.entities),
            "groups": dict(sorted(groups.items())),
        }

    async def find(self, source: Source, contains: str, limit: int):
        index = await self.metadata(source)
        found = [
            x
            for x in index.find(contains, max(1, min(limit, 200)))
            if source.entity_allowed(x.name)
        ]
        return [
            {
                "name": x.name,
                "entity_type": x.entity_type,
                "properties": list(x.properties),
                "navigation_properties": list(x.navigation_properties),
            }
            for x in found
        ]

    async def read(
        self,
        source: Source,
        *,
        entity_set: str,
        select: list[str] | None,
        filter_expr: str | None,
        orderby: str | None,
        expand: list[str] | None,
        top: int,
        skip: int,
    ):
        if "/" in entity_set or "\\" in entity_set or entity_set.startswith("$"):
            raise ValueError("invalid EntitySet")
        if not source.entity_allowed(entity_set):
            raise PermissionError("EntitySet denied by source policy")
        if filter_expr and len(filter_expr) > self.settings.max_filter_chars:
            raise ValueError("filter expression too long")
        if orderby and len(orderby) > 1000:
            raise ValueError("orderby too long")
        if select and (len(select) > 100 or any(len(x) > 256 for x in select)):
            raise ValueError("select is too large")
        if expand and (len(expand) > 20 or any(len(x) > 256 for x in expand)):
            raise ValueError("expand is too large")

        if self.settings.require_metadata_entity:
            index = await self.metadata(source)
            if entity_set not in index.names:
                raise ValueError(f"EntitySet not present in live metadata: {entity_set}")

        capabilities = await self.capabilities(source)
        if expand and capabilities.expand_supported is False:
            raise ValueError("$expand is not supported by this 1C capability profile")

        params = {
            "$top": max(1, min(top, self.settings.max_rows)),
            "$skip": max(0, skip),
        }
        if select:
            params["$select"] = ",".join(select)
        if filter_expr:
            params["$filter"] = filter_expr
        if orderby:
            params["$orderby"] = orderby
        if expand:
            params["$expand"] = ",".join(expand)

        username, password = await self.credentials(source)

        if capabilities.adapter_profile == AdapterProfile.ODATA_JSON_V3:
            if self.sidecar is not None and username is not None and password is not None:
                return await self.sidecar.read(
                    source,
                    username=username,
                    password=password,
                    entity_set=entity_set,
                    select=select,
                    filter_expr=filter_expr,
                    orderby=orderby,
                    expand=expand,
                    top=params["$top"],
                    skip=params["$skip"],
                )
            raw = await self.client.get_bytes(
                source,
                entity_set,
                username=username,
                password=password,
                params=params,
                accept="application/json",
            )
            try:
                return normalize_json_payload(json.loads(raw))
            except json.JSONDecodeError as exc:
                raise RuntimeError("1C returned invalid JSON") from exc

        if capabilities.adapter_profile == AdapterProfile.ODATA_ATOM_V3:
            raw = await self.client.get_bytes(
                source,
                entity_set,
                username=username,
                password=password,
                params=params,
                accept="application/atom+xml",
            )
            return parse_atom_payload(raw)

        if capabilities.adapter_profile == AdapterProfile.HTTP_QUERY_FALLBACK:
            raise NotImplementedError(
                "source requires the read-only HTTP/query fallback; "
                "generic OData entity reads are unavailable for this source"
            )

        raise RuntimeError("no supported safe 1C read transport detected")

    async def count(
        self, source: Source, *, entity_set: str, filter_expr: str | None = None
    ) -> int:
        if "/" in entity_set or "\\" in entity_set or entity_set.startswith("$"):
            raise ValueError("invalid EntitySet")
        if not source.entity_allowed(entity_set):
            raise PermissionError("EntitySet denied by source policy")
        if filter_expr and len(filter_expr) > self.settings.max_filter_chars:
            raise ValueError("filter expression too long")
        if self.settings.require_metadata_entity:
            index = await self.metadata(source)
            if entity_set not in index.names:
                raise ValueError(f"EntitySet not present in live metadata: {entity_set}")
        capabilities = await self.capabilities(source)
        if capabilities.adapter_profile != AdapterProfile.ODATA_JSON_V3 or self.sidecar is None:
            raise NotImplementedError("entity count requires the pinned OData JSON sidecar")
        username, password = await self.credentials(source)
        if username is None or password is None:
            raise RuntimeError("pinned OData sidecar requires paired username/password credentials")
        return await self.sidecar.count(
            source,
            username=username,
            password=password,
            entity_set=entity_set,
            filter_expr=filter_expr,
        )

    async def get(self, source: Source, *, entity_set: str, key: str | dict[str, str]):
        if "/" in entity_set or "\\" in entity_set or entity_set.startswith("$"):
            raise ValueError("invalid EntitySet")
        if not source.entity_allowed(entity_set):
            raise PermissionError("EntitySet denied by source policy")
        if self.settings.require_metadata_entity:
            index = await self.metadata(source)
            if entity_set not in index.names:
                raise ValueError(f"EntitySet not present in live metadata: {entity_set}")
        capabilities = await self.capabilities(source)
        if capabilities.adapter_profile != AdapterProfile.ODATA_JSON_V3 or self.sidecar is None:
            raise NotImplementedError("entity get requires the pinned OData JSON sidecar")
        username, password = await self.credentials(source)
        if username is None or password is None:
            raise RuntimeError("pinned OData sidecar requires paired username/password credentials")
        return await self.sidecar.get(
            source, username=username, password=password, entity_set=entity_set, key=key
        )

    async def register_read(
        self,
        source: Source,
        *,
        register_set: str,
        method: str,
        arguments: dict,
        top: int,
        skip: int = 0,
    ):
        if not source.entity_allowed(register_set):
            raise PermissionError("register denied by source policy")
        if not register_set.startswith(
            ("AccumulationRegister_", "InformationRegister_", "AccountingRegister_")
        ):
            raise ValueError("invalid register EntitySet")
        if self.settings.require_metadata_entity:
            index = await self.metadata(source)
            if register_set not in index.names:
                raise ValueError(f"register not present in live metadata: {register_set}")
        capabilities = await self.capabilities(source)
        if capabilities.adapter_profile != AdapterProfile.ODATA_JSON_V3 or self.sidecar is None:
            raise NotImplementedError("register reads require the pinned OData JSON sidecar")
        profile = capabilities.register_capabilities
        matched_register = next(
            (
                item
                for item in profile.get("registers", [])
                if item.get("entity_set") == register_set
            ),
            None,
        )
        method_evidence = (
            matched_register.get("methods", {}).get(method)
            if isinstance(matched_register, dict)
            else None
        )
        if (
            profile.get("evidence_source") != "live-metadata"
            or profile.get("metadata_fingerprint") != capabilities.metadata_fingerprint
            or not isinstance(method_evidence, dict)
            or method_evidence.get("available") is not True
        ):
            raise CapabilityUnsupported(
                f"CAPABILITY_UNSUPPORTED: {register_set}/{method} has no source capability evidence"
            )
        username, password = await self.credentials(source)
        if username is None or password is None:
            raise RuntimeError("pinned OData sidecar requires paired username/password credentials")
        return await self.sidecar.register_read(
            source,
            username=username,
            password=password,
            register_set=register_set,
            method=method,
            arguments=arguments,
            top=max(1, min(top, self.settings.max_rows)),
            skip=max(0, skip),
        )
