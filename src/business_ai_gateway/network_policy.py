from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

import httpcore
import httpx
from httpcore._backends.anyio import AnyIOBackend


class EgressPolicyError(RuntimeError):
    """The resolved destination is outside the configured egress policy."""


async def validate_resolved_egress(url: str, cidrs: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve immediately before connect and require every answer in approved CIDRs."""
    if not cidrs:
        return ()
    parsed = urlparse(url)
    if not parsed.hostname:
        raise EgressPolicyError("destination hostname is missing")
    return await resolve_egress_host(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), cidrs)


async def resolve_egress_host(host: str, port: int, cidrs: tuple[str, ...]) -> tuple[str, ...]:
    if not cidrs:
        return ()
    try:
        networks = tuple(ipaddress.ip_network(item, strict=False) for item in cidrs)
    except ValueError:
        raise EgressPolicyError("egress policy is invalid") from None
    try:
        answers = await asyncio.to_thread(
            socket.getaddrinfo,
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        raise EgressPolicyError("destination resolution failed") from None
    addresses = tuple(sorted({item[4][0] for item in answers}))
    if not addresses or len(addresses) > 64:
        raise EgressPolicyError("destination resolution returned no addresses")
    try:
        parsed_addresses = tuple(ipaddress.ip_address(item) for item in addresses)
    except ValueError:
        raise EgressPolicyError("destination resolution returned an invalid address") from None
    if any(not any(address in network for network in networks) for address in parsed_addresses):
        raise EgressPolicyError("destination is outside the egress policy")
    return addresses


class PinnedEgressBackend(httpcore.AsyncNetworkBackend):
    """Resolve and validate at TCP connect; dial only the resulting numeric addresses.

    httpcore retains the original origin for TLS server_hostname and certificate checks.
    HTTP/OData framing remains entirely in the pinned HTTPX/httpcore dependencies.
    """

    def __init__(self, cidrs: tuple[str, ...], backend=None):
        self.cidrs = cidrs
        self.backend = backend or AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            async with asyncio.timeout(timeout):
                addresses = await resolve_egress_host(host, port, self.cidrs)
                for address in addresses or (host,):
                    try:
                        return await self.backend.connect_tcp(address, port, timeout=timeout,
                                                              local_address=local_address,
                                                              socket_options=socket_options)
                    except httpcore.ConnectError:
                        continue
        except EgressPolicyError:
            raise httpcore.ConnectError("EGRESS_DESTINATION_DENIED") from None
        except TimeoutError:
            raise httpcore.ConnectTimeout("EGRESS_CONNECT_TIMEOUT") from None
        raise httpcore.ConnectError("EGRESS_CONNECTION_FAILED")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise httpcore.ConnectError("EGRESS_UNIX_SOCKET_DENIED")

    async def sleep(self, seconds):
        await self.backend.sleep(seconds)


def pinned_egress_transport(cidrs: tuple[str, ...]) -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport(verify=True, trust_env=False,
                                        limits=httpx.Limits(max_connections=100,
                                                            max_keepalive_connections=20))
    # HTTPX 0.28/httpcore 1.0 pool integration is covered by wiring and connect tests.
    # Reuse the existing transport/SSL context rather than duplicating HTTP framing.
    transport._pool._network_backend = PinnedEgressBackend(cidrs)
    return transport
