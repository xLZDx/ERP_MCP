from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from .adapters.onec.adapter import OneCAdapter
from .adapters.onec.client import OneCReadClient
from .adapters.onec.rsv_bridge import RSVDataBridgeClient
from .adapters.onec.sidecar_client import ODataSidecarClient
from .audit import Audit
from .db import Database
from .rate_limit import RateLimiter
from .registry import Registry
from .secrets import build_secret_provider
from .settings import Settings


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.database_url)
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        self.registry = Registry(
            self.db,
            production=settings.environment == "production",
            allowed_source_hosts=settings.source_host_allowlist_items,
        )
        self.secrets = build_secret_provider(settings)
        self.audit = Audit(self.db, include_query=settings.audit_include_query)
        self.rate_limit = RateLimiter(self.redis, per_minute=settings.rate_limit_per_minute)
        self.onec_client = OneCReadClient(
            timeout_seconds=settings.http_timeout_seconds,
            max_response_bytes=settings.max_response_bytes,
        )
        self.odata_sidecar = (
            ODataSidecarClient(
                base_url=settings.odata_sidecar_url,
                token=settings.odata_sidecar_token.get_secret_value(),
                timeout_seconds=settings.http_timeout_seconds,
                max_response_bytes=settings.max_response_bytes,
                max_rows=settings.max_rows,
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
            )
            if settings.rsv_bridge_executable and settings.rsv_bridge_config_root
            else None
        )
        self.onec = OneCAdapter(
            settings, self.secrets, self.onec_client, self.odata_sidecar, self.rsv_bridge
        )
        self._started = False
        self._lock = asyncio.Lock()

    async def start(self):
        if self._started:
            return
        async with self._lock:
            if self._started:
                return
            await self.db.start()
            await self.db.assert_schema()
            if not await self.redis.ping():
                raise RuntimeError("redis unavailable")
            self._started = True

    async def ready(self) -> bool:
        await self.start()
        return await self.db.ping() and bool(await self.redis.ping())

    async def close(self):
        await self.onec_client.close()
        if self.odata_sidecar is not None:
            await self.odata_sidecar.close()
        await self.redis.aclose()
        await self.db.close()
        self._started = False
