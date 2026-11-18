from __future__ import annotations

import asyncio
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp.server.auth.provider import AccessToken

from business_ai_gateway.auth import (
    JWTTokenVerifier,
    PRIVATE_WRITER_AUDIENCE,
    PRIVATE_WRITER_SCOPE,
)
from business_ai_gateway.settings import Settings
from erp_mcp_private_writer.private_auth import (
    PrivateWriterAuthenticationError,
    PrivateWriterAuthenticator,
)


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
        oauth_jwks_timeout_seconds=1.0,
        oauth_jwks_cache_ttl_seconds=300,
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


def test_additional_audience_is_accepted():
    private_key, public_key = make_keypair()
    settings = Settings(
        oauth_enabled=True,
        oauth_issuer="https://identity.example.test/",
        oauth_audience="https://mcp.example.test/mcp",
        oauth_additional_audiences="https://api.openai.com/v1/mcp/tunnel_example",
        oauth_jwks_url="https://identity.example.test/jwks",
        oauth_required_scope="onec:read",
    )
    verifier = JWTTokenVerifier(settings)
    verifier._jwks = FixedJWKS(public_key)

    token = token_for(
        private_key,
        aud="https://api.openai.com/v1/mcp/tunnel_example",
    )
    assert verifier._verify_sync(token) is not None


def test_read_verifier_rejects_private_writer_only_and_mixed_audiences(auth_setup):
    verifier, private_key = auth_setup
    writer_only = token_for(
        private_key,
        aud=PRIVATE_WRITER_AUDIENCE,
        scope=PRIVATE_WRITER_SCOPE,
    )
    mixed = token_for(
        private_key,
        aud=["https://mcp.example.test/mcp", PRIVATE_WRITER_AUDIENCE],
    )

    assert verifier._verify_sync(writer_only) is None
    assert verifier._verify_sync(mixed) is None


@pytest.mark.parametrize(
    "audience,accepted",
    [
        (PRIVATE_WRITER_AUDIENCE, True),
        ([PRIVATE_WRITER_AUDIENCE], True),
        ([PRIVATE_WRITER_AUDIENCE, "https://mcp.example.test/mcp"], False),
    ],
    ids=["writer-string", "writer-singleton-list", "mixed-audience"],
)
def test_private_writer_verifier_accepts_only_its_single_audience(auth_setup, audience, accepted):
    read_verifier, private_key = auth_setup
    settings = Settings(
        oauth_enabled=True,
        oauth_issuer="https://identity.example.test/",
        oauth_audience="https://mcp.example.test/mcp",
        oauth_jwks_url="https://identity.example.test/jwks",
        oauth_required_scope="onec:read",
        oauth_jwks_timeout_seconds=1.0,
        oauth_jwks_cache_ttl_seconds=300,
    )
    verifier = JWTTokenVerifier(
        settings,
        audience=PRIVATE_WRITER_AUDIENCE,
        required_scope=PRIVATE_WRITER_SCOPE,
        resource=PRIVATE_WRITER_AUDIENCE,
        private_writer=True,
    )
    verifier._jwks = FixedJWKS(read_verifier._jwks.key)
    token = token_for(
        private_key,
        aud=audience,
        scope=PRIVATE_WRITER_SCOPE,
    )

    result = verifier._verify_sync(token)

    assert (result is not None) is accepted


def test_private_writer_verifier_rejects_read_scope(auth_setup):
    verifier, private_key = auth_setup
    writer = JWTTokenVerifier(
        verifier.settings,
        audience=PRIVATE_WRITER_AUDIENCE,
        required_scope=PRIVATE_WRITER_SCOPE,
        resource=PRIVATE_WRITER_AUDIENCE,
        private_writer=True,
    )
    writer._jwks = verifier._jwks
    read_scoped_token = token_for(
        private_key,
        aud=PRIVATE_WRITER_AUDIENCE,
        scope="onec:read",
    )

    assert writer._verify_sync(read_scoped_token) is None


@pytest.mark.parametrize(
    "audience,accepted",
    [
        (PRIVATE_WRITER_AUDIENCE, True),
        ([PRIVATE_WRITER_AUDIENCE], True),
        ([PRIVATE_WRITER_AUDIENCE, "https://mcp.example.test/mcp"], False),
    ],
    ids=["writer-string", "writer-singleton-list", "mixed-audience"],
)
def test_private_authenticator_rechecks_injected_verifier_audience(audience, accepted):
    class InjectedVerifier:
        async def verify_token(self, token):
            return AccessToken(
                token=token,
                client_id="writer-client",
                scopes=[PRIVATE_WRITER_SCOPE],
                expires_at=int(time.time()) + 120,
                subject="writer-subject",
                claims={"aud": audience},
            )

    authenticator = PrivateWriterAuthenticator(
        InjectedVerifier(),
        allowed_client_ids=frozenset({"writer-client"}),
    )

    async def authenticate():
        if accepted:
            caller = await authenticator.authenticate(["Bearer a.b.c"])
            assert caller.client_id == "writer-client"
        else:
            with pytest.raises(PrivateWriterAuthenticationError) as raised:
                await authenticator.authenticate(["Bearer a.b.c"])
            assert raised.value.code == "UNAUTHORIZED"

    asyncio.run(authenticate())


def test_private_authenticator_rejects_read_scope_from_injected_verifier():
    class InjectedVerifier:
        async def verify_token(self, token):
            return AccessToken(
                token=token,
                client_id="writer-client",
                scopes=["onec:read"],
                expires_at=int(time.time()) + 120,
                subject="writer-subject",
                claims={"aud": PRIVATE_WRITER_AUDIENCE},
            )

    authenticator = PrivateWriterAuthenticator(
        InjectedVerifier(),
        allowed_client_ids=frozenset({"writer-client"}),
    )

    async def authenticate():
        with pytest.raises(PrivateWriterAuthenticationError) as raised:
            await authenticator.authenticate(["Bearer a.b.c"])
        assert raised.value.code == "UNAUTHORIZED"

    asyncio.run(authenticate())


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


@pytest.mark.parametrize("client_claims", [
    {"azp": None},
    {"azp": "   "},
    {"azp": ["spoofed"]},
    {"azp": {"client": "spoofed"}},
    {"azp": None, "client_id": 123},
])
def test_missing_or_malformed_client_identity_fails_closed(auth_setup, client_claims):
    verifier, private_key = auth_setup
    assert verifier._verify_sync(token_for(private_key, **client_claims)) is None


def test_valid_explicit_client_id_is_accepted(auth_setup):
    verifier, private_key = auth_setup
    result = verifier._verify_sync(token_for(private_key, azp=None, client_id="mcp-client-8"))
    assert result is not None
    assert result.client_id == "mcp-client-8"


def test_legacy_appid_client_claim_remains_accepted(auth_setup):
    verifier, private_key = auth_setup
    token = token_for(private_key, azp=None, appid="trusted-app-client")
    result = verifier._verify_sync(token)
    assert result is not None
    assert result.client_id == "trusted-app-client"


def test_blank_primary_client_identity_does_not_fall_back(auth_setup):
    verifier, private_key = auth_setup
    token = token_for(private_key, client_id="   ", azp="trusted-client")
    assert verifier._verify_sync(token) is None
