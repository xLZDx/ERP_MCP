from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError

from business_ai_gateway.auth import JWTTokenVerifier
from business_ai_gateway.settings import Settings


class FixedJWKS:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, _token):
        return type("SigningKey", (), {"key": self.key})()


def make_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def admin_settings():
    return Settings(
        oauth_enabled=True,
        oauth_issuer="https://identity.example.test/",
        oauth_audience="https://mcp.example.test/mcp",
        oauth_jwks_url="https://identity.example.test/jwks",
        oauth_required_scope="onec:read",
        admin_api_enabled=True,
        admin_oauth_audience="https://mcp.example.test/admin",
        admin_oauth_required_scope="erp_mcp:admin",
    )


def token_for(private_key, *, audience, scope):
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "https://identity.example.test/",
            "aud": audience,
            "sub": "admin-subject",
            "iat": now,
            "exp": now + 120,
            "scope": scope,
            "azp": "admin-client",
            "groups": ["erp-ops"],
        },
        private_key,
        algorithm="RS256",
    )


def test_admin_verifier_requires_distinct_audience_and_scope():
    private_key, public_key = make_keypair()
    settings = admin_settings()
    verifier = JWTTokenVerifier(
        settings,
        audience=settings.admin_oauth_audience,
        required_scope=settings.admin_oauth_required_scope,
        resource=settings.admin_oauth_audience,
    )
    verifier._jwks = FixedJWKS(public_key)

    valid = verifier._verify_sync(
        token_for(
            private_key,
            audience="https://mcp.example.test/admin",
            scope="erp_mcp:admin profile",
        )
    )
    wrong_audience = verifier._verify_sync(
        token_for(
            private_key,
            audience="https://mcp.example.test/mcp",
            scope="erp_mcp:admin",
        )
    )
    data_plane_only = verifier._verify_sync(
        token_for(
            private_key,
            audience="https://mcp.example.test/admin",
            scope="onec:read",
        )
    )

    assert valid is not None
    assert valid.subject == "admin-subject"
    assert wrong_audience is None
    assert data_plane_only is None


def test_admin_api_cannot_reuse_mcp_audience():
    with pytest.raises(ValidationError, match="admin API audience must differ"):
        Settings(
            oauth_enabled=True,
            oauth_issuer="https://identity.example.test/",
            oauth_audience="https://mcp.example.test/mcp",
            oauth_jwks_url="https://identity.example.test/jwks",
            admin_api_enabled=True,
            admin_oauth_audience="https://mcp.example.test/mcp",
        )


def test_admin_api_cannot_reuse_data_plane_scope():
    with pytest.raises(ValidationError, match="admin API scope must differ"):
        Settings(
            oauth_enabled=True,
            oauth_issuer="https://identity.example.test/",
            oauth_audience="https://mcp.example.test/mcp",
            oauth_jwks_url="https://identity.example.test/jwks",
            admin_api_enabled=True,
            admin_oauth_audience="https://mcp.example.test/admin",
            admin_oauth_required_scope="onec:read",
        )


@pytest.mark.parametrize("failure", ["signature", "issuer", "expiry", "missing_scope", "missing_subject"])
def test_admin_access_token_negative_cryptographic_cases(failure):
    private, public = make_keypair()
    config = admin_settings()
    verifier = JWTTokenVerifier(config, audience=config.admin_oauth_audience,
                                required_scope=config.admin_oauth_required_scope)
    verifier._jwks = FixedJWKS(public)
    raw = token_for(private, audience=config.admin_oauth_audience, scope="erp_mcp:admin")
    claims = jwt.decode(raw, options={"verify_signature": False})
    if failure == "issuer":
        claims["iss"] = "https://untrusted.example.test/"
    elif failure == "expiry":
        claims["exp"] = int(time.time()) - 60
    elif failure == "missing_scope":
        claims["scope"] = "onec:read"
    elif failure == "missing_subject":
        claims.pop("sub")
    signing = make_keypair()[0] if failure == "signature" else private
    assert verifier._verify_sync(jwt.encode(claims, signing, algorithm="RS256")) is None
