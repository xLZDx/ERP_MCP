from __future__ import annotations

import asyncio
from typing import Any

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

from .settings import Settings


class JWTTokenVerifier(TokenVerifier):
    def __init__(
        self,
        settings: Settings,
        *,
        audience: str | None = None,
        required_scope: str | None = None,
        resource: str | None = None,
    ):
        if not settings.oauth_jwks_url:
            raise ValueError("oauth_jwks_url required")
        self.settings = settings
        self.audience = settings.oauth_audience if audience is None else audience
        self.required_scope = settings.oauth_required_scope if required_scope is None else required_scope
        self.resource = settings.public_mcp_url if resource is None else resource
        if not self.audience:
            raise ValueError("oauth audience required")
        self._jwks = jwt.PyJWKClient(
            settings.oauth_jwks_url,
            cache_jwk_set=True,
            cache_keys=False,
            # Individual-key LRU caching is deliberately disabled: it has no TTL and
            # would keep removed/rotated keys usable past the bounded JWKS set age.
            lifespan=settings.oauth_jwks_cache_ttl_seconds,
            timeout=settings.oauth_jwks_timeout_seconds,
        )
        # Bound forced refreshes caused by unknown `kid` values to prevent IdP request floods.
        self._jwks.cooldown_duration = settings.oauth_jwks_refresh_cooldown_seconds

    @staticmethod
    def _scopes(claims: dict[str, Any]) -> list[str]:
        raw = claims.get("scope", claims.get("scp", []))
        if isinstance(raw, str):
            return [x for x in raw.split() if x]
        if isinstance(raw, list):
            return [str(x) for x in raw]
        return []

    def _verify_sync(self, token: str) -> AccessToken | None:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=self.settings.oauth_algorithm_list,
                issuer=self.settings.oauth_issuer,
                audience=self.audience,
                options={
                    "require": ["exp", "iat", "iss", "sub", "aud"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
        except jwt.PyJWTError:
            return None

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            return None
        scopes = self._scopes(claims)
        if self.required_scope not in scopes:
            return None
        client_id = (
            claims.get("client_id")
            or claims.get("azp")
            or claims.get("appid")
            or "unknown-client"
        )
        return AccessToken(
            token=token,
            client_id=str(client_id),
            scopes=scopes,
            expires_at=int(claims["exp"]),
            resource=self.resource,
            subject=subject,
            claims=claims,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        return await asyncio.to_thread(self._verify_sync, token)
