from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx

from ...compatibility import AdapterProfile
from ...models import Source

UPSTREAM_SHA = "cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5"


class ODataSidecarError(RuntimeError):
    """Sanitized error from the isolated pinned OData implementation."""


class ODataSidecarClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float,
        max_response_bytes: int,
        max_rows: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("invalid OData sidecar URL")
        self.max_response_bytes = max_response_bytes
        self.max_rows = max_rows
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/",
            timeout=httpx.Timeout(timeout_seconds),
            verify=True,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            transport=transport,
        )

    async def close(self):
        await self._client.aclose()

    async def read(
        self,
        source: Source,
        *,
        username: str | None,
        password: str | None,
        entity_set: str,
        select: list[str] | None,
        filter_expr: str | None,
        orderby: str | None,
        expand: list[str] | None,
        top: int,
        skip: int,
    ) -> dict[str, Any]:
        order_items = [part.strip() for part in orderby.split(",")] if orderby else []
        envelope = await self._request(
            source,
            operation="query",
            username=username,
            password=password,
            entity_set=entity_set,
            select=select or [],
            filter_expr=filter_expr,
            orderby=order_items,
            expand=expand or [],
            top=top,
            skip=skip,
        )
        return {"value": envelope["data"]}

    async def count(
        self,
        source: Source,
        *,
        username: str | None,
        password: str | None,
        entity_set: str,
        filter_expr: str | None,
    ) -> int:
        envelope = await self._request(
            source,
            operation="count",
            username=username,
            password=password,
            entity_set=entity_set,
            select=[],
            filter_expr=filter_expr,
            orderby=[],
            expand=[],
            top=1,
            skip=0,
        )
        try:
            value = envelope["data"][0]["count"]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError
            return value
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ODataSidecarError("OData sidecar returned invalid count") from exc

    async def get(
        self,
        source: Source,
        *,
        username: str,
        password: str,
        entity_set: str,
        key: str | dict[str, str],
    ) -> dict[str, Any]:
        envelope = await self._request(
            source,
            operation="entity_get",
            username=username,
            password=password,
            entity_set=entity_set,
            select=[],
            filter_expr=None,
            orderby=[],
            expand=[],
            top=1,
            skip=0,
            key=key,
        )
        return {"value": envelope["data"]}

    async def register_read(
        self,
        source: Source,
        *,
        username: str,
        password: str,
        register_set: str,
        method: str,
        arguments: dict[str, Any],
        top: int,
        skip: int = 0,
    ) -> dict[str, Any]:
        envelope = await self._request(
            source,
            operation="register_read",
            username=username,
            password=password,
            entity_set=register_set,
            select=[],
            filter_expr=None,
            orderby=[],
            expand=[],
            top=top,
            skip=skip,
            extra_payload={
                "register_set": register_set,
                "register_method": method,
                "register_args": arguments,
            },
        )
        return {"value": envelope["data"], "page": envelope["page"]}

    async def _request(
        self,
        source: Source,
        *,
        operation: str,
        username: str | None,
        password: str | None,
        entity_set: str,
        select: list[str],
        filter_expr: str | None,
        orderby: list[str],
        expand: list[str],
        top: int,
        skip: int,
        key: str | dict[str, str] | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "operation": operation,
            "source_id": source.id,
            "base_url": source.base_url,
            "username": username,
            "password": password,
            "entity_set": entity_set,
            "select": select,
            "filter": filter_expr,
            "orderby": orderby,
            "expand": expand,
            "top": top,
            "skip": skip,
        }
        if operation == "entity_get":
            payload["key"] = key
        if extra_payload:
            payload.update(extra_payload)
        try:
            async with self._client.stream("POST", "v1/read", json=payload) as response:
                if response.status_code != 200:
                    raise ODataSidecarError(f"OData sidecar returned HTTP {response.status_code}")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > self.max_response_bytes:
                    raise ODataSidecarError("OData sidecar response exceeded configured limit")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self.max_response_bytes:
                        raise ODataSidecarError("OData sidecar response exceeded configured limit")
        except httpx.HTTPError as exc:
            raise ODataSidecarError("OData sidecar is unavailable") from exc
        try:
            envelope = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ODataSidecarError("OData sidecar returned invalid JSON") from exc
        if not isinstance(envelope, dict) or envelope.get("source_id") != source.id:
            raise ODataSidecarError("OData sidecar source provenance mismatch")
        adapter = envelope.get("adapter")
        if (
            not isinstance(adapter, dict)
            or adapter.get("kind") != AdapterProfile.ODATA_JSON_V3.value
        ):
            raise ODataSidecarError("OData sidecar adapter provenance mismatch")
        if adapter.get("upstream_sha") != UPSTREAM_SHA:
            raise ODataSidecarError("OData sidecar upstream pin mismatch")
        data = envelope.get("data")
        if (
            envelope.get("operation") != operation
            or not isinstance(data, list)
            or (operation == "query" and len(data) > self.max_rows)
            or (operation == "entity_get" and len(data) != 1)
            or (operation == "register_read" and len(data) > self.max_rows)
        ):
            raise ODataSidecarError("OData sidecar response contract mismatch")
        return envelope
