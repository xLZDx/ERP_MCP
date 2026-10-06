"""Create a NEW disposable PostgreSQL instance and execute actual registry CLI contracts."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from pathlib import Path

import asyncpg

from scripts.execute_evidence_tests import execute
from scripts.postgres_restore_drill import migrate, new_postgres


async def run() -> dict:
    container = f"erp-capability-{uuid.uuid4().hex[:12]}"
    dsn = await new_postgres(container)
    connection = await asyncpg.connect(dsn)
    try:
        await migrate(connection)
    finally:
        await connection.close()
    previous = os.environ.get("BAG_PRIVILEGE_TEST_DATABASE_URL")
    os.environ["BAG_PRIVILEGE_TEST_DATABASE_URL"] = dsn
    try:
        evidence = await asyncio.to_thread(execute, ["tests/test_capability_registry_postgres.py"])
    finally:
        if previous is None:
            os.environ.pop("BAG_PRIVILEGE_TEST_DATABASE_URL", None)
        else:
            os.environ["BAG_PRIVILEGE_TEST_DATABASE_URL"] = previous
    evidence.update(container=container, new_disposable_database=True, existing_data_touched=False,
                    real_1c_called=False, container_retained=True)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = asyncio.run(run())
    rendered = json.dumps(evidence, sort_keys=True, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            output.write(rendered)
    print(rendered, end="")
    if not evidence["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
