from __future__ import annotations

import ipaddress
import re
from enum import StrEnum
from pathlib import Path
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
        hide_input_in_errors=True,
    )

    environment: Literal["development", "test", "production"] = "development"
    public_mcp_url: str = "http://127.0.0.1:8000/mcp"

    oauth_enabled: bool = False
    oauth_issuer: str | None = None
    oauth_audience: str | None = None
    oauth_required_scope: str = "onec:read"
    oauth_jwks_url: str | None = None
    oauth_algorithms: str = "RS256"
    oauth_jwks_timeout_seconds: float = Field(default=3.0, gt=0, le=10)
    oauth_jwks_cache_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    oauth_jwks_refresh_cooldown_seconds: float = Field(default=1.0, ge=0, le=30)

    database_url: str = "postgresql://business_ai:business_ai@localhost:5432/business_ai"
    admin_database_url: str | None = None
    migration_database_url: str | None = None
    redis_url: str = "redis://localhost:6379/0"

    odata_sidecar_url: str | None = None
    odata_sidecar_token: SecretStr | None = None
    source_host_allowlist: str | None = None
    source_egress_cidrs: str | None = None
    sidecar_egress_cidrs: str | None = None
    metrics_token: SecretStr | None = None
    rsv_bridge_executable: str | None = None
    rsv_bridge_executable_sha256: str | None = None
    rsv_bridge_config_root: str | None = None
    rsv_bridge_config_secret_ref: str | None = None
    evidence_store_root: str | None = Field(default=None, repr=False, max_length=1024)
    evidence_approval_index: str | None = Field(default=None, repr=False, max_length=1024)
    evidence_approval_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')

    secret_provider: SecretProviderKind = SecretProviderKind.ENV
    secret_file_root: str = "/run/secrets"
    gcp_project_id: str | None = None

    max_rows: int = Field(default=200, ge=1, le=10_000)
    max_response_bytes: int = Field(default=5_000_000, ge=10_000, le=100_000_000)
    http_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    metadata_cache_ttl_seconds: float = Field(default=60.0, gt=0, le=3600)
    max_filter_chars: int = Field(default=4000, ge=64, le=20_000)
    require_metadata_entity: bool = True
    rate_limit_per_minute: int = Field(default=120, ge=1, le=10_000)
    audit_include_query: bool = False

    @property
    def oauth_algorithm_list(self) -> list[str]:
        return [x.strip() for x in self.oauth_algorithms.split(",") if x.strip()]

    @property
    def source_host_allowlist_items(self) -> tuple[str, ...]:
        if not self.source_host_allowlist:
            return ()
        return tuple(
            host.strip().rstrip(".").lower()
            for host in self.source_host_allowlist.split(",")
            if host.strip()
        )

    @staticmethod
    def _cidr_items(value: str | None) -> tuple[str, ...]:
        return tuple(item.strip() for item in (value or "").split(",") if item.strip())

    @property
    def source_egress_cidr_items(self) -> tuple[str, ...]:
        return self._cidr_items(self.source_egress_cidrs)

    @property
    def sidecar_egress_cidr_items(self) -> tuple[str, ...]:
        return self._cidr_items(self.sidecar_egress_cidrs)

    @model_validator(mode="after")
    def production_guards(self):
        evidence_settings = (self.evidence_store_root, self.evidence_approval_index, self.evidence_approval_sha256)
        if any(evidence_settings) and not all(evidence_settings):
            raise ValueError('EVIDENCE_PROVIDER_SETTINGS_INCOMPLETE')
        if self.evidence_store_root and not all(Path(value).is_absolute() for value in evidence_settings[:2]):
            raise ValueError('EVIDENCE_PROVIDER_SETTINGS_INVALID')
        if self.metrics_token and len(self.metrics_token.get_secret_value().encode()) < 32:
            raise ValueError("BAG_METRICS_TOKEN must contain at least 32 bytes")
        if (self.rsv_bridge_executable is None) != (self.rsv_bridge_config_root is None):
            raise ValueError(
                "BAG_RSV_BRIDGE_EXECUTABLE and BAG_RSV_BRIDGE_CONFIG_ROOT "
                "must be configured together"
            )
        if self.rsv_bridge_executable_sha256 and self.rsv_bridge_executable is None:
            raise ValueError("BAG_RSV_BRIDGE_EXECUTABLE_SHA256 requires the bridge executable")
        if self.rsv_bridge_config_secret_ref and not self.rsv_bridge_executable:
            raise ValueError("BAG_RSV_BRIDGE_CONFIG_SECRET_REF requires the bridge executable")
        if self.rsv_bridge_executable_sha256 and not re.fullmatch(
            r"[0-9a-fA-F]{64}", self.rsv_bridge_executable_sha256
        ):
            raise ValueError("BAG_RSV_BRIDGE_EXECUTABLE_SHA256 must be a SHA-256 hex digest")
        if self.rsv_bridge_executable:
            executable = Path(self.rsv_bridge_executable)
            config_root = Path(self.rsv_bridge_config_root)
            if not executable.is_absolute() or not config_root.is_absolute():
                raise ValueError("RSV bridge executable and config root must be absolute paths")
            if self.environment == "production" and not self.rsv_bridge_executable_sha256:
                raise ValueError("production requires BAG_RSV_BRIDGE_EXECUTABLE_SHA256")
            if self.environment == "production" and not self.rsv_bridge_config_secret_ref:
                raise ValueError("production requires BAG_RSV_BRIDGE_CONFIG_SECRET_REF")
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
        if self.environment != "production":
            return self
        if not self.source_host_allowlist_items:
            raise ValueError("production requires BAG_SOURCE_HOST_ALLOWLIST")
        for host in self.source_host_allowlist_items:
            parsed_host = urlparse(f"//{host}")
            if (
                not parsed_host.hostname
                or parsed_host.port is not None
                or parsed_host.hostname.rstrip(".").lower() != host
                or "*" in host
            ):
                raise ValueError("BAG_SOURCE_HOST_ALLOWLIST must contain exact hostnames only")
        if not self.source_egress_cidr_items:
            raise ValueError("production requires BAG_SOURCE_EGRESS_CIDRS")
        if self.odata_sidecar_url and not self.sidecar_egress_cidr_items:
            raise ValueError("production requires BAG_SIDECAR_EGRESS_CIDRS")
        for cidr in (*self.source_egress_cidr_items, *self.sidecar_egress_cidr_items):
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                raise ValueError("egress CIDR must be a valid IP network") from None
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
