from __future__ import annotations

import json

from ...compatibility import AdapterProfile, OneCCapabilities, OneCCapabilityDetector
from ...models import Source
from ...secrets import SecretProvider
from ...settings import Settings
from .atom import parse_atom_payload
from .client import OneCReadClient
from .metadata import MetadataIndex, parse_metadata


def normalize_json_payload(payload):
    if isinstance(payload, dict) and "d" in payload:
        data = payload["d"]
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return {"value": data["results"]}
        if isinstance(data, dict):
            return {"value": [data]}
    return payload


class OneCAdapter:
    def __init__(self, settings: Settings, secrets: SecretProvider, client: OneCReadClient):
        self.settings = settings
        self.secrets = secrets
        self.client = client
        self._metadata: dict[str, MetadataIndex] = {}
        self._capabilities: dict[str, OneCCapabilities] = {}
        self._detector = OneCCapabilityDetector(client=client, secrets=secrets)

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
        return await self.client.head_metadata(
            source, username=username, password=password
        )

    async def capabilities(
        self,
        source: Source,
        *,
        refresh: bool = False,
    ) -> OneCCapabilities:
        if not refresh and source.id in self._capabilities:
            return self._capabilities[source.id]
        capabilities, index = await self._detector.detect(source)
        self._capabilities[source.id] = capabilities
        if index is not None:
            self._metadata[source.id] = index
        return capabilities

    async def metadata(self, source: Source, *, refresh: bool = False) -> MetadataIndex:
        if not refresh and source.id in self._metadata:
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
            x for x in index.find(contains, max(1, min(limit, 200)))
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
