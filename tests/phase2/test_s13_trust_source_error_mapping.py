"""Error mapping of the trust snapshot source (no database)."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import asyncpg
import pytest

from erp_mcp_private_writer import postgres_evidence_trust as trust_module
from erp_mcp_private_writer.evidence_trust import TrustSnapshotRequest
from erp_mcp_private_writer.postgres_evidence_trust import (
    EvidenceTrustSourceError,
    PostgresEvidenceTrustSource,
)


class _Transaction:
    async def start(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None


class _Connection:
    def is_in_transaction(self):
        return False

    def transaction(self):
        return _Transaction()

    def terminate(self):
        pass

    async def execute(self, *_args):
        return None


class _Pool(asyncpg.Pool):
    def __init__(self):
        pass

    @asynccontextmanager
    async def acquire(self, **_kwargs):
        yield _Connection()


def _source(monkeypatch, error: Exception) -> PostgresEvidenceTrustSource:
    async def _identity_ok(*_args):
        return True

    async def _raise(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(trust_module, "has_expected_database_identity", _identity_ok)
    monkeypatch.setattr(PostgresEvidenceTrustSource, "_fetch_before_deadline",
                        lambda self, conn, deadline, request: _raise())
    return PostgresEvidenceTrustSource(_Pool())


def _code(source) -> str:
    request = object.__new__(TrustSnapshotRequest)
    with pytest.raises(EvidenceTrustSourceError) as raised:
        asyncio.run(source.load_snapshot(request))
    return raised.value.code


def _raise_error(message: str) -> asyncpg.exceptions.RaiseError:
    error = asyncpg.exceptions.RaiseError(message)
    error.message = message
    return error


def test_an_exact_database_code_is_passed_through(monkeypatch):
    source = _source(monkeypatch, _raise_error("TRUST_ROTATION_CHAIN_TOO_DEEP"))

    assert _code(source) == "TRUST_ROTATION_CHAIN_TOO_DEEP"


def test_a_message_that_only_contains_a_known_code_is_not_mapped_to_it(monkeypatch):
    source = _source(monkeypatch, _raise_error("see TRUST_ROTATION_CHAIN_TOO_DEEP in log"))

    assert _code(source) == "TRUST_SNAPSHOT_UNAVAILABLE"
