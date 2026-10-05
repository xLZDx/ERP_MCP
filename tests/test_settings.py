import pytest
from pydantic import ValidationError

from business_ai_gateway.settings import Settings


def test_production_refuses_insecure_profile():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            public_mcp_url="http://localhost:8000/mcp",
            oauth_enabled=False,
            secret_provider="env",
        )


def test_production_refuses_mismatched_resource_audience():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            public_mcp_url="https://mcp.example.com/mcp",
            oauth_enabled=True,
            oauth_issuer="https://id.example.com/",
            oauth_audience="some-other-api",
            oauth_jwks_url="https://id.example.com/jwks",
            secret_provider="file",
            database_url="postgresql://u:p@db/x",
            redis_url="redis://redis/0",
        )


def test_production_accepts_required_security_shape():
    settings = Settings(
        environment="production",
        public_mcp_url="https://mcp.example.com/mcp",
        oauth_enabled=True,
        oauth_issuer="https://id.example.com/",
        oauth_audience="https://mcp.example.com/mcp",
        oauth_jwks_url="https://id.example.com/jwks",
        secret_provider="file",
        database_url="postgresql://u:p@db/x",
        redis_url="redis://redis/0",
    )
    assert settings.environment == "production"
