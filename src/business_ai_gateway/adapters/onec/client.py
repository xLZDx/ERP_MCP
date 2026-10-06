from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from urllib.parse import urljoin, urlparse

import httpx

from ...models import Source


class OneCTransportError(RuntimeError):
    pass


class OneCReadClient:
    """1C OData transport with only GET/HEAD. Write verbs intentionally do not exist."""

    RETRYABLE: ClassVar[set[int]] = {429, 502, 503, 504}

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.max_response_bytes = max_response_bytes
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            verify=True,
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30,
            ),
            headers={"User-Agent": "erp-mcp/0.1", "Accept-Encoding": "identity"},
            transport=transport,
        )

    async def close(self):
        await self._client.aclose()

    @staticmethod
    def _url(source: Source, relative: str) -> str:
        base = source.base_url.rstrip("/") + "/"
        clean = relative.lstrip("/")
        if "://" in clean or clean.startswith("//") or ".." in clean.split("/"):
            raise OneCTransportError("unsafe relative OData path")
        target = urljoin(base, clean)
        if urlparse(base).hostname != urlparse(target).hostname:
            raise OneCTransportError("target host differs from registered source")
        return target

    async def get_bytes(
        self,
        source: Source,
        relative: str,
        *,
        username: str | None,
        password: str | None,
        params: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> bytes:
        auth = (
            httpx.BasicAuth(username, password)
            if username is not None and password is not None
            else None
        )
        url = self._url(source, relative)

        for attempt in range(3):
            async with self._client.stream(
                "GET",
                url,
                params=params,
                headers={"Accept": accept},
                auth=auth,
            ) as response:
                if response.status_code in self.RETRYABLE and attempt < 2:
                    retry_after = response.headers.get("Retry-After")
                    delay = 0.25 * (2**attempt)
                    if retry_after and retry_after.isdigit():
                        delay = min(float(retry_after), 3.0)
                    await response.aclose()
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise OneCTransportError("encoded response is unsupported by bounded native transport")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > self.max_response_bytes:
                        raise OneCTransportError(
                            f"response exceeded {self.max_response_bytes} bytes"
                        )
                return bytes(data)

        raise OneCTransportError("unreachable retry state")

    async def head_metadata(
        self,
        source: Source,
        *,
        username: str | None,
        password: str | None,
    ) -> dict[str, Any]:
        auth = (
            httpx.BasicAuth(username, password)
            if username is not None and password is not None
            else None
        )
        response = await self._client.head(
            self._url(source, "$metadata"),
            headers={"Accept": "application/xml"},
            auth=auth,
        )
        try:
            return {"status_code": response.status_code, "ok": response.is_success}
        finally:
            await response.aclose()
