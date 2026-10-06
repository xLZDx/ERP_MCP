from __future__ import annotations

from enum import StrEnum
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SecretProviderKind(StrEnum):
    ENV = "env"
    FILE = "file"
    GCP = "gcp"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    public_mcp_url: str = "http://127.0.0.1:8000/mcp"

    oauth_enabled: bool = False
    oauth_issuer: str | None = None
    oauth_audience: str | None = None
    oauth_required_scope: str = "onec:read"
    oauth_jwks_url: str | None = None
    oauth_algorithms: str = "RS256"

    admin_api_enabled: bool = False
    admin_mutations_enabled: bool = False
    admin_ui_enabled: bool = False
    admin_oauth_audience: str | None = None
    admin_oauth_required_scope: str = "erp_mcp:admin"
    admin_oidc_authorization_url: str | None = None
    admin_oidc_token_url: str | None = None
    admin_oidc_client_id: str | None = None
    admin_oidc_client_secret: SecretStr | None = None
    admin_oidc_redirect_uri: str | None = None
    admin_session_ttl_seconds: int = Field(default=28800, ge=300, le=86400)
    admin_control_database_url: str | None = None
    admin_source_allowed_hosts: str = ""
    admin_source_allowed_cidrs: str = ""
    business_capability_enforcement_enabled: bool = False

    database_url: str = "postgresql://business_ai:business_ai@localhost:5432/business_ai"
    admin_database_url: str | None = None
    migration_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    odata_sidecar_url: str | None = None
    odata_sidecar_token: SecretStr | None = None

    secret_provider: SecretProviderKind = SecretProviderKind.ENV
    secret_file_root: str = "/run/secrets"
    gcp_project_id: str | None = None

    max_rows: int = Field(default=200, ge=1, le=10_000)
    max_response_bytes: int = Field(default=5_000_000, ge=10_000, le=100_000_000)
    http_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    max_filter_chars: int = Field(default=4000, ge=64, le=20_000)
    require_metadata_entity: bool = True
    rate_limit_per_minute: int = Field(default=120, ge=1, le=10_000)
    audit_include_query: bool = False

    @property
    def oauth_algorithm_list(self) -> list[str]:
        return [x.strip() for x in self.oauth_algorithms.split(",") if x.strip()]

    @model_validator(mode="after")
    def production_guards(self):
        if (self.odata_sidecar_url is None) != (self.odata_sidecar_token is None):
            raise ValueError(
                "BAG_ODATA_SIDECAR_URL and BAG_ODATA_SIDECAR_TOKEN must be configured together"
            )
        if self.odata_sidecar_url:
            parsed = urlparse(self.odata_sidecar_url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError("BAG_ODATA_SIDECAR_URL must be an absolute HTTP(S) URL")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError(
                    "BAG_ODATA_SIDECAR_URL must not contain credentials/query/fragment"
                )
            if len(self.odata_sidecar_token.get_secret_value().encode()) < 32:
                raise ValueError("BAG_ODATA_SIDECAR_TOKEN must contain at least 32 bytes")
            if self.environment == "production" and parsed.scheme != "https":
                raise ValueError("production BAG_ODATA_SIDECAR_URL must use https://")

        if self.admin_api_enabled:
            if not self.oauth_enabled:
                raise ValueError("admin API requires BAG_OAUTH_ENABLED=true")
            if not self.admin_oauth_audience:
                raise ValueError("admin API requires BAG_ADMIN_OAUTH_AUDIENCE")
            if self.admin_oauth_audience == self.oauth_audience:
                raise ValueError("admin API audience must differ from MCP OAuth audience")
            if self.admin_oauth_required_scope == self.oauth_required_scope:
                raise ValueError("admin API scope must differ from MCP OAuth scope")
        if self.admin_mutations_enabled:
            if not self.admin_api_enabled:
                raise ValueError("admin mutations require BAG_ADMIN_API_ENABLED=true")
            if not self.admin_control_database_url:
                raise ValueError("admin mutations require BAG_ADMIN_CONTROL_DATABASE_URL")
            if self.environment == "production" and not self.admin_source_allowed_hosts.strip():
                raise ValueError("production admin mutations require BAG_ADMIN_SOURCE_ALLOWED_HOSTS")
        if self.admin_ui_enabled:
            if not self.admin_api_enabled:
                raise ValueError("admin UI requires BAG_ADMIN_API_ENABLED=true")
            ui_required = {
                "BAG_ADMIN_OIDC_AUTHORIZATION_URL": self.admin_oidc_authorization_url,
                "BAG_ADMIN_OIDC_TOKEN_URL": self.admin_oidc_token_url,
                "BAG_ADMIN_OIDC_CLIENT_ID": self.admin_oidc_client_id,
                "BAG_ADMIN_OIDC_REDIRECT_URI": self.admin_oidc_redirect_uri,
            }
            missing_ui = [name for name, value in ui_required.items() if not value]
            if missing_ui:
                raise ValueError(
                    f"admin UI missing OIDC settings: {', '.join(missing_ui)}"
                )
            for name, value in (
                ("BAG_ADMIN_OIDC_AUTHORIZATION_URL", self.admin_oidc_authorization_url),
                ("BAG_ADMIN_OIDC_TOKEN_URL", self.admin_oidc_token_url),
                ("BAG_ADMIN_OIDC_REDIRECT_URI", self.admin_oidc_redirect_uri),
            ):
                parsed = urlparse(value or "")
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise ValueError(f"{name} must be an absolute HTTP(S) URL")
                if self.environment == "production" and parsed.scheme != "https":
                    raise ValueError(f"production {name} must use https://")

        if self.environment != "production":
            return self
        if not self.oauth_enabled:
            raise ValueError("production requires BAG_OAUTH_ENABLED=true")
        required = {
            "BAG_OAUTH_ISSUER": self.oauth_issuer,
            "BAG_OAUTH_AUDIENCE": self.oauth_audience,
            "BAG_OAUTH_JWKS_URL": self.oauth_jwks_url,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"production missing OAuth settings: {', '.join(missing)}")
        if not self.public_mcp_url.startswith("https://"):
            raise ValueError("production BAG_PUBLIC_MCP_URL must use https://")
        if self.oauth_issuer and not self.oauth_issuer.startswith("https://"):
            raise ValueError("production BAG_OAUTH_ISSUER must use https://")
        if self.oauth_jwks_url and not self.oauth_jwks_url.startswith("https://"):
            raise ValueError("production BAG_OAUTH_JWKS_URL must use https://")
        if self.oauth_audience != self.public_mcp_url:
            raise ValueError("production requires BAG_OAUTH_AUDIENCE == BAG_PUBLIC_MCP_URL")
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("production requires PostgreSQL BAG_DATABASE_URL")
        if not self.redis_url.startswith(("redis://", "rediss://")):
            raise ValueError("production requires Redis BAG_REDIS_URL")
        if self.secret_provider == SecretProviderKind.ENV:
            raise ValueError("production forbids BAG_SECRET_PROVIDER=env")
        if self.secret_provider == SecretProviderKind.GCP and not self.gcp_project_id:
            raise ValueError("gcp secret provider requires BAG_GCP_PROJECT_ID")
        return self
