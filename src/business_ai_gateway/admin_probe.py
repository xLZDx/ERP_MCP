from __future__ import annotations

import asyncio
import ipaddress
import socket
import uuid
from dataclasses import replace
from urllib.parse import urlparse

from .models import Source


class SourceEgressDenied(PermissionError):
    code = "SOURCE_EGRESS_DENIED"


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
        if host not in self.allowed_hosts and authority not in self.allowed_hosts:
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

    async def probe(
        self,
        *,
        base_url: str,
        username_secret_ref: str,
        password_secret_ref: str,
        display_name: str = "Admin source probe",
        platform_version_hint: str | None = None,
    ) -> dict[str, object]:
        egress = await self.policy.validate(base_url)
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

        health = await self.runtime.onec.health(source)
        capabilities = await self.runtime.onec.capabilities(source, refresh=True)
        # Probe identities are ephemeral and must not remain in adapter caches.
        self.runtime.onec._metadata.pop(source.id, None)
        self.runtime.onec._capabilities.pop(source.id, None)

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
            "egress": egress,
            "health": {
                "status_code": int(health.get("status_code", 0)),
                "ok": bool(health.get("ok", False)),
            },
            "capabilities": safe_capabilities,
        }
