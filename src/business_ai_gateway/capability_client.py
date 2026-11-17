from __future__ import annotations

import json
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx


class CapabilityObserverUnavailable(RuntimeError):
    code = "CAPABILITY_OBSERVER_UNAVAILABLE"


class CapabilityObserverClient:
    """Request independently probed capability state without holding DB authority."""

    def __init__(
        self,
        *,
        base_url: str | None,
        token: str | None,
        production: bool,
        timeout_seconds: float,
        max_response_bytes: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = None
        self.token = token
        self.max_response_bytes = max_response_bytes
        self._client: httpx.AsyncClient | None = None
        if base_url is None and token is None:
            if production:
                raise ValueError("production requires the capability observer service")
            return
        if not base_url or not token:
            raise ValueError("capability observer URL and token must be configured together")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("invalid capability observer URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("capability observer URL must not contain credentials/query/fragment")
        if production and parsed.scheme != "https":
            raise ValueError("production capability observer service must use HTTPS")
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds),
            verify=True,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=8),
            transport=transport,
            trust_env=False,
        )

    async def refresh(
        self,
        *,
        source_id: str,
        access_token: str | None,
        request_id: str | UUID | None = None,
    ) -> dict:
        if self._client is None or not self.token:
            raise CapabilityObserverUnavailable("CAPABILITY_OBSERVER_UNAVAILABLE")
        if not source_id or len(source_id) > 128:
            raise ValueError("CAPABILITY_SOURCE_INVALID")
        headers = {"X-Capability-Worker-Token": self.token}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        correlation_id = str(UUID(str(request_id))) if request_id else str(uuid4())
        try:
            async with self._client.stream(
                "POST",
                "/internal/v1/observe-capabilities",
                json={"source_id": source_id, "request_id": correlation_id},
                headers=headers,
            ) as response:
                response.raise_for_status()
                body = bytearray()
                chunk_size = max(1, min(64 * 1024, self.max_response_bytes + 1))
                async for chunk in response.aiter_bytes(chunk_size=chunk_size):
                    if len(body) + len(chunk) > self.max_response_bytes:
                        raise CapabilityObserverUnavailable("CAPABILITY_OBSERVER_UNAVAILABLE")
                    body.extend(chunk)
                result = json.loads(body)
        except (httpx.HTTPError, ValueError) as exc:
            raise CapabilityObserverUnavailable("CAPABILITY_OBSERVER_UNAVAILABLE") from exc
        if not isinstance(result, dict) or result.get("source_id") != source_id:
            raise CapabilityObserverUnavailable("CAPABILITY_OBSERVER_UNAVAILABLE")
        if result.get("request_id") != correlation_id or result.get("status") not in {
            "STABLE", "DRIFTED", "NEEDS_VALIDATION"
        }:
            raise CapabilityObserverUnavailable("CAPABILITY_OBSERVER_UNAVAILABLE")
        observation_id = result.get("observation_id")
        if type(observation_id) is not int or observation_id <= 0:
            raise CapabilityObserverUnavailable("CAPABILITY_OBSERVER_UNAVAILABLE")
        return result

    async def ready(self) -> bool:
        if self._client is None or not self.token:
            return False
        try:
            response = await self._client.get(
                "/readyz", headers={"X-Capability-Worker-Token": self.token}
            )
            return response.is_success and response.json().get("status") == "ready"
        except (httpx.HTTPError, ValueError, AttributeError):
            return False

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
