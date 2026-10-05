from __future__ import annotations

import pytest

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
