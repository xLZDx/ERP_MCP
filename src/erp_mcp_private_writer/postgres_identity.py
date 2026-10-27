"""Fail-closed PostgreSQL session identity checks for private-writer adapters."""
from __future__ import annotations

import asyncio
import time
from typing import Any

PRIVATE_WRITER_SESSION_USER = "business_ai_private_writer"
EVIDENCE_INGEST_SESSION_USER = "private_writer_evidence_ingest"


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
