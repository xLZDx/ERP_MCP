from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from urllib.parse import urlparse

import httpx

from .adapters.onec.adapter import OneCAdapter
from .adapters.onec.client import OneCReadClient
from .models import Source


class SourceEgressDenied(PermissionError):
    code = "SOURCE_EGRESS_DENIED"


class PinnedSourceTransport(httpx.AsyncBaseTransport):
    """Connect to a validated numeric address; retain the original TLS name and Host."""

    def __init__(self, host: str, port: int, address: str, transport=None):
        self.host, self.port, self.address = host, port, address
        self.transport = transport or httpx.AsyncHTTPTransport(trust_env=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method not in {"GET", "HEAD"}:
            raise SourceEgressDenied("probe transport is read-only")
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        if request.url.host.casefold() != self.host or port != self.port:
            raise SourceEgressDenied("probe target differs from approved authority")
        extensions = {**request.extensions, "sni_hostname": self.host}
        pinned = httpx.Request(
            request.method,
            request.url.copy_with(host=self.address),
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )
        return await self.transport.handle_async_request(pinned)

    async def aclose(self):
        await self.transport.aclose()


def _split_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


class SourceEgressPolicy:
    def __init__(self, *, allowed_hosts: str, allowed_cidrs: str):
        self.allowed_hosts = frozenset(item.casefold() for item in _split_csv(allowed_hosts))
        self.allowed_networks = tuple(
            ipaddress.ip_network(item, strict=False) for item in _split_csv(allowed_cidrs)
        )

    @staticmethod
    def authority(url: str) -> tuple[str, int]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise SourceEgressDenied("source URL must be absolute HTTP(S)")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise SourceEgressDenied("source URL credentials/query/fragment are forbidden")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return parsed.hostname.casefold(), port

    async def validate(self, url: str) -> dict[str, object]:
        host, port = self.authority(url)
        authority = f"{host}:{port}"
        if authority not in self.allowed_hosts and not (
            host in self.allowed_hosts and port in {80, 443}
        ):
            raise SourceEgressDenied("source host is not in the administrative egress allowlist")

        infos = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            port,
            type=socket.SOCK_STREAM,
        )
        addresses = sorted({item[4][0] for item in infos})
        if not addresses:
            raise SourceEgressDenied("source hostname did not resolve")

        if self.allowed_networks:
            for raw in addresses:
                address = ipaddress.ip_address(raw)
                if not any(address in network for network in self.allowed_networks):
                    raise SourceEgressDenied(
                        f"resolved address {address} is outside approved source networks"
                    )

        return {"host": host, "port": port, "resolved_addresses": addresses}


class AdminSourceProbe:
    def __init__(self, runtime, policy: SourceEgressPolicy):
        self.runtime = runtime
        self.policy = policy
        self._slots = asyncio.Semaphore(4)

    @asynccontextmanager
    async def approved_adapter(self, base_url: str):
        # Separate pool and caches isolate slow probes from the MCP runtime.
        started = time.monotonic()
        outcome = "error"
        try:
            async with asyncio.timeout(45), self._slots:
                egress = await self.policy.validate(base_url)
                transport = PinnedSourceTransport(
                    str(egress["host"]), int(egress["port"]), egress["resolved_addresses"][0]
                )
                client = OneCReadClient(
                    timeout_seconds=min(self.runtime.settings.http_timeout_seconds, 10),
                    max_response_bytes=min(self.runtime.settings.max_response_bytes, 5_000_000),
                    transport=transport,
                )
                adapter = OneCAdapter(self.runtime.settings, self.runtime.secrets, client)
                try:
                    yield adapter, egress
                    outcome = "success"
                finally:
                    await client.close()
        finally:
            logging.getLogger("uvicorn.error").info("admin_source_probe outcome=%s duration_ms=%s",
                outcome, int((time.monotonic() - started) * 1000))

    async def probe(
        self,
        *,
        base_url: str,
        username_secret_ref: str,
        password_secret_ref: str,
        display_name: str = "Admin source probe",
        platform_version_hint: str | None = None,
    ) -> dict[str, object]:
        source = Source(
            id=f"admin-probe-{uuid.uuid4()}",
            project="onec",
            kind="onec_auto",
            display_name=display_name,
            base_url=base_url,
            username_secret_ref=username_secret_ref,
            password_secret_ref=password_secret_ref,
            read_only=True,
            enabled=True,
            tags=(),
            entity_allow_patterns=(),
            entity_deny_patterns=(),
            platform_version_hint=platform_version_hint,
        )
        source.validate_runtime(
            production=self.runtime.settings.environment == "production"
        )

        async with self.approved_adapter(base_url) as (adapter, egress):
            health = await adapter.health(source)
            if not health.get("ok"):
                raise SourceEgressDenied("source health probe failed")
            capabilities = await adapter.capabilities(source, refresh=True)
            if not capabilities.metadata_supported:
                raise SourceEgressDenied("source metadata unavailable")

        safe_capabilities = replace(
            capabilities,
            source_id="candidate",
            evidence={
                key: value
                for key, value in capabilities.evidence.items()
                if isinstance(value, (str, int, float, bool, type(None)))
            },
            register_capabilities={},
        ).as_dict()
        return {
            "egress": {
                "host": egress["host"],
                "port": egress["port"],
                "resolved_count": len(egress["resolved_addresses"]),
            },
            "health": {
                "status_code": int(health.get("status_code", 0)),
                "ok": bool(health.get("ok", False)),
            },
            "capabilities": safe_capabilities,
        }
