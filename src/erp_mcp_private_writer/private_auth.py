"""Fail-closed caller authentication primitives for a future private writer ingress.

This module does not create a listener or authorize a COM/database operation. The caller must
compose a verifier configured for the private writer audience and pass an explicit client allowlist.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from mcp.server.auth.provider import AccessToken

from business_ai_gateway.auth import JWTTokenVerifier
from business_ai_gateway.settings import Settings

from .dependency_shape import has_static_callable_method

PRIVATE_WRITER_AUDIENCE = "urn:erp-mcp:private-writer"
PRIVATE_WRITER_SCOPE = "erp_mcp:private_writer"
_BEARER_JWT = re.compile(
    r"Bearer ([A-Za-z0-9_-]{1,8192}\.[A-Za-z0-9_-]{1,8192}\.[A-Za-z0-9_-]{1,8192})\Z"
)
_MAX_AUTHORIZATION_HEADER_CHARS = len("Bearer ") + 3 * 8192 + 2
_MAX_VERIFICATION_TIMEOUT_SECONDS = 10.0


class TokenVerifier(Protocol):
    async def verify_token(self, token: str) -> AccessToken | None: ...


class PrivateWriterAuthenticationError(PermissionError):
    """Stable authentication refusal that never includes credentials or verifier details."""

    def __init__(self, code: str) -> None:
        if code not in {"UNAUTHORIZED", "AUTHENTICATION_UNAVAILABLE"}:
            code = "UNAUTHORIZED"
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PrivateWriterCaller:
    """Authenticated request identity safe to use for audit correlation."""

    subject: str
    client_id: str
    scopes: frozenset[str]


class PrivateWriterAuthenticator:
    """Require a verified JWT, the private audience/scope, and an exact client allowlist."""

    __slots__ = ("_allowed_client_ids", "_verification_timeout_seconds", "_verifier")

    def __init__(
        self,
        verifier: TokenVerifier,
        *,
        allowed_client_ids: frozenset[str],
        verification_timeout_seconds: float = 5.0,
    ) -> None:
        if not has_static_callable_method(verifier, "verify_token"):
            raise ValueError("TOKEN_VERIFIER_REQUIRED")
        if (
            type(allowed_client_ids) is not frozenset
            or not allowed_client_ids
            or any(not self._valid_identity_value(value) for value in allowed_client_ids)
        ):
            raise ValueError("WRITER_CLIENT_ALLOWLIST_REQUIRED")
        if (
            isinstance(verification_timeout_seconds, bool)
            or not isinstance(verification_timeout_seconds, (int, float))
            or not 0 < verification_timeout_seconds <= _MAX_VERIFICATION_TIMEOUT_SECONDS
            or not math.isfinite(verification_timeout_seconds)
        ):
            raise ValueError("WRITER_AUTHENTICATION_TIMEOUT_INVALID")
        self._verifier = verifier
        self._allowed_client_ids = allowed_client_ids
        self._verification_timeout_seconds = float(verification_timeout_seconds)

    def __setattr__(self, name: str, value: object) -> None:
        if hasattr(self, name):
            raise AttributeError("WRITER_AUTHENTICATOR_CONFIGURATION_IMMUTABLE")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError("WRITER_AUTHENTICATOR_CONFIGURATION_IMMUTABLE")

    @staticmethod
    def _valid_identity_value(value: object) -> bool:
        return (
            type(value) is str
            and bool(value)
            and value == value.strip()
            and len(value) <= 512
            and all(unicodedata.category(character) != "Cc" for character in value)
        )

    @staticmethod
    def _authorization_value(values: Sequence[str | bytes]) -> str:
        if type(values) not in (list, tuple) or len(values) != 1:
            raise PrivateWriterAuthenticationError("UNAUTHORIZED")
        value = values[0]
        if type(value) is bytes:
            if len(value) > _MAX_AUTHORIZATION_HEADER_CHARS:
                raise PrivateWriterAuthenticationError("UNAUTHORIZED")
            try:
                value = value.decode("ascii")
            except UnicodeDecodeError:
                raise PrivateWriterAuthenticationError("UNAUTHORIZED") from None
        if type(value) is not str or len(value) > _MAX_AUTHORIZATION_HEADER_CHARS:
            raise PrivateWriterAuthenticationError("UNAUTHORIZED")
        match = _BEARER_JWT.fullmatch(value)
        if match is None:
            raise PrivateWriterAuthenticationError("UNAUTHORIZED")
        return match.group(1)

    @staticmethod
    def _audience_matches(claims: dict[str, Any], expected: str) -> bool:
        raw = claims.get("aud")
        if type(raw) is str:
            return raw == expected
        if type(raw) is list:
            return bool(raw) and all(type(value) is str for value in raw) and expected in raw
        return False

    async def authenticate(self, authorization_values: Sequence[str | bytes]) -> PrivateWriterCaller:
        token = self._authorization_value(authorization_values)
        try:
            async with asyncio.timeout(self._verification_timeout_seconds):
                verified = await self._verifier.verify_token(token)
        except TimeoutError:
            raise PrivateWriterAuthenticationError("AUTHENTICATION_UNAVAILABLE") from None
        except Exception:
            raise PrivateWriterAuthenticationError("AUTHENTICATION_UNAVAILABLE") from None
        if type(verified) is not AccessToken:
            raise PrivateWriterAuthenticationError("UNAUTHORIZED")

        claims = verified.claims
        if type(claims) is not dict or not self._audience_matches(
            claims, PRIVATE_WRITER_AUDIENCE
        ):
            raise PrivateWriterAuthenticationError("UNAUTHORIZED")
        if type(verified.expires_at) is not int or verified.expires_at <= int(time.time()):
            raise PrivateWriterAuthenticationError("UNAUTHORIZED")
        subject = verified.subject
        client_id = verified.client_id
        if (
            not self._valid_identity_value(subject)
            or not self._valid_identity_value(client_id)
            or client_id not in self._allowed_client_ids
        ):
            raise PrivateWriterAuthenticationError("UNAUTHORIZED")
        if type(verified.scopes) is not list or any(
            not self._valid_identity_value(scope) for scope in verified.scopes
        ):
            raise PrivateWriterAuthenticationError("UNAUTHORIZED")
        scopes = frozenset(verified.scopes)
        if PRIVATE_WRITER_SCOPE not in scopes:
            raise PrivateWriterAuthenticationError("UNAUTHORIZED")
        return PrivateWriterCaller(subject=subject, client_id=client_id, scopes=scopes)


def build_private_writer_token_verifier(settings: Settings) -> JWTTokenVerifier:
    """Bind the existing JWT verifier to the private writer's fixed audience and scope."""
    if (
        type(settings) is not Settings
        or not settings.oauth_issuer
        or not settings.oauth_jwks_url
    ):
        raise ValueError("WRITER_OAUTH_CONFIGURATION_REQUIRED")
    return JWTTokenVerifier(
        settings,
        audience=PRIVATE_WRITER_AUDIENCE,
        required_scope=PRIVATE_WRITER_SCOPE,
        resource=PRIVATE_WRITER_AUDIENCE,
    )


__all__ = [
    "PRIVATE_WRITER_AUDIENCE",
    "PRIVATE_WRITER_SCOPE",
    "PrivateWriterAuthenticationError",
    "PrivateWriterAuthenticator",
    "PrivateWriterCaller",
    "TokenVerifier",
    "build_private_writer_token_verifier",
]
