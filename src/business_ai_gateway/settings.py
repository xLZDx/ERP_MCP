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
    oauth_additional_audiences: str = ""
    oauth_required_scope: str = "onec:read"
    oauth_jwks_url: str | None = None
    oauth_algorithms: str = "RS256"
    oauth_jwks_timeout_seconds: float = Field(default=3.0, gt=0, le=10)
    oauth_jwks_cache_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    oauth_jwks_refresh_cooldown_seconds: float = Field(default=1.0, ge=0, le=30)

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
    admin_step_up_acr_values: str = ""
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

    # Optional COM route for balance-by-analytics (ADR-0008). Absent settings mean "no COM route".
    com_bindings_file: str | None = Field(default=None, repr=False, max_length=1024)
    com_bindings_sha256: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    com_bridge_url: str | None = None
    com_bridge_token_secret_ref: str | None = None

    # Test-only reviewed synthetic fixture profiles (hard-denied in production; see
    # fixture_profiles.py). Never a native reconciliation substitute.
    synthetic_fixture_profiles_file: str | None = Field(default=None, repr=False, max_length=1024)
    synthetic_fixture_profiles_sha256: str | None = Field(
        default=None, pattern=r'^[a-f0-9]{64}$'
    )

    # Test-only allow-list of source ids whose profile may be validated by labelled machine two-source
    # reconciliation (evidence_basis.py). Hard-denied outside the test environment; never native proof.
    machine_reconciled_sources: str = ""

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
    def oauth_audience_list(self) -> tuple[str, ...]:
        values = [self.oauth_audience] if self.oauth_audience else []
        values.extend(
            item.strip()
            for item in self.oauth_additional_audiences.split(",")
            if item.strip()
        )
        return tuple(dict.fromkeys(values))

    @property
    def source_host_allowlist_items(self) -> tuple[str, ...]:
        if not self.source_host_allowlist:
            return ()
        return tuple(
            host.strip().rstrip(".").lower()
            for host in self.source_host_allowlist.split(",")
            if host.strip()
        )

    @property
    def machine_reconciled_source_items(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                item.strip()
                for item in self.machine_reconciled_sources.split(",")
                if item.strip()
            )
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
        if self.machine_reconciled_source_items:
            if self.environment != "test":
                raise ValueError("MACHINE_RECONCILED_SOURCES_REQUIRE_TEST_ENVIRONMENT")
            if any(
                not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", item)
                for item in self.machine_reconciled_source_items
            ):
                raise ValueError("MACHINE_RECONCILED_SOURCES_INVALID")
        if self.synthetic_fixture_profiles_file or self.synthetic_fixture_profiles_sha256:
            if self.environment == "production":
                raise ValueError("SYNTHETIC_FIXTURE_PROFILES_FORBIDDEN_IN_PRODUCTION")
            if not (
                self.synthetic_fixture_profiles_file and self.synthetic_fixture_profiles_sha256
            ):
                raise ValueError("SYNTHETIC_FIXTURE_PROFILES_SETTINGS_INCOMPLETE")
            if self.environment != "test":
                raise ValueError("SYNTHETIC_FIXTURE_PROFILES_REQUIRE_TEST_ENVIRONMENT")
            if not Path(self.synthetic_fixture_profiles_file).is_absolute():
                raise ValueError("SYNTHETIC_FIXTURE_PROFILES_SETTINGS_INVALID")
        evidence_settings = (self.evidence_store_root, self.evidence_approval_index, self.evidence_approval_sha256)
        if any(evidence_settings) and not all(evidence_settings):
            raise ValueError('EVIDENCE_PROVIDER_SETTINGS_INCOMPLETE')
        if self.evidence_store_root and not all(Path(value).is_absolute() for value in evidence_settings[:2]):
            raise ValueError('EVIDENCE_PROVIDER_SETTINGS_INVALID')
        if bool(self.com_bindings_file) != bool(self.com_bindings_sha256):
            raise ValueError("COM_BINDINGS_SETTINGS_INCOMPLETE")
        if self.com_bindings_file and not Path(self.com_bindings_file).is_absolute():
            raise ValueError("COM_BINDINGS_SETTINGS_INVALID")
        if bool(self.com_bridge_url) != bool(self.com_bridge_token_secret_ref):
            raise ValueError("COM_BRIDGE_SETTINGS_INCOMPLETE")
        if self.com_bridge_url:
            parsed_bridge = urlparse(self.com_bridge_url)
            if (
                parsed_bridge.scheme != "http"
                or parsed_bridge.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed_bridge.username or parsed_bridge.password
                or parsed_bridge.query or parsed_bridge.fragment
            ):
                raise ValueError("COM_BRIDGE_URL_MUST_BE_LOOPBACK_HTTP")
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

        if self.admin_api_enabled:
            if not self.oauth_enabled:
                raise ValueError("admin API requires BAG_OAUTH_ENABLED=true")
            if not self.admin_oauth_audience:
                raise ValueError("admin API requires BAG_ADMIN_OAUTH_AUDIENCE")
            if len(self.admin_oauth_required_scope.split()) != 1:
                raise ValueError("admin API requires one nonempty admin scope")
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
