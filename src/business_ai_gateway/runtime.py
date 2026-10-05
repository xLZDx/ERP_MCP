from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from .adapters.onec.adapter import OneCAdapter
from .adapters.onec.client import OneCReadClient
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
            self.db, production=settings.environment == "production"
        )
        self.secrets = build_secret_provider(settings)
        self.audit = Audit(self.db, include_query=settings.audit_include_query)
        self.rate_limit = RateLimiter(
            self.redis, per_minute=settings.rate_limit_per_minute
        )
        self.onec_client = OneCReadClient(
            timeout_seconds=settings.http_timeout_seconds,
            max_response_bytes=settings.max_response_bytes,
        )
        self.onec = OneCAdapter(settings, self.secrets, self.onec_client)
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
        await self.redis.aclose()
        await self.db.close()
        self._started = False
