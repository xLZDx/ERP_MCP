from pathlib import Path

import pytest

from business_ai_gateway.db import SCHEMA_VERSION, Database


class SchemaPool:
    def __init__(self, version):
        self.version = version

    async def fetchval(self, query):
        return self.version

    async def fetchrow(self, query):
        if self.version is None:
            return {"minimum": None, "maximum": None, "count": 0, "identified": None}
        return {
            "minimum": 1,
            "maximum": self.version,
            "count": self.version,
            "identified": True,
        }


@pytest.mark.asyncio
async def test_runtime_accepts_the_complete_migration_chain():
    latest = max(int(p.name.split("_", 1)[0]) for p in Path("db/migrations").glob("*.sql"))
    db = Database("unused")
    db.pool = SchemaPool(latest)
    assert latest == SCHEMA_VERSION
    await db.assert_schema()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [None, 7, 8, 10, 12, 13, 15])
async def test_runtime_rejects_old_missing_and_unknown_future_schema(version):
    db = Database("unused")
    db.pool = SchemaPool(version)
    with pytest.raises(RuntimeError, match="unsupported or unidentified schema"):
        await db.assert_schema()
