from __future__ import annotations

from argparse import Namespace
from uuid import UUID

import pytest

from scripts.admin import parser, platform_role_add, platform_role_revoke


class FakeConnection:
    def __init__(self):
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        if "INSERT INTO bag.platform_role_bindings" in sql:
            return {
                "binding_id": args[0],
                "principal_kind": args[1],
                "principal_id": args[2],
                "role_name": args[3],
                "source_id": args[4],
            }
        if "UPDATE bag.platform_role_bindings" in sql:
            return {
                "binding_id": args[0],
                "principal_kind": "subject",
                "principal_id": "operator-1",
                "role_name": "PLATFORM_ADMIN",
                "source_id": None,
                "revoked_at": "now",
            }
        raise AssertionError(sql)


@pytest.mark.asyncio
async def test_platform_role_add_uses_stable_binding_id_and_actor_provenance():
    conn = FakeConnection()
    binding_id = "5d54d8b5-1db2-42df-a7a6-eacdf9010c0a"
    args = Namespace(
        binding_id=binding_id,
        kind="subject",
        principal="operator-1",
        role="PLATFORM_ADMIN",
        source_id=None,
        expires_at=None,
        created_by="bootstrap-owner",
        client_id="operator-cli",
        reason="Initial Admin Control Center bootstrap",
    )

    await platform_role_add(args, conn)

    sql, values = conn.calls[-1]
    assert "INSERT INTO bag.platform_role_bindings" in sql
    assert values[0] == UUID(binding_id)
    assert values[1:5] == ("subject", "operator-1", "PLATFORM_ADMIN", None)
    assert values[6:] == (
        "bootstrap-owner",
        "operator-cli",
        "Initial Admin Control Center bootstrap",
    )


@pytest.mark.asyncio
async def test_platform_role_revoke_is_exact_binding_id():
    conn = FakeConnection()
    binding_id = "4bc00b35-84fd-4864-9993-aa11ec372323"

    await platform_role_revoke(Namespace(binding_id=binding_id), conn)

    sql, values = conn.calls[-1]
    assert "WHERE binding_id=$1" in sql
    where_clause = sql.split("WHERE", 1)[1].split("RETURNING", 1)[0]
    assert "principal_id" not in where_clause
    assert values == (UUID(binding_id),)


def test_platform_role_cli_commands_are_registered():
    p = parser()

    add = p.parse_args(
        [
            "platform-role-add",
            "--principal",
            "operator-1",
            "--role",
            "PLATFORM_ADMIN",
            "--created-by",
            "bootstrap-owner",
            "--reason",
            "bootstrap",
        ]
    )
    revoke = p.parse_args(
        [
            "platform-role-revoke",
            "--binding-id",
            "4bc00b35-84fd-4864-9993-aa11ec372323",
        ]
    )

    assert add.command == "platform-role-add"
    assert revoke.command == "platform-role-revoke"
