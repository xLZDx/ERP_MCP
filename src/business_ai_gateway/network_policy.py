from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class EgressPolicyError(RuntimeError):
    """The resolved destination is outside the configured egress policy."""


async def validate_resolved_egress(url: str, cidrs: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve immediately before connect and require every answer in approved CIDRs."""
    if not cidrs:
        return ()
    parsed = urlparse(url)
    if not parsed.hostname:
        raise EgressPolicyError("destination hostname is missing")
    try:
        networks = tuple(ipaddress.ip_network(item, strict=False) for item in cidrs)
    except ValueError:
        raise EgressPolicyError("egress policy is invalid") from None
    try:
        answers = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError:
        raise EgressPolicyError("destination resolution failed") from None
    addresses = tuple(sorted({item[4][0] for item in answers}))
    if not addresses:
        raise EgressPolicyError("destination resolution returned no addresses")
    try:
        parsed_addresses = tuple(ipaddress.ip_address(item) for item in addresses)
    except ValueError:
        raise EgressPolicyError("destination resolution returned an invalid address") from None
    if any(not any(address in network for network in networks) for address in parsed_addresses):
        raise EgressPolicyError("destination is outside the egress policy")
    return addresses
