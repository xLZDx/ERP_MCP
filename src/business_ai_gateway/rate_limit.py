from __future__ import annotations

import time

from redis.asyncio import Redis


class RateLimitExceeded(RuntimeError):
    pass


class RateLimiter:
    def __init__(self, redis: Redis, *, per_minute: int):
        self.redis = redis
        self.per_minute = per_minute

    async def check(self, *, subject: str, source_id: str, tool: str):
        minute = int(time.time() // 60)
        key = f"bag:rl:{subject}:{source_id}:{tool}:{minute}"
        pipe = self.redis.pipeline(transaction=True)
        pipe.incr(key)
        pipe.expire(key, 90)
        count, _ = await pipe.execute()
        if int(count) > self.per_minute:
            raise RateLimitExceeded("rate limit exceeded")
