"""CR101 / R-03-021 application-to-PostgreSQL boundary journey.

The caller owns an isolated PostgreSQL database after migrations 001-021 and the historical
pre-cutover fixtures are in place. This helper owns no container or database lifecycle. It uses
the real ``SqlChangeLedger`` adapter to prove that an Ed25519 completion is accepted, while a
valid legacy-signed completion written before cutover cannot authorize the same action after
migration 021. The audit read path must still return that historical row.
"""
from __future__ import annotations

import json
import uuid

import asyncpg

from _ed25519_fixtures import pub_hex, sign_hex
from test_change_ledger_sql import C, L, T
from business_ai_gateway.phase2.change_ledger._common import LedgerError, Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger


async def run_api_boundary(conn: asyncpg.Connection) -> dict[str, str]:
    """Use the application adapter against real post-cutover PostgreSQL state."""
    scope = Scope(T, C)
    api = SqlChangeLedger(conn, actors={"writer": "clt_wri", "auditor": "clt_aud"})

    # The functional fixture seeds this valid legacy completion through migration 018 while the
    # old writer API is still installed. Select an APPLYING/DISPATCHED action so its evidence is
    # otherwise sufficient to complete the state transition.
    legacy = await conn.fetchrow(
        "SELECT e.evidence_id,e.change_id,e.generation,r.claim_generation,r.execution_state,"
        "r.dispatch_state,k.key_algorithm "
        "FROM change_ledger.evidence_records e "
        "JOIN change_ledger.verifier_keys k ON k.tenant_id=e.tenant_id "
        "AND k.company_id=e.company_id AND k.key_id=e.signer_key_id "
        "JOIN change_ledger.records r ON r.tenant_id=e.tenant_id "
        "AND r.company_id=e.company_id AND r.change_id=e.change_id "
        "WHERE e.tenant_id=$1 AND e.company_id=$2 AND e.kind='COMPLETION_PROOF' "
        "AND e.content->>'class'='a' AND k.key_algorithm='KEYED_HASH_STANDIN' "
        "AND r.execution_state='APPLYING' AND r.dispatch_state='DISPATCHED' "
        "AND e.generation=r.claim_generation ORDER BY e.recorded_at LIMIT 1",
        T, C,
    )
    assert legacy is not None, "missing valid pre-cutover legacy completion fixture"
    assert legacy["key_algorithm"] == "KEYED_HASH_STANDIN"

    legacy_id = legacy["evidence_id"]
    cid = legacy["change_id"]
    before = await conn.fetchrow(
        "SELECT execution_state,dispatch_state,claim_generation FROM change_ledger.records "
        "WHERE tenant_id=$1 AND company_id=$2 AND change_id=$3", T, C, cid)
    before_events = await conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 AND change_id=$3",
        T, C, cid)
    try:
        await api.complete_signed(scope, cid, legacy["generation"], "SUCCESS", legacy_id)
    except LedgerError as error:
        assert error.code == "EVIDENCE_UNSIGNED", error.code
    else:
        raise AssertionError("post-cutover adapter accepted legacy evidence as action authority")

    after = await conn.fetchrow(
        "SELECT execution_state,dispatch_state,claim_generation FROM change_ledger.records "
        "WHERE tenant_id=$1 AND company_id=$2 AND change_id=$3", T, C, cid)
    assert dict(after) == dict(before), "rejected legacy action changed its record state"
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 AND change_id=$3",
        T, C, cid) == before_events, "rejected legacy action appended an event"

    historical = await api.read_evidence(scope, cid, as_class="auditor")
    assert any(str(row["evidence_id"]) == str(legacy_id)
               and row["signer_key_id"] == "vk-legacy-wri" for row in historical), \
        "audit adapter no longer exposes the retained historical legacy evidence"

    # A fresh Ed25519 completion on the very same dispatched record remains actionable.
    key_id = "r03-api-postcutover-writer"
    await conn.execute(
        "INSERT INTO change_ledger.verifier_keys"
        "(tenant_id,company_id,key_id,role_name,key_material,key_algorithm) "
        "VALUES($1,$2,$3,'clt_wri',$4,'ED25519')",
        T, C, key_id, pub_hex(key_id),
    )
    call_id = await conn.fetchval(
        "SELECT call_id FROM change_ledger.dispatch_permits "
        "WHERE change_id=$1 AND generation=$2", cid, legacy["generation"])
    assert call_id is not None, "dispatched action has no bound call id"
    content = {
        "generation": legacy["generation"],
        "call_id": str(call_id),
        "nonce": uuid.uuid4().hex,
        "class": "a",
        "result_returned": True,
    }
    observed_at = await conn.fetchval("SELECT clock_timestamp()")
    content_hash = await conn.fetchval(
        "SELECT change_ledger.canonical_content_hash($1::jsonb)", json.dumps(content))
    binding = await conn.fetchval(
        "SELECT change_ledger.evidence_binding($1,$2,$3,$4,$5,$6)",
        cid, "COMPLETION_PROOF", content_hash, observed_at, legacy["generation"], call_id)
    evidence_id = await api.record_evidence(
        scope, cid, "COMPLETION_PROOF", content_hash, observed_at, content,
        key_id, binding, sign_hex(key_id, binding), legacy["generation"], call_id,
    )
    result = await api.complete_signed(scope, cid, legacy["generation"], "SUCCESS", evidence_id)
    assert result == "APPLIED", f"valid Ed25519 completion returned {result!r}"
    assert await conn.fetchval(
        "SELECT execution_state FROM change_ledger.records WHERE change_id=$1", cid) == "APPLIED"

    return {
        "journey": "SqlChangeLedger.complete_signed/read_evidence to PostgreSQL after migrations 001-021",
        "valid_ed25519": "accepted and recorded",
        "valid_legacy_signature": "rejected as EVIDENCE_UNSIGNED",
        "state": "rejected action left no row",
        "action": "Ed25519 completion reached APPLIED; legacy rejection changed neither state nor events",
        "legacy_evidence": "pre-cutover record rejected as EVIDENCE_UNSIGNED",
        "historical_read": "retained legacy evidence visible through auditor adapter",
    }
