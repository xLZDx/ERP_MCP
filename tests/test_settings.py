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


def test_rsv_bridge_settings_require_paired_absolute_paths(tmp_path):
    with pytest.raises(ValidationError, match="configured together"):
        Settings(rsv_bridge_executable=str(tmp_path / "bridge.exe"))
    with pytest.raises(ValidationError, match="absolute paths"):
        Settings(rsv_bridge_executable="bridge.exe", rsv_bridge_config_root=str(tmp_path))
    with pytest.raises(ValidationError, match="absolute paths"):
        Settings(
            rsv_bridge_executable=str(tmp_path / "bridge.exe"), rsv_bridge_config_root="configs"
        )


def test_metrics_endpoint_token_must_be_long_enough():
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(metrics_token="short")
