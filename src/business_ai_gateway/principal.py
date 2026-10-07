from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    client_id: str
    scopes: frozenset[str]
    groups: frozenset[str]
    claims: dict[str, Any]


def claim_groups(claims: dict[str, Any]) -> frozenset[str]:
    distributed = claims.get("_claim_names")
    if (isinstance(distributed, dict) and "groups" in distributed) or claims.get("hasgroups"):
        raise PermissionError("group membership is incomplete")
    raw = claims.get("groups")
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        raw = [raw] if raw else []
    if not isinstance(raw, list) or len(raw) > 2048 or any(
        not isinstance(value, str) or not value or len(value) > 512 for value in raw
    ):
        raise PermissionError("invalid group membership claim")
    return frozenset(raw)


def current_principal(*, oauth_enabled: bool) -> Principal:
    token = get_access_token()
    if token is None:
        if oauth_enabled:
            raise PermissionError("authenticated MCP request required")
        return Principal(
            subject="development-local",
            client_id="development",
            scopes=frozenset({"onec:read"}),
            groups=frozenset({"development"}),
            claims={},
        )
    claims = token.claims or {}
    subject = token.subject or claims.get("sub")
    if not subject:
        raise PermissionError("token has no subject")
    return Principal(
        subject=str(subject),
        client_id=token.client_id,
        scopes=frozenset(token.scopes),
        groups=claim_groups(claims),
        claims=claims,
    )
