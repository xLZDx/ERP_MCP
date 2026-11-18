"""Focused S13-04 legacy registry bridge contracts on disposable PostgreSQL."""
from __future__ import annotations

import asyncpg
import json

import pytest

from test_change_ledger_sql import L
from test_s13_inflight_status import ledger

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]


# The legacy entry points retain their migration-005/010 caller grants. The paired v1
# signatures are intentionally not runtime entry points after migration 027.
_LEGACY_BRIDGES = (
    ("bump_epoch(text,text,text)", "bump_epoch_v1(text,text,text)", "operator_role"),
    (
        "register_principal(text,text,text,text,text[],boolean)",
        "register_principal_v1(text,text,text,text,text[],boolean)",
        "operator_role",
    ),
    (
        "register_target(text,text,text,text,text,text,timestamptz)",
        "register_target_v1(text,text,text,text,text,text,timestamptz)",
        "operator_role",
    ),
    (
        "approve_registry_change(text,text,uuid,text)",
        "approve_registry_change_v1(text,text,uuid,text)",
        "operator_role",
    ),
    (
        "add_epoch_dependency(text,text,uuid,text)",
        "add_epoch_dependency_v1(text,text,uuid,text)",
        "requester_role",
    ),
    (
        "register_verifier_key(text,text,text,text,text)",
        "register_verifier_key_v1(text,text,text,text,text)",
        "operator_role",
    ),
    (
        "revoke_verifier_key(text,text,text)",
        "revoke_verifier_key_v1(text,text,text)",
        "operator_role",
    ),
    ("enforce_registry(text,text)", "enforce_registry_v1(text,text)", "operator_role"),
    (
        "propose_registry_change(text,text,text,jsonb)",
        "propose_registry_change_v1(text,text,uuid,text,jsonb)",
        "operator_role",
    ),
    (
        "propose(text,text,uuid,text,text,text,text,text,text,text,text,uuid,timestamptz,uuid)",
        "propose_v1(text,text,uuid,text,text,text,text,text,text,text,text,uuid,timestamptz,uuid)",
        "requester_role",
    ),
)


async def test_legacy_registry_grants_remain_and_v1_routes_are_not_callable_by_runtime_roles(
    ledger: L,
) -> None:
    """Preserve the old caller ACL while denying direct access to versioned bodies."""
    conn = ledger.conn
    runtime_roles = (
        "requester_role",
        "approver_role",
        "operator_role",
        "writer_role",
        "worker_role",
        "auditor_role",
        "checkpoint_role",
        "business_ai_private_writer",
        "private_writer_evidence_ingest",
    )

    for legacy_signature, v1_signature, entitled_role in _LEGACY_BRIDGES:
        legacy = f"change_ledger.{legacy_signature}"
        v1 = f"change_ledger.{v1_signature}"
        assert await conn.fetchval(
            "SELECT pg_catalog.has_function_privilege($1::text::name, $2::text::regprocedure, 'EXECUTE')",
            entitled_role,
            legacy,
        ), f"legacy entry point lost its {entitled_role} grant: {legacy}"
        for role in runtime_roles:
            assert not await conn.fetchval(
                "SELECT pg_catalog.has_function_privilege($1::text::name, $2::text::regprocedure, 'EXECUTE')",
                role,
                v1,
            ), f"runtime role {role} can call fenced implementation directly: {v1}"

    # The runtime roles used by the positive scenario must not receive the operator-only grant.
    assert not await conn.fetchval(
        "SELECT pg_catalog.has_function_privilege('requester_role', "
        "'change_ledger.register_target(text,text,text,text,text,text,timestamptz)'::regprocedure, "
        "'EXECUTE')"
    )


async def test_legacy_register_target_bridge_records_synthetic_target_as_calling_operator(
    ledger: L,
) -> None:
    """The entitled legacy signature commits the target and its epoch/audit through v1."""
    conn = ledger.conn
    base = "base-1"
    before = await conn.fetchrow(
        "SELECT target.epoch AS target_epoch, "
        "change_ledger.epoch_value($1,$2,'target:'||$3) AS registry_epoch "
        "FROM change_ledger.targets AS target "
        "WHERE target.tenant_id=$1 AND target.company_id=$2 AND target.base_fingerprint=$3",
        "T1",
        "C1",
        base,
    )
    assert before is not None, "the shared disposable fixture must seed base-1"

    returned_epoch = await ledger.call(
        "clt_dave",
        "register_target",
        base,
        "org-1",
        "CLONE",
        "ACTIVE",
        None,
    )

    after = await conn.fetchrow(
        "SELECT target.organization_ref, target.target_class, target.status, "
        "target.registered_by, target.epoch AS target_epoch, "
        "change_ledger.epoch_value($1,$2,'target:'||$3) AS registry_epoch "
        "FROM change_ledger.targets AS target "
        "WHERE target.tenant_id=$1 AND target.company_id=$2 AND target.base_fingerprint=$3",
        "T1",
        "C1",
        base,
    )
    events = await conn.fetch(
        "SELECT event_type, payload FROM change_ledger.events "
        "WHERE tenant_id=$1 AND company_id=$2 AND event_type IN ('TARGET_REGISTERED','EPOCH_BUMPED') "
        "AND payload->>'base'=$3 ORDER BY seq",
        "T1",
        "C1",
        base,
    )

    assert (after["organization_ref"], after["target_class"], after["status"]) == (
        "org-1",
        "DISPOSABLE_CLONE",
        "ACTIVE",
    )
    assert after["registered_by"] == "clt_dave"
    assert after["target_epoch"] == before["target_epoch"] + 1
    assert after["registry_epoch"] == before["registry_epoch"] + 1
    assert returned_epoch == after["registry_epoch"]
    assert len(events) == 1
    assert events[0]["event_type"] == "TARGET_REGISTERED"
    payload = events[0]["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload == {
        "base": base,
        "organization": "org-1",
        "class": "DISPOSABLE_CLONE",
        "status": "ACTIVE",
        "by": "clt_dave",
    }


async def test_legacy_observe_target_bridge_rejects_substituted_fingerprint_then_binds_exact_target(
    ledger: L,
) -> None:
    """The entitled writer cannot bind its claim to a different registered target."""
    change_id = await ledger.propose(request_id="s13-observe-bridge-fingerprint")
    token = await ledger.claimed(change_id, observe=False)
    token_id = token["token_id"]
    before_events = await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events "
        "WHERE tenant_id='T1' AND company_id='C1' AND change_id=$1 "
        "AND event_type='TARGET_OBSERVED'",
        change_id,
    )

    with pytest.raises(asyncpg.PostgresError, match="TARGET_REJECTED"):
        await ledger.call("clt_wri", "observe_target", token_id, "substituted-test-fingerprint", "CLONE")

    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.target_observations WHERE change_id=$1", change_id
    ) == 0
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events "
        "WHERE tenant_id='T1' AND company_id='C1' AND change_id=$1 "
        "AND event_type='TARGET_OBSERVED'",
        change_id,
    ) == before_events

    assert await ledger.call("clt_wri", "observe_target", token_id, "base-1", "CLONE") is True
    observation = await ledger.conn.fetchrow(
        "SELECT observed_fingerprint, observed_class, observed_by "
        "FROM change_ledger.target_observations WHERE change_id=$1 AND generation=$2",
        change_id,
        token["generation"],
    )
    assert tuple(observation) == ("base-1", "DISPOSABLE_CLONE", "clt_wri")
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events "
        "WHERE tenant_id='T1' AND company_id='C1' AND change_id=$1 "
        "AND event_type='TARGET_OBSERVED'",
        change_id,
    ) == before_events + 1
