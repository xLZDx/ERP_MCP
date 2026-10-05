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
    raw_groups = claims.get("groups") or []
    if isinstance(raw_groups, str):
        raw_groups = [raw_groups]
    subject = token.subject or claims.get("sub")
    if not subject:
        raise PermissionError("token has no subject")
    return Principal(
        subject=str(subject),
        client_id=token.client_id,
        scopes=frozenset(token.scopes),
        groups=frozenset(str(x) for x in raw_groups),
        claims=claims,
    )
