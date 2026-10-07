from __future__ import annotations

import asyncio
from pathlib import Path

from redis.asyncio import Redis

from .adapters.onec.adapter import OneCAdapter
from .adapters.onec.client import OneCReadClient
from .adapters.onec.rsv_bridge import RSVDataBridgeClient
from .adapters.onec.sidecar_client import ODataSidecarClient
from .analytics_balance import ComBinding, load_com_bindings
from .audit import Audit
from .business_policy import CapabilityPolicy
from .company_scope import CompanyScopeResolver
from .db import Database
from .evidence_index import ApprovedEvidenceProvider
from .evidence_store import PrivateEvidenceStore
from .fixture_profiles import SyntheticFixtureProfiles
from .observability import OperationalMetrics
from .rate_limit import RateLimiter
from .registry import Registry
from .secrets import build_secret_provider
from .settings import Settings


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.metrics = OperationalMetrics()
        self.db = Database(settings.database_url)
        self.admin_db = (
            Database(settings.admin_control_database_url)
            if settings.admin_control_database_url
            else None
        )
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        self.synthetic_profiles = (
            SyntheticFixtureProfiles(
                settings.synthetic_fixture_profiles_file,
                settings.synthetic_fixture_profiles_sha256,
                environment=settings.environment,
            )
            if settings.synthetic_fixture_profiles_file
            else None
        )
        self.registry = Registry(
            self.db,
            production=settings.environment == "production",
            allowed_source_hosts=settings.source_host_allowlist_items,
            synthetic_profiles=self.synthetic_profiles,
        )
        self.secrets = build_secret_provider(settings)
        self.audit = Audit(
            self.db, include_query=settings.audit_include_query, metrics=self.metrics
        )
        self.capability_policy = CapabilityPolicy(
            self.db,
            enabled=settings.business_capability_enforcement_enabled,
        )
        self.company_scope = CompanyScopeResolver(self.db)
        self.rate_limit = RateLimiter(self.redis, per_minute=settings.rate_limit_per_minute)
        self.evidence_provider = (
            ApprovedEvidenceProvider(PrivateEvidenceStore(Path(settings.evidence_store_root)),
                Path(settings.evidence_approval_index), settings.evidence_approval_sha256)
            if settings.evidence_store_root else None
        )
        self.onec_client = OneCReadClient(
            timeout_seconds=settings.http_timeout_seconds,
            max_response_bytes=settings.max_response_bytes,
            allowed_egress_cidrs=settings.source_egress_cidr_items,
        )
        self.odata_sidecar = (
            ODataSidecarClient(
                base_url=settings.odata_sidecar_url,
                token=settings.odata_sidecar_token.get_secret_value(),
                timeout_seconds=settings.http_timeout_seconds,
                max_response_bytes=settings.max_response_bytes,
                max_rows=settings.max_rows,
                allowed_egress_cidrs=settings.sidecar_egress_cidr_items,
            )
            if settings.odata_sidecar_url and settings.odata_sidecar_token
            else None
        )
        self.rsv_bridge = (
            RSVDataBridgeClient(
                executable=settings.rsv_bridge_executable,
                config_root=settings.rsv_bridge_config_root,
                timeout_seconds=settings.http_timeout_seconds,
                expected_executable_sha256=settings.rsv_bridge_executable_sha256,
                config_secret_loader=self.secrets.get if settings.rsv_bridge_config_secret_ref else None,
                config_secret_ref=settings.rsv_bridge_config_secret_ref,
            )
            if settings.rsv_bridge_executable and settings.rsv_bridge_config_root
            else None
        )
        self.onec = OneCAdapter(
            settings, self.secrets, self.onec_client, self.odata_sidecar, self.rsv_bridge
        )
        self._started = False
        self._lock = asyncio.Lock()
        self._com_client = None

    def com_bindings(self) -> tuple[ComBinding, ...]:
        """Operator-pinned COM bindings; absent settings mean no COM route (never an import error)."""
        if not self.settings.com_bindings_file:
            return ()
        return load_com_bindings(
            Path(self.settings.com_bindings_file), self.settings.com_bindings_sha256 or ""
        )

    async def com_client(self):
        """Lazy COM bridge client factory; None when the bridge is not configured."""
        if not (self.settings.com_bridge_url and self.settings.com_bridge_token_secret_ref):
            return None
        if self._com_client is None:
            from .adapters.onec.com_bridge_client import ComBridgeClient  # lazy: optional route

            token = await self.secrets.get(self.settings.com_bridge_token_secret_ref)
            self._com_client = ComBridgeClient(
                base_url=self.settings.com_bridge_url,
                token=token,
                timeout_seconds=self.settings.http_timeout_seconds,
                max_response_bytes=self.settings.max_response_bytes,
            )
        return self._com_client

    async def start(self):
        if self._started:
            return
        async with self._lock:
            if self._started:
                return
            await self.db.start()
            await self.db.assert_schema()
            if self.settings.environment == "production":
                await self.db.assert_runtime_role()
            if self.admin_db is not None:
                await self.admin_db.start()
                await self.admin_db.assert_schema()
                if self.settings.environment == "production":
                    await self.admin_db.assert_control_api_role()
            if self.settings.admin_mutations_enabled and self.admin_db is None:
                raise RuntimeError("admin mutation database is not configured")
            if not await self.redis.ping():
                raise RuntimeError("redis unavailable")
            self._started = True

    async def ready(self) -> bool:
        await self.start()
        admin_ready = self.admin_db is None or await self.admin_db.ping()
        return await self.db.ping() and admin_ready and bool(await self.redis.ping())

    async def close(self):
        await self.onec_client.close()
        if self._com_client is not None and hasattr(self._com_client, "close"):
            await self._com_client.close()
        if self.odata_sidecar is not None:
            await self.odata_sidecar.close()
        await self.redis.aclose()
        if self.admin_db is not None:
            await self.admin_db.close()
        await self.db.close()
        self._started = False
