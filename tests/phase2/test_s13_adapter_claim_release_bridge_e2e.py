"""Disposable PostgreSQL E2E for the flag-on claim/release adapter bridges.

Acceptance: S13-CLAIM-PARENT-RANK-01 and S13-RELEASE-CLAIM-RANK-01 require the enabled
adapter path to retain caller-preallocated claim identity while direct versioned entry points
remain unavailable to runtime roles. This slice does not close the wider lock-order/race matrix.
Run only after coding closes: uv run pytest -q -s
tests/phase2/test_s13_adapter_claim_release_bridge_e2e.py
"""
from __future__ import annotations

import uuid

import asyncpg
import pytest

pytest_plugins = ("test_s13_current_turn_sql",)

import business_ai_gateway.phase2.change_ledger.sql_ledger as sql_ledger_module
from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger
from test_change_ledger_sql import BASE, DEFAULT_GRANT, ORG, exp, fixture_digest_for, sha
from test_s13_current_turn_sql import C, T, L, _ledger_snapshot, ledger

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_s13_flag_on_adapter_uses_narrow_claim_and_release_bridges(
        ledger: L, monkeypatch: pytest.MonkeyPatch) -> None:
    """Candidate runtime reaches only granted bridges and preserves the supplied token ID."""
    change_id = await ledger.approved(request_id="s13-adapter-claim-release-bridge")
    budget = await ledger.conn.fetchrow(
        "SELECT grant_id,amount,counts_create_update,counts_post "
        "FROM change_ledger.change_budget WHERE change_id=$1",
        change_id,
    )
    assert budget is not None

    actor_roles = {"requester": "clt_alice", "worker": "clt_wri"}
    adapter = SqlChangeLedger(
        ledger.conn,
        actors=actor_roles,
        private_writer_schema_enabled=True,
    )
    scope = Scope(T, C)
    token_id = uuid.UUID("73b20000-7a1b-4e33-8b14-f4893db1d80f")
    monkeypatch.setattr(sql_ledger_module, "uuid4", lambda: token_id)

    # Pin the intended adapter target as well as the runtime outcome: a legacy fallback would
    # allocate a different token ID, and a direct *_v1 call is denied to this role below.
    assert sql_ledger_module._PRIVATE_WRITER_SPEC["claim_s13"].name == "claim_with_id_v1"
    assert sql_ledger_module._PRIVATE_WRITER_SPEC["release_claim_s13"].name == "release_claim"
    assert await ledger.conn.fetchval(
        "SELECT pg_catalog.has_function_privilege('clt_alice', "
        "'change_ledger.claim_with_id_v1(text,text,uuid,text,uuid,numeric,boolean,boolean,uuid)', "
        "'EXECUTE')"
    ) is True
    assert await ledger.conn.fetchval(
        "SELECT pg_catalog.has_function_privilege('clt_alice', "
        "'change_ledger.release_claim(text,text,uuid)', 'EXECUTE')"
    ) is True

    token = await adapter.claim(
        scope,
        change_id,
        grant_id=budget["grant_id"],
        amount=budget["amount"],
        counts_create_update=budget["counts_create_update"],
        counts_post=budget["counts_post"],
    )
    assert token is not None
    assert token["token_id"] == token_id

    # The private adapter releases through the same authorized SECDEF bridge as legacy callers.
    assert await adapter.release_claim(scope, token_id) == "SUPERSEDED"
    token_state = await ledger.conn.fetchval(
        "SELECT state FROM change_ledger.claim_tokens WHERE token_id=$1", token_id
    )
    assert token_state == "SUPERSEDED"
    record = await ledger.conn.fetchrow(
        "SELECT authorization_state,execution_state FROM change_ledger.records "
        "WHERE change_id=$1",
        change_id,
    )
    assert record is not None
    assert record["authorization_state"] == "APPROVED"
    assert record["execution_state"] == "NOT_STARTED"
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
        "AND change_id=$3 AND event_type='CLAIM_RELEASED'",
        T,
        C,
        change_id,
    ) == 1

    direct_claim = (
        "change_ledger.claim_v1(text,text,uuid,text,uuid,numeric,boolean,boolean,uuid)"
    )
    direct_release = "change_ledger.release_claim_v1(text,text,uuid)"
    assert await ledger.conn.fetchval(
        "SELECT NOT pg_catalog.has_function_privilege('clt_alice',$1,'EXECUTE')", direct_claim
    ) is True
    assert await ledger.conn.fetchval(
        "SELECT NOT pg_catalog.has_function_privilege('clt_alice',$1,'EXECUTE')", direct_release
    ) is True

    before_denied_calls = await _ledger_snapshot(ledger.conn)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await ledger.sql(
            "clt_alice",
            "SELECT change_ledger.claim_v1($1,$2,$3,$4,$5,$6,$7,$8,$9)",
            T,
            C,
            change_id,
            None,
            budget["grant_id"],
            budget["amount"],
            budget["counts_create_update"],
            budget["counts_post"],
            uuid.uuid4(),
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await ledger.sql(
            "clt_alice",
            "SELECT change_ledger.release_claim_v1($1,$2,$3)",
            T,
            C,
            token_id,
        )
    assert await _ledger_snapshot(ledger.conn) == before_denied_calls


@pytest.mark.asyncio
async def test_s13_flag_on_adapter_proposal_and_validation_use_granted_bridges(
        ledger: L) -> None:
    """Candidate adapter reaches preserved proposal/validation bridges, never direct v1 APIs."""
    adapter = SqlChangeLedger(
        ledger.conn,
        actors={"requester": "clt_alice"},
        private_writer_schema_enabled=True,
    )
    scope = Scope(T, C)
    change_id = uuid.UUID("73b20000-7a1b-4e33-8b14-f4893db1d810")
    request_id = "s13-adapter-propose-validate-bridge"

    assert sql_ledger_module._PRIVATE_WRITER_SPEC["propose_s13"].name == "propose"
    assert sql_ledger_module._PRIVATE_WRITER_SPEC["validate_s13"].name == "validate"
    assert await ledger.conn.fetchval(
        "SELECT pg_catalog.has_function_privilege('clt_alice', "
        "'change_ledger.propose(text,text,uuid,text,text,text,text,text,text,text,text,uuid,timestamptz,uuid)', "
        "'EXECUTE')"
    ) is True
    assert await ledger.conn.fetchval(
        "SELECT pg_catalog.has_function_privilege('clt_alice', "
        "'change_ledger.validate(text,text,uuid)', 'EXECUTE')"
    ) is True

    assert await adapter.propose(
        scope,
        change_id,
        "CREATE_DRAFT",
        BASE,
        ORG,
        "clt_alice",
        request_id,
        fixture_digest_for("CREATE_DRAFT"),
        "doc1",
        "v1",
        None,
        exp(),
        None,
    ) == change_id
    row = await ledger.conn.fetchrow(
        "SELECT requester,request_id,lifecycle FROM change_ledger.records WHERE change_id=$1",
        change_id,
    )
    assert row is not None
    assert row["requester"] == "clt_alice"
    assert row["request_id"] == request_id
    assert row["lifecycle"] == "PROPOSED"
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
        "AND change_id=$3 AND event_type='PROPOSED'",
        T,
        C,
        change_id,
    ) == 1

    # Prepare prerequisite rows through their already granted bridges; this case targets only
    # the flag-on proposal and validation adapter routes.
    await ledger.call("clt_alice", "declare_business_key", change_id, sha(str(change_id)), None, None)
    await ledger.call("clt_alice", "declare_target_class", change_id, "CLONE")
    await ledger.call(
        "clt_alice",
        "declare_budget",
        change_id,
        DEFAULT_GRANT[(T, C)],
        "EUR",
        0,
        False,
        False,
    )
    assert await adapter.validate(scope, change_id) == "VALIDATED"
    row = await ledger.conn.fetchrow(
        "SELECT lifecycle FROM change_ledger.records WHERE change_id=$1", change_id
    )
    assert row is not None and row["lifecycle"] == "VALIDATED"
    assert await ledger.conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
        "AND change_id=$3 AND event_type='VALIDATED'",
        T,
        C,
        change_id,
    ) == 1

    direct_proposal = (
        "change_ledger.propose_v1(text,text,uuid,text,text,text,text,text,text,text,text,uuid,timestamptz,uuid)"
    )
    direct_validate = "change_ledger.validate_v1(text,text,uuid)"
    assert await ledger.conn.fetchval(
        "SELECT NOT pg_catalog.has_function_privilege('clt_alice',$1,'EXECUTE')", direct_proposal
    ) is True
    assert await ledger.conn.fetchval(
        "SELECT NOT pg_catalog.has_function_privilege('clt_alice',$1,'EXECUTE')", direct_validate
    ) is True

    before_denied_calls = await _ledger_snapshot(ledger.conn)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await ledger.sql(
            "clt_alice",
            "SELECT change_ledger.propose_v1($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)",
            T,
            C,
            uuid.uuid4(),
            "CREATE_DRAFT",
            BASE,
            ORG,
            "clt_alice",
            "s13-adapter-direct-propose-denied",
            fixture_digest_for("CREATE_DRAFT"),
            "doc2",
            "v1",
            None,
            exp(),
            None,
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await ledger.sql("clt_alice", "SELECT change_ledger.validate_v1($1,$2,$3)", T, C, change_id)
    assert await _ledger_snapshot(ledger.conn) == before_denied_calls
