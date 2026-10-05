from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator
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

    database_url: str = "postgresql://business_ai:business_ai@localhost:5432/business_ai"
    admin_database_url: str | None = None
    migration_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"

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
            raise ValueError(
                "production requires BAG_OAUTH_AUDIENCE == BAG_PUBLIC_MCP_URL"
            )
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("production requires PostgreSQL BAG_DATABASE_URL")
        if not self.redis_url.startswith(("redis://", "rediss://")):
            raise ValueError("production requires Redis BAG_REDIS_URL")
        if self.secret_provider == SecretProviderKind.ENV:
            raise ValueError("production forbids BAG_SECRET_PROVIDER=env")
        if self.secret_provider == SecretProviderKind.GCP and not self.gcp_project_id:
            raise ValueError("gcp secret provider requires BAG_GCP_PROJECT_ID")
        return self
