"""Fail-closed PostgreSQL session identity checks for private-writer adapters."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from business_ai_gateway.phase2.change_ledger.checkpoint import DatabaseTargetIdentity

PRIVATE_WRITER_SESSION_USER = "business_ai_private_writer"
EVIDENCE_INGEST_SESSION_USER = "private_writer_evidence_ingest"


class DatabaseIdentityUnavailable(RuntimeError):
    """Fixed, sanitized refusal when a server-derived database identity cannot be read."""

    def __init__(self) -> None:
        super().__init__("DATABASE_TARGET_IDENTITY_UNAVAILABLE")


async def read_database_target_identity(connection: Any) -> DatabaseTargetIdentity:
    """Read the cluster system ID and current database OID from the authenticated session.

    Migration 028 exposes only this read-only identity function to the exact T16 roles. Caller
    adapters bound the query with their existing statement/operation deadline and sanitize errors.
    """
    try:
        row = await connection.fetchrow(
            "SELECT system_identifier, database_oid "
            "FROM change_ledger.t16_database_identity_v1()"
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        raise DatabaseIdentityUnavailable() from None
    if row is None:
        raise DatabaseIdentityUnavailable()
    try:
        return DatabaseTargetIdentity(
            system_identifier=row["system_identifier"],
            database_oid=row["database_oid"],
        )
    except (IndexError, KeyError, TypeError, ValueError):
        raise DatabaseIdentityUnavailable() from None


async def has_expected_database_identity(
        connection: Any, expected_session_user: str, deadline: float) -> bool:
    """Check server-authenticated roles without returning either identity to callers.

    Both roles must match: ``session_user`` is the login identity checked by the candidate SQL,
    while ``current_user`` detects an unexpected role switch in the adapter transaction.
    Call only after transaction isolation and its statement timeout are established.
    """
    if (type(expected_session_user) is not str or not expected_session_user
            or expected_session_user != expected_session_user.strip()):
        return False
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError
    async with asyncio.timeout(remaining):
        value = await connection.fetchval(
            "SELECT SESSION_USER::text = $1 AND CURRENT_USER::text = $1",
            expected_session_user,
        )
    return type(value) is bool and value
