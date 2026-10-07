import pytest

from scripts.migrate import _migration_applied, _preflight_history, load_migrations


class FakeConnection:
    def __init__(self, *, history_exists: bool, applied: bool):
        self.history_exists = history_exists
        self.applied = applied
        self.calls = []

    async def fetchval(self, query, *args):
        self.calls.append((query, args))
        if "to_regclass" in query:
            return self.history_exists
        return self.applied


async def test_migration_runner_applies_schema_when_history_is_absent():
    conn = FakeConnection(history_exists=False, applied=False)

    assert await _migration_applied(conn, 3) is False
    assert len(conn.calls) == 1


async def test_migration_runner_skips_a_version_already_recorded():
    conn = FakeConnection(history_exists=True, applied=True)

    assert await _migration_applied(conn, 3) is True
    assert len(conn.calls) == 2


async def test_migration_runner_runs_a_new_version_with_existing_history():
    conn = FakeConnection(history_exists=True, applied=False)

    assert await _migration_applied(conn, 4) is False
    assert conn.calls[1][1] == (4,)


class FutureLedgerConnection:
    def __init__(self):
        self.ddl_calls = []

    async def fetchval(self, query, *args):
        return "to_regclass" in query

    async def fetch(self, query, *args):
        if "information_schema.columns" in query:
            return [{"column_name": "name"}, {"column_name": "checksum"}]
        return [{"version": 15, "name": "future", "checksum": "0" * 64}]


@pytest.mark.asyncio
async def test_ahead_of_code_migration_version_is_rejected_before_ddl():
    conn = FutureLedgerConnection()
    with pytest.raises(RuntimeError, match="unknown to this release"):
        await _preflight_history(conn, load_migrations())
    assert conn.ddl_calls == []
