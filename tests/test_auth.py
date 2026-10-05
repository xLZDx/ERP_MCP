from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

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


@pytest.fixture
def auth_setup():
    private_key, public_key = make_keypair()
    settings = Settings(
        oauth_enabled=True,
        oauth_issuer="https://identity.example.test/",
        oauth_audience="https://mcp.example.test/mcp",
        oauth_jwks_url="https://identity.example.test/jwks",
        oauth_required_scope="onec:read",
    )
    verifier = JWTTokenVerifier(settings)
    verifier._jwks = FixedJWKS(public_key)
    return verifier, private_key


def token_for(private_key, **overrides):
    now = int(time.time())
    claims = {
        "iss": "https://identity.example.test/",
        "aud": "https://mcp.example.test/mcp",
        "sub": "subject-42",
        "iat": now,
        "exp": now + 120,
        "scope": "onec:read profile",
        "azp": "mcp-client-7",
        "groups": ["finance", "operators"],
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


def test_valid_token_resolves_subject_client_scope_and_groups(auth_setup):
    verifier, private_key = auth_setup

    result = verifier._verify_sync(token_for(private_key))

    assert result is not None
    assert result.subject == "subject-42"
    assert result.client_id == "mcp-client-7"
    assert set(result.scopes) == {"onec:read", "profile"}
    assert result.claims["groups"] == ["finance", "operators"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://wrong.example.test/"},
        {"aud": "https://wrong.example.test/mcp"},
        {"exp": int(time.time()) - 30},
        {"scope": "profile"},
        {"sub": ""},
        {"iat": None},
    ],
    ids=["issuer", "audience", "expired", "scope", "subject", "issued-at"],
)
def test_invalid_or_under_scoped_tokens_are_denied(auth_setup, overrides):
    verifier, private_key = auth_setup

    result = verifier._verify_sync(token_for(private_key, **overrides))

    assert result is None


def test_bad_signature_is_denied(auth_setup):
    verifier, _private_key = auth_setup
    attacker_key, _attacker_public = make_keypair()

    assert verifier._verify_sync(token_for(attacker_key)) is None


def test_jwks_validation_error_fails_closed(auth_setup):
    verifier, private_key = auth_setup

    class FailedJWKS:
        def get_signing_key_from_jwt(self, _token):
            raise jwt.PyJWKClientError("JWKS unavailable")

    verifier._jwks = FailedJWKS()

    assert verifier._verify_sync(token_for(private_key)) is None
