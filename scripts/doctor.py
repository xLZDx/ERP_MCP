import asyncio

from business_ai_gateway.runtime import Runtime
from business_ai_gateway.settings import Settings


async def main():
    settings = Settings()
    runtime = Runtime(settings)
    await runtime.start()
    try:
        print(
            {
                "environment": settings.environment,
                "db": await runtime.db.ping(),
                "redis": bool(await runtime.redis.ping()),
                "secret_provider": settings.secret_provider,
                "oauth_enabled": settings.oauth_enabled,
            }
        )
    finally:
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
