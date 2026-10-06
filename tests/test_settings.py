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


def test_sidecar_settings_require_paired_url_and_long_secret():
    with pytest.raises(ValidationError, match="configured together"):
        Settings(odata_sidecar_url="http://odata-sidecar:8765")
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(odata_sidecar_url="http://odata-sidecar:8765", odata_sidecar_token="short")


def test_admin_ui_requires_distinct_complete_oidc_configuration():
    with pytest.raises(ValidationError, match="admin UI missing OIDC settings"):
        Settings(
            oauth_enabled=True,
            oauth_issuer="https://id.example.com/",
            oauth_audience="https://mcp.example.com/mcp",
            oauth_jwks_url="https://id.example.com/jwks",
            admin_api_enabled=True,
            admin_ui_enabled=True,
            admin_oauth_audience="https://mcp.example.com/admin",
        )


def test_admin_mutations_require_dedicated_control_database():
    with pytest.raises(ValidationError, match="BAG_ADMIN_CONTROL_DATABASE_URL"):
        Settings(
            oauth_enabled=True,
            oauth_issuer="https://id.example.com/",
            oauth_audience="https://mcp.example.com/mcp",
            oauth_jwks_url="https://id.example.com/jwks",
            admin_api_enabled=True,
            admin_mutations_enabled=True,
            admin_oauth_audience="https://mcp.example.com/admin",
        )


def test_production_admin_ui_accepts_secure_distinct_configuration():
    settings = Settings(
        environment="production",
        public_mcp_url="https://mcp.example.com/mcp",
        oauth_enabled=True,
        oauth_issuer="https://id.example.com/",
        oauth_audience="https://mcp.example.com/mcp",
        oauth_jwks_url="https://id.example.com/jwks",
        secret_provider="file",
        database_url="postgresql://app:p@db/x",
        redis_url="rediss://redis/0",
        admin_api_enabled=True,
        admin_ui_enabled=True,
        admin_mutations_enabled=True,
        admin_oauth_audience="https://mcp.example.com/admin",
        admin_oidc_authorization_url="https://id.example.com/authorize",
        admin_oidc_token_url="https://id.example.com/token",
        admin_oidc_client_id="erp-mcp-admin",
        admin_oidc_redirect_uri="https://mcp.example.com/admin/callback",
        admin_control_database_url="postgresql://control:p@db/x",
        admin_source_allowed_hosts="onec.internal.example",
    )

    assert settings.admin_ui_enabled is True
    assert settings.admin_mutations_enabled is True
