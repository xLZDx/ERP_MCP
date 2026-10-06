"""Stop/restart newly created PostgreSQL/Redis containers and exercise gateway readiness.

Containers and databases are retained. Existing targets cannot be supplied.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time
import uuid
from unittest.mock import patch

from redis.asyncio import Redis

from business_ai_gateway.runtime import Runtime
from business_ai_gateway.settings import Settings

try:
    from .postgres_restore_drill import REPO, command, new_postgres
except ImportError:
    from postgres_restore_drill import REPO, command, new_postgres


async def execute() -> dict[str, object]:
    from business_ai_gateway.app import readyz

    suffix = uuid.uuid4().hex[:12]
    names = {"postgres": f"erp-fault-pg-{suffix}", "redis": f"erp-fault-redis-{suffix}"}
    def free_port():
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            return reservation.getsockname()[1]

    database_url = await new_postgres(names["postgres"], host_port=free_port())
    environment = {**os.environ, "BAG_DATABASE_URL": database_url}
    command(sys.executable, str(REPO / "scripts/migrate.py"), env=environment)
    command("docker", "run", "-d", "--name", names["redis"], "-p", f"127.0.0.1:{free_port()}:6379", "redis:7-alpine")
    port = command("docker", "port", names["redis"], "6379/tcp").rsplit(":", 1)[-1]
    if not port.isdigit():
        raise RuntimeError("unexpected Redis loopback port")
    settings = Settings(_env_file=None, environment="development", database_url=database_url,
                        redis_url=f"redis://127.0.0.1:{port}/0")
    runtime = Runtime(settings)
    await runtime.redis.aclose()
    runtime.redis = Redis.from_url(settings.redis_url, decode_responses=True,
                                   socket_connect_timeout=1, socket_timeout=1)
    results = []

    async def response():
        with patch("business_ai_gateway.app.runtime", runtime):
            async with asyncio.timeout(5):
                return await readyz(None)

    async def wait_ready():
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                if (await response()).status_code == 200:
                    return
            except TimeoutError:
                pass
            await asyncio.sleep(0.25)
        raise RuntimeError("isolated dependency did not recover")

    try:
        await wait_ready()
        for dependency, name in names.items():
            command("docker", "stop", "--time", "1", name)
            try:
                failed = await response()
                body = json.loads(failed.body)
                sanitized = database_url not in failed.body.decode() and "password" not in failed.body.decode().lower()
                if failed.status_code != 503 or body.get("status") != "not-ready" or not sanitized:
                    raise RuntimeError("readiness failed to normalize actual dependency outage")
            finally:
                command("docker", "start", name)
            await wait_ready()
            recovered = await response()
            results.append({"dependency": dependency, "failure_status": failed.status_code,
                            "recovered_status": recovered.status_code, "sanitized": sanitized,
                            "passed": recovered.status_code == 200})
    finally:
        await runtime.close()
    return {
        "mode": "actual_local_container_outages", "containers_retained": names,
        "real_1c_called": False, "results": results,
        "passed": all(item["passed"] for item in results),
        "not_covered": ["JWKS", "secrets", "OData", "RSV", "audit_during_DB_outage"],
    }
