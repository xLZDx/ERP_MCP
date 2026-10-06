from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from urllib.parse import unquote, urljoin, urlparse

import httpx

from ...models import Source
from ...network_policy import EgressPolicyError, pinned_egress_transport, validate_resolved_egress


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
        allowed_egress_cidrs: tuple[str, ...] = (),
    ):
        self.max_response_bytes = max_response_bytes
        self.allowed_egress_cidrs = allowed_egress_cidrs
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            verify=True,
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=100,
                max_keepalive_connections=20,
                keepalive_expiry=30,
            ),
            headers={"User-Agent": "erp-mcp/0.1"},
            transport=transport or (pinned_egress_transport(allowed_egress_cidrs) if allowed_egress_cidrs else None),
            trust_env=False,
        )

    async def close(self):
        await self._client.aclose()

    @staticmethod
    def _url(source: Source, relative: str) -> str:
        base = source.base_url.rstrip("/") + "/"
        clean = relative
        decoded = relative
        for _ in range(8):
            if (
                not decoded or decoded.startswith("/") or "\\" in decoded
                or any(ord(character) < 32 or ord(character) == 127 for character in decoded)
                or any(segment in {".", ".."} for segment in decoded.split("/"))
                or urlparse(decoded).scheme or "?" in decoded or "#" in decoded
            ):
                raise OneCTransportError("unsafe relative OData path")
            next_decoded = unquote(decoded)
            if next_decoded == decoded:
                break
            decoded = next_decoded
        else:
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
        try:
            await validate_resolved_egress(url, self.allowed_egress_cidrs)
        except EgressPolicyError:
            raise OneCTransportError("SOURCE_EGRESS_DENIED") from None

        for attempt in range(3):
            try:
                request = self._client.build_request(
                    "GET", url, params=params,
                    headers={"Accept": accept, "Accept-Encoding": "identity"},
                )
                response = await self._client.send(request, stream=True, auth=auth)
            except httpx.TimeoutException:
                raise OneCTransportError("SOURCE_TIMEOUT") from None
            except httpx.RequestError:
                raise OneCTransportError("SOURCE_NETWORK_ERROR") from None
            try:
                if response.status_code in self.RETRYABLE and attempt < 2:
                    retry_after = response.headers.get("Retry-After")
                    delay = 0.25 * (2**attempt)
                    if retry_after and retry_after.isdigit():
                        delay = min(float(retry_after), 3.0)
                    await response.aclose()
                    await asyncio.sleep(delay)
                    continue
                if response.is_error or 300 <= response.status_code < 400:
                    raise OneCTransportError(f"1C_UPSTREAM_HTTP_{response.status_code}")
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
            finally:
                await response.aclose()

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
        try:
            try:
                await validate_resolved_egress(
                    self._url(source, "$metadata"), self.allowed_egress_cidrs
                )
            except EgressPolicyError:
                raise OneCTransportError("SOURCE_EGRESS_DENIED") from None
            response = await self._client.head(
                self._url(source, "$metadata"),
                headers={"Accept": "application/xml"},
                auth=auth,
            )
        except httpx.TimeoutException:
            raise OneCTransportError("SOURCE_TIMEOUT") from None
        except httpx.RequestError:
            raise OneCTransportError("SOURCE_NETWORK_ERROR") from None
        try:
            return {"status_code": response.status_code, "ok": response.is_success}
        finally:
            await response.aclose()
