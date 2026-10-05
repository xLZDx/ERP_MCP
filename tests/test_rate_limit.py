from __future__ import annotations

import socket

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from business_ai_gateway.rate_limit import RateLimiter


class BrokenPipeline:
    def incr(self, _key):
        return self

    def expire(self, _key, _seconds):
        return self

    async def execute(self):
        raise ConnectionError("redis unavailable")


class BrokenRedis:
    def pipeline(self, *, transaction):
        assert transaction is True
        return BrokenPipeline()


@pytest.mark.asyncio
async def test_redis_rate_limit_failure_propagates_without_unlimited_fallback():
    limiter = RateLimiter(BrokenRedis(), per_minute=5)

    with pytest.raises(ConnectionError, match="redis unavailable"):
        await limiter.check(subject="subject", source_id="source", tool="onec_read")


@pytest.mark.asyncio
async def test_redis_tcp_outage_fails_closed_with_real_redis_client():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        unused_port = listener.getsockname()[1]

    redis = Redis.from_url(
        f"redis://127.0.0.1:{unused_port}/0",
        socket_connect_timeout=0.25,
        socket_timeout=0.25,
    )
    try:
        limiter = RateLimiter(redis, per_minute=5)

        with pytest.raises((RedisConnectionError, RedisTimeoutError)):
            await limiter.check(
                subject="subject", source_id="source", tool="onec_read"
            )
    finally:
        await redis.aclose()
