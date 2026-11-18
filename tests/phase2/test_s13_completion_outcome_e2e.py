"""S13 terminal-outcome qualification slices on invocation-owned PostgreSQL.

Success and PRE_WRITE_NO_EFFECT scenarios use READY only as an explicitly fixture-seeded
static precondition, not as proof of runtime readiness. The separate setup-gate test confirms
the current lifecycle recovery entry remains fail-closed.

T16 remains a separate unqualified boundary: migration 027 revokes operator_resolve_v1 from
operator_role and does not grant it later. This test records that ACL fact without bypassing it.
This slice covers normal-success, PRE_WRITE_NO_EFFECT, target-lock-owner mismatch, and the bounded
PRE_WRITE repair handoff. The broader T16 repair/resolve flow and conditional-version-conflict
scenario remain explicitly NOT COVERED.
"""
from __future__ import annotations

import asyncpg
import pytest
import pytest_asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime

from _pg_harness import apply_files, throwaway_db
from test_change_ledger_sql import _setup
from test_s13_current_turn_sql import (
    MIGRATIONS_019_027,
    _OwnedClusterDsn,
    _apply_migration,
    _safe_postgres_diagnostics,
)

pytest_plugins = ("test_s13_current_turn_sql",)

from business_ai_gateway.phase2.change_ledger._common import Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger
from _ed25519_fixtures import pub_hex, sign_hex
from test_change_ledger_sql import C, L, T
from test_s13_current_turn_sql import _ledger_snapshot


@pytest_asyncio.fixture
async def ledger(owned_cluster_dsn: _OwnedClusterDsn):
    """Build the S13 candidate through migration 030 in this owned throwaway database."""
    async with throwaway_db(owned_cluster_dsn.value, seed=False) as db:
        step = "base migrations 001-018"
        try:
            await apply_files(db.conn)
            for migration in MIGRATIONS_019_027:
                step = migration
                await _apply_migration(db.conn, migration)
            step = "synthetic S13 fixture setup"
            await _setup(db.conn)
            await db.conn.execute(
                "INSERT INTO change_ledger.lifecycle_fences(tenant_id,company_id,state,epoch,reason) "
                "VALUES($1,$2,'LEGACY',0,'TEST_FIXTURE') ON CONFLICT DO NOTHING",
                T,
                C,
            )
            for migration in (
                "028_refusal_codes_parity.sql",
                "029_scoped_operator_reads.sql",
                "030_private_writer_consolidation.sql",
            ):
                step = migration
                await _apply_migration(db.conn, migration)
        except asyncpg.PostgresError as error:
            pytest.fail(
                f"PostgreSQL setup error in {step}: {_safe_postgres_diagnostics(error)}",
                pytrace=False,
            )
        yield L(db)

pytestmark = pytest.mark.integration

HOST = "s13-completion-test-host"
SERVICE = "s13-completion-test-service"
KEY_VERSION = "synthetic-v1"


async def _private_call(
    conn: asyncpg.Connection, sql: str, *args, scope: tuple[str, str] | None = None,
):
    async with conn.transaction():
        await conn.execute('SET LOCAL ROLE "business_ai_private_writer"')
        if scope is not None:
            # Direct private-writer functions require the same transaction-local scope context
            # as SqlChangeLedger.invoke. Their assert_scope checks still enforce this role's
            # tenant/company membership; this only arranges the context for this disposable call.
            await conn.fetchval(
                "SELECT pg_catalog.set_config('change_ledger.tenant_id',$1,true),"
                "pg_catalog.set_config('change_ledger.company_id',$2,true)",
                *scope,
            )
        return await conn.fetchval(sql, *args)


async def _seed_static_preconditions(ledger: L) -> tuple[str, int, str]:
    """Fixture-only READY and synthetic service/key bindings in this invocation-owned DB."""
    conn = ledger.conn
    base = hashlib.sha256(f"s13-completion-{uuid.uuid4()}".encode()).hexdigest()
    session_user = await conn.fetchval("SELECT session_user::text")
    # Synthetic trust fixtures intentionally span the disposable PostgreSQL clock, which may
    # differ from the Windows host clock running pytest.
    valid_from = datetime(2000, 1, 1, tzinfo=UTC)
    valid_until = datetime(2100, 1, 1, tzinfo=UTC)
    await conn.execute(
        "INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,"
        "target_class,epoch) VALUES($1,$2,$3,'org-1','DISPOSABLE_CLONE',1)", T, C, base,
    )
    # Disposable-fixture authorization context for direct private-writer finalizer calls.
    # Production role membership/grants are not modified; row_in_scope still enforces the scope.
    await conn.execute(
        "INSERT INTO change_ledger.role_scope(role_name,tenant_id,company_id) VALUES($1,$2,$3) "
        "ON CONFLICT DO NOTHING",
        "business_ai_private_writer", T, C,
    )
    # The physical slot is a static test precondition. Admission itself must claim it only through
    # private_writer_admit_v1; the fixture starts empty and open.
    await conn.execute(
        "INSERT INTO change_ledger.physical_base_slots(base_fingerprint) VALUES($1)", base,
    )
    # This is a static test precondition only. It is not evidence that recovery can produce READY.
    await conn.execute(
        "UPDATE change_ledger.lifecycle_fences SET state='READY',epoch=1,reason='TEST_FIXTURE' "
        "WHERE tenant_id=$1 AND company_id=$2", T, C,
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_service_bindings(\"session_user\",base_fingerprint,"
        "writer_service_id,writer_host_id) VALUES($1,$2,$3,$4)", session_user, base, SERVICE, HOST,
    )
    await conn.execute(
        "UPDATE change_ledger.verifier_keys SET role_name='checkpoint_role',key_algorithm='ED25519',"
        "key_material=$3,status='ACTIVE' WHERE tenant_id=$1 AND company_id=$2 AND key_id='vk-chk'",
        T, C, pub_hex("vk-chk"),
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_signer_key_versions(key_id,key_version,public_key,"
        "signer_role,service_id,host_id,valid_from,valid_until) VALUES($1,$2,$3,'checkpoint_signer',"
        "$4,$5,$6,$7)", "vk-chk", KEY_VERSION, bytes.fromhex(pub_hex("vk-chk")), SERVICE, HOST,
        valid_from, valid_until,
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_signer_key_scopes(key_id,key_version,tenant_id,company_id,"
        "organization_ref,base_fingerprint) VALUES($1,$2,$3,$4,'org-1',$5)",
        "vk-chk", KEY_VERSION, T, C, base,
    )
    instance_id = str(uuid.uuid4())
    startup = await _private_call(
        conn,
        "SELECT pg_catalog.to_jsonb(change_ledger.private_writer_startup_recovery_state_v1($1::text))",
        instance_id,
    )
    if isinstance(startup, str):
        startup = json.loads(startup)
    assert startup["service_instance_id"] == instance_id
    assert int(startup["service_epoch"]) == 1 and startup["readiness_ref"] is not None
    return base, 1, instance_id


async def _seed_failed_verify_parent(
    ledger: L, base: str, target: str,
) -> uuid.UUID:
    """Fixture-only historical parent facts; runtime repair/claim/terminal paths stay real."""
    parent_id = uuid.uuid4()
    await ledger.conn.execute(
        "INSERT INTO change_ledger.records "
        "(change_id,tenant_id,company_id,base_fingerprint,organization_ref,kind,requester,"
        "request_id,payload_digest,target_ref,target_version,lifecycle,authorization_state,"
        "execution_state,verification_state,call_ownership,attribution,effect_known,"
        "reservation_state,dispatch_state,auth_epoch_at_proposal,expires_at) "
        "VALUES($1,$2,$3,$4,'org-1','POST','clt_alice',$5,$6,$7,'v1','VALIDATED',"
        "'APPROVED','APPLIED','FAILED_VERIFY','PROVEN_FINISHED','PROVEN','YES',"
        "'CONSUMED','NOT_PERMITTED',1,pg_catalog.clock_timestamp()+interval '1 hour')",
        parent_id, T, C, base, f"s13-repair-parent-{parent_id.hex}",
        hashlib.sha256(f"synthetic-parent-{parent_id}".encode()).hexdigest(), target,
    )
    await ledger.conn.execute(
        "INSERT INTO change_ledger.target_locks "
        "(tenant_id,company_id,base_fingerprint,target_ref,owner_change_id) "
        "VALUES($1,$2,$3,$4,$5)", T, C, base, target, parent_id,
    )
    await ledger.conn.execute(
        "INSERT INTO change_ledger.holds "
        "(tenant_id,company_id,base_fingerprint,cause,change_id) "
        "VALUES($1,$2,$3,'FAILED_VERIFY_HALT',$4)", T, C, base, parent_id,
    )
    return parent_id


async def _admitted_attempt(
    ledger: L, label: str, *, with_repair_parent: bool = False,
) -> dict[str, object]:
    conn = ledger.conn
    base, epoch, instance_id = await _seed_static_preconditions(ledger)
    scope = Scope(T, C)
    target_ref = f"s13-target-{label}-{uuid.uuid4().hex}"
    repair_parent_id = (
        await _seed_failed_verify_parent(ledger, base, target_ref) if with_repair_parent else None
    )
    if repair_parent_id is not None:
        parent = await conn.fetchrow(
            "SELECT target_ref FROM change_ledger.records WHERE change_id=$1", repair_parent_id,
        )
        assert parent is not None and parent["target_ref"] == target_ref
        change_id = await ledger.approved(
            request_id=f"s13-completion-{label}-{uuid.uuid4().hex}", kind="UNPOST", base=base,
            target=target_ref, parent=repair_parent_id, repair_for=repair_parent_id,
            approver="clt_carol",
        )
    else:
        change_id = await ledger.approved(
            request_id=f"s13-completion-{label}-{uuid.uuid4().hex}", kind="POST", base=base,
            target=target_ref,
        )
    budget = await conn.fetchrow("SELECT * FROM change_ledger.change_budget WHERE change_id=$1", change_id)
    requester = SqlChangeLedger(
        conn, actors={"requester": "clt_alice", "worker": "clt_wrk"},
        private_writer_schema_enabled=True,
    )
    token = await requester.claim(
        scope, change_id, key_hash="9" * 64 if repair_parent_id is not None else None,
        grant_id=budget["grant_id"], amount=budget["amount"],
        counts_create_update=budget["counts_create_update"], counts_post=budget["counts_post"],
    )
    assert token is not None
    assert await requester.observe_target(scope, token["token_id"], base, "DISPOSABLE_CLONE") is True
    call_id = uuid.uuid4()
    await requester.begin_apply(scope, token["token_id"], call_id, HOST, f"session-{label}")
    # POST has no body, so the public verifier records the canonical empty-object wire payload.
    # private_writer_admit_v1 requires this generation-bound verification before admission.
    assert await requester.verify_dispatch_payload(scope, change_id, token["generation"], None) is True
    head = await ledger.head()
    await ledger.checkpoint()
    intent = await requester.dispatch_intent_for_call(scope, call_id)
    assert intent is not None
    checkpoint = await conn.fetchrow(
        "SELECT cp.seq,cp.ledger_seq,cp.head_hash,cp.sink_kind,cp.read_back_confirmed,cp.verified,"
        "cp.written_by,e.seq AS matching_event_seq,e.hash AS matching_event_hash,"
        "(SELECT max(seq) FROM change_ledger.events WHERE tenant_id=$1 AND company_id=$2 "
        "AND change_id=$3 AND event_type='APPLYING') AS applying_seq "
        "FROM change_ledger.checkpoints cp JOIN change_ledger.events e "
        "ON e.tenant_id=cp.tenant_id AND e.company_id=cp.company_id AND e.seq=cp.ledger_seq "
        "AND e.hash=cp.head_hash WHERE cp.tenant_id=$1 AND cp.company_id=$2 "
        "AND cp.sink_kind='REAL' AND cp.read_back_confirmed AND cp.verified "
        "AND cp.written_by IS NOT NULL AND cp.ledger_seq >= (SELECT max(seq) FROM change_ledger.events "
        "WHERE tenant_id=$1 AND company_id=$2 AND change_id=$3 AND event_type='APPLYING') "
        "ORDER BY cp.seq DESC LIMIT 1",
        T, C, change_id,
    )
    assert checkpoint is not None, "issue_permit has no qualifying written/read-back checkpoint"
    checkpoint_seq = checkpoint["seq"]
    assert checkpoint_seq > 0 and checkpoint_seq != checkpoint["ledger_seq"]
    permit_id = uuid.uuid4()
    permit_digest = hashlib.sha256(
        f"{change_id}:{token['generation']}:{checkpoint_seq}".encode(),
    ).hexdigest()
    signature = sign_hex("vk-chk", "change-ledger-permit|v1|" + permit_digest)
    assert checkpoint is not None and checkpoint["sink_kind"] == "REAL"
    assert checkpoint["read_back_confirmed"] is True and checkpoint["verified"] is True
    assert checkpoint["written_by"] is not None
    assert checkpoint["matching_event_seq"] == checkpoint["ledger_seq"]
    assert checkpoint["matching_event_hash"] == checkpoint["head_hash"]
    assert checkpoint["ledger_seq"] >= checkpoint["applying_seq"]
    signer = await conn.fetchrow(
        "SELECT signer_role,public_key,valid_from,valid_until FROM change_ledger.private_writer_signer_key_versions "
        "WHERE key_id='vk-chk' AND key_version=$1", KEY_VERSION,
    )
    assert signer is not None and signer["signer_role"] == "checkpoint_signer"
    assert await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes "
        "WHERE key_id='vk-chk' AND key_version=$1 AND tenant_id=$2 AND company_id=$3 "
        "AND organization_ref='org-1' AND base_fingerprint=$4)", KEY_VERSION, T, C, base,
    ) is True
    verifier = await conn.fetchrow(
        "SELECT role_name,key_algorithm,key_material,status FROM change_ledger.verifier_keys "
        "WHERE tenant_id=$1 AND company_id=$2 AND key_id='vk-chk'", T, C,
    )
    assert verifier is not None and tuple(verifier) == (
        "checkpoint_role", "ED25519", pub_hex("vk-chk"), "ACTIVE",
    )
    db_now = await conn.fetchval("SELECT clock_timestamp()")
    assert signer["valid_from"] <= db_now < signer["valid_until"]
    assert await conn.fetchval(
        "SELECT change_ledger.signature_ok('ED25519',$1,$2,$3)",
        pub_hex("vk-chk"), "change-ledger-permit|v1|" + permit_digest, signature,
    ) is True
    assert requester._actors["worker"] == "clt_wrk"
    assert await conn.fetchval(
        "SELECT NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations "
        "WHERE key_id='vk-chk' AND key_version=$1 AND revoked_at<=clock_timestamp())",
        KEY_VERSION,
    ) is True, "checkpoint signer has a revocation effective at the PostgreSQL clock"
    permit_before = await conn.fetchrow(
        "SELECT state,call_id,generation,checkpoint_seq,permit_digest,signer_key_id,signature "
        "FROM change_ledger.dispatch_permits WHERE change_id=$1 AND generation=$2",
        change_id, token["generation"],
    )
    assert permit_before is not None and permit_before["state"] == "NOT_PERMITTED", permit_before
    assert permit_before["call_id"] == call_id and permit_before["checkpoint_seq"] is None, permit_before
    assert permit_before["permit_digest"] is None and permit_before["signer_key_id"] is None, permit_before
    await requester.issue_permit_s13(
        scope, change_id, token["generation"], intent["dispatch_intent_id"], permit_id,
        "vk-chk", KEY_VERSION, signature,
    )
    identity = await conn.fetchrow(
        "SELECT i.tenant_id,i.company_id,i.organization_ref,i.change_id::text AS change_id,"
        "i.claim_generation AS generation,i.call_id::text AS call_id,i.operation_kind AS operation,"
        "i.target_ref,i.expected_pre_version AS target_version,i.auth_epoch AS epoch,i.payload_digest,"
        "b.permit_id::text AS permit_id,b.permit_digest,i.base_fingerprint,"
        "i.repair_authorization_id::text AS repair_authorization_id,i.dispatch_intent_id::text AS intent_id "
        "FROM change_ledger.private_writer_dispatch_intents i JOIN change_ledger.private_writer_permit_bindings b "
        "USING(dispatch_intent_id) WHERE i.dispatch_intent_id=$1", intent["dispatch_intent_id"],
    )
    assert identity is not None
    identity = dict(identity)
    identity["host_id"] = HOST
    identity["repair_authorization_id"] = identity["repair_authorization_id"]
    identity_json = json.dumps(identity)
    admission_preconditions = await conn.fetchrow(
        "SELECT (SELECT pg_catalog.to_jsonb(x) FROM change_ledger.physical_base_slots x "
        "WHERE x.base_fingerprint=$1) AS physical_slot, "
        "change_ledger.blocking_hold($2,$3,$1,NULL) AS blocking_hold, "
        "(SELECT pg_catalog.to_jsonb(x) FROM change_ledger.lifecycle_fences x "
        "WHERE x.tenant_id=$2 AND x.company_id=$3) AS lifecycle, "
        "(SELECT pg_catalog.to_jsonb(x) FROM change_ledger.private_writer_serving_fences x "
        "WHERE x.writer_service_id=$4 AND x.base_fingerprint=$1) AS serving_fence, "
        "(SELECT pg_catalog.to_jsonb(x) FROM change_ledger.dispatch_permits x "
        "WHERE x.change_id=$5 AND x.generation=$6) AS dispatch_permit",
        base, T, C, SERVICE, change_id, token["generation"],
    )
    admitted = await _private_call(
        conn,
        "SELECT pg_catalog.to_jsonb(change_ledger.private_writer_admit_v1("
        "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1,$1::jsonb),$2,$3))",
        identity_json, instance_id, epoch,
    )
    if isinstance(admitted, str):
        admitted = json.loads(admitted)
    # Keep the exact database decision and its first relevant static predicates in the failure
    # artifact. This distinguishes fixture incompleteness from application or migration defects.
    assert admitted["state"] == "ACCEPTED_NOT_INVOKED" and admitted["newly_admitted"] is True, (
        f"private_writer_admit_v1 returned state={admitted['state']!r}, "
        f"refusal_code={admitted['refusal_code']!r}, "
        f"preconditions={dict(admission_preconditions)!r}, identity={identity!r}"
    )
    cas_id = admitted["dispatch_cas_id"]
    return {
        "conn": conn, "identity": identity, "identity_json": identity_json,
        "change_id": change_id, "generation": token["generation"], "call_id": call_id,
        "cas_id": cas_id, "instance_id": instance_id, "epoch": epoch,
        "intent_id": str(intent["dispatch_intent_id"]), "base": base,
        "repair_parent_id": repair_parent_id,
    }


async def _seed_evidence(flow: dict[str, object], kind: str) -> dict[str, str]:
    """Schema-owner synthetic typed projections; never used as evidence-ingest qualification."""
    conn: asyncpg.Connection = flow["conn"]
    identity = flow["identity"]
    attempt = await conn.fetchrow(
        "SELECT * FROM change_ledger.dispatch_attempts WHERE dispatch_cas_id=$1", flow["cas_id"],
    )
    assert attempt is not None
    now = datetime.now(UTC)
    valid_from = datetime(2000, 1, 1, tzinfo=UTC)
    valid_until = datetime(2100, 1, 1, tzinfo=UTC)
    refs = {name: f"synthetic-{name}-{uuid.uuid4()}" for name in ("receipt", "outcome", "completion")}
    writer_key, outcome_key = "s13-writer-projection", "s13-outcome-projection"
    for key_id, signer_role in ((writer_key, "writer_receipt"), (outcome_key, "verification_worker")):
        await conn.execute(
            "INSERT INTO change_ledger.private_writer_signer_key_versions(key_id,key_version,public_key,"
            "signer_role,service_id,host_id,valid_from,valid_until) VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
            key_id, KEY_VERSION, hashlib.sha256(key_id.encode()).digest(), signer_role, SERVICE, HOST,
            valid_from, valid_until,
        )
        # Fixture-only scope binding for these synthetic evidence signers. This does not exercise
        # evidence-ingest authorization or qualify a real signing key.
        await conn.execute(
            "INSERT INTO change_ledger.private_writer_signer_key_scopes(key_id,key_version,tenant_id,"
            "company_id,organization_ref,base_fingerprint) VALUES($1,$2,$3,$4,$5,$6)",
            key_id, KEY_VERSION, identity["tenant_id"], identity["company_id"],
            identity["organization_ref"], identity["base_fingerprint"],
        )
    common = {
        "tenant_id": identity["tenant_id"], "company_id": identity["company_id"],
        "organization_ref": identity["organization_ref"], "base_fingerprint": identity["base_fingerprint"],
        "change_id": flow["change_id"], "claim_generation": identity["generation"],
        "dispatch_generation": attempt["dispatch_generation"], "call_id": flow["call_id"],
        "dispatch_cas_id": flow["cas_id"], "dispatch_intent_id": attempt["dispatch_intent_id"],
        "operation_kind": identity["operation"], "approval_digest": attempt["approval_digest"],
        "payload_digest": identity["payload_digest"], "permit_id": uuid.UUID(identity["permit_id"]),
        "permit_digest": identity["permit_digest"], "target_ref": identity["target_ref"],
        "pre_version": identity["target_version"], "auth_epoch": identity["epoch"],
        "repair_authorization_id": identity["repair_authorization_id"], "signer_key_version": KEY_VERSION,
        "signer_service_id": SERVICE, "signer_host_id": HOST, "signed_at": now,
        "trust_registry_revision": 1, "verified_at": now, "validator_build_id": "synthetic-e2e-fixture",
        "process_instance_id": attempt["writer_process_instance_id"],
        "session_instance_id": attempt["onec_session_instance_id"],
    }
    if kind == "success":
        receipt_id = uuid.uuid4()
        projections = [
            {"record_type":"DISPATCH_RECEIPT_V1","writer_receipt_id":receipt_id,
             "writer_invocation_stage":"ENTERED","writer_result_class":"CALL_RETURNED_SUCCESS",
             "writer_call_returned":True,"writer_returned_at":now,"writer_returned_target_ref":identity["target_ref"],
             "writer_returned_version":"v2","signer_key_id":writer_key,"signer_role":"writer_receipt"},
            {"record_type":"OUTCOME_EVIDENCE_V1","outcome_evidence_version":1,
             "outcome_dispatch_receipt_id":receipt_id,
             "outcome_target_ref":identity["target_ref"],"outcome_pre_version":identity["target_version"],
             "outcome_observed_version":"v2","outcome_expected_effect_digest":"a"*64,
             "outcome_observed_effect_digest":"a"*64,"outcome_fields_match":True,
             "outcome_movements_match":True,"outcome_observation_complete":True,
             "outcome_reader_health":"HEALTHY","outcome_effect_presence":"PRESENT",
             "outcome_effect_identity":"MATCH","outcome_version_relation":"ADVANCED",
             "outcome_attribution_result":"PROVEN",
             "outcome_attribution_evidence_ref":f"synthetic-attribution-{uuid.uuid4()}",
             "outcome_uncertainty_count":0,
             "outcome_completion_proof_class":"WRITER_CALL_RETURNED",
             "signer_key_id":outcome_key,"signer_role":"verification_worker"},
            {"record_type":"COMPLETION_PROOF_V1","completion_proof_id":uuid.uuid4(),
             "completion_proof_class":"WRITER_CALL_RETURNED","signer_key_id":writer_key,
             "signer_role":"writer_receipt"},
        ]
    else:
        no_effect_digest = hashlib.sha256(b"synthetic-pre-write-no-effect").hexdigest()
        projections = [{"record_type":"DISPATCH_NO_ENTRY_RECEIPT_V1",
                       "writer_receipt_id":uuid.uuid4(),"writer_invocation_stage":"NOT_INVOKED",
                       "writer_result_class":"PRE_WRITE_NO_EFFECT","writer_call_returned":False,
                       "no_effect_evidence_digest":no_effect_digest,"signer_key_id":writer_key,
                       "signer_role":"writer_receipt"}]
    for index, projection in enumerate(projections):
        signed = f"synthetic-{kind}-{index}-{uuid.uuid4()}".encode()
        digest = hashlib.sha256(signed).hexdigest()
        values = {**common, **projection, "evidence_ref":refs["receipt"] if index == 0 else refs["outcome"] if index == 1 else refs["completion"],
                  "signed_bytes":signed,"signed_bytes_sha256":hashlib.sha256(signed).digest(),"record_digest":digest}
        signer = await conn.fetchrow(
            "SELECT signer_role,service_id,host_id,valid_from,valid_until "
            "FROM change_ledger.private_writer_signer_key_versions "
            "WHERE key_id=$1 AND key_version=$2", values["signer_key_id"], values["signer_key_version"],
        )
        assert signer is not None and (
            values["signer_role"], values["signer_service_id"], values["signer_host_id"],
        ) == (signer["signer_role"], signer["service_id"], signer["host_id"]), (
            f"projection index={index} type={values['record_type']} signer identity mismatch"
        )
        assert signer["valid_from"] <= values["signed_at"] < signer["valid_until"]
        assert await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_scopes "
            "WHERE key_id=$1 AND key_version=$2 AND tenant_id=$3 AND company_id=$4 "
            "AND organization_ref=$5 AND base_fingerprint=$6)",
            values["signer_key_id"], values["signer_key_version"], values["tenant_id"],
            values["company_id"], values["organization_ref"], values["base_fingerprint"],
        ) is True, f"projection index={index} type={values['record_type']} signer scope missing"
        assert await conn.fetchval(
            "SELECT NOT EXISTS(SELECT 1 FROM change_ledger.private_writer_signer_key_revocations "
            "WHERE key_id=$1 AND key_version=$2 AND revoked_at<=$3)",
            values["signer_key_id"], values["signer_key_version"], values["signed_at"],
        ) is True, f"projection index={index} type={values['record_type']} signer already revoked"
        if values["record_type"] == "OUTCOME_EVIDENCE_V1":
            assert values["outcome_evidence_version"] == 1, (
                f"projection index={index} type=OUTCOME_EVIDENCE_V1 requires version 1"
            )
        columns = list(values)
        placeholders = ",".join(f"${i}" for i in range(1,len(columns)+1))
        try:
            await conn.execute(
                f"INSERT INTO change_ledger.private_writer_evidence({','.join(columns)}) VALUES({placeholders})",
                *(values[column] for column in columns),
            )
        except asyncpg.PostgresError as exc:
            pytest.fail(
                f"synthetic evidence projection index={index} type={values['record_type']} rejected: {exc}",
            )
    return refs


async def _finalizer(
    flow: dict[str, object], fn: str, *extra, service_epoch: int | None = None,
):
    identity_json = flow["identity_json"]
    conn: asyncpg.Connection = flow["conn"]
    sql = (
        "SELECT change_ledger." + fn + "(pg_catalog.jsonb_populate_record("
        "NULL::change_ledger.private_writer_identity_v1,$1::jsonb),$2::uuid,$3::text,$4::bigint,$5::text"
    )
    active_epoch = flow["epoch"] if service_epoch is None else service_epoch
    args = [identity_json, flow["cas_id"], flow["instance_id"], active_epoch, *extra]
    extra_params = ",".join(f"${i}" for i in range(6,len(args)+1))
    sql += ("," + extra_params if extra_params else "") + ")"
    identity = flow["identity"]
    return await _private_call(
        conn, sql, *args, scope=(identity["tenant_id"], identity["company_id"]),
    )


async def _private_terminal_receipt(flow: dict[str, object], receipt_ref: str) -> str:
    conn: asyncpg.Connection = flow["conn"]
    return await _private_call(
        conn,
        "SELECT change_ledger.private_writer_record_terminal_v1("
        "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1,$1::jsonb),"
        "$2::uuid,$3::text,$4::text)",
        flow["identity_json"], flow["cas_id"], flow["instance_id"], receipt_ref,
    )


async def _assert_success_finalizer_preconditions(
    flow: dict[str, object], refs: dict[str, str],
) -> None:
    """Mirror the exact SQL authorization/evidence predicates before the success finalizer."""
    conn: asyncpg.Connection = flow["conn"]
    attempt = await conn.fetchrow(
        "SELECT * FROM change_ledger.dispatch_attempts WHERE dispatch_cas_id=$1", flow["cas_id"],
    )
    record = await conn.fetchrow(
        "SELECT * FROM change_ledger.records WHERE change_id=$1", flow["change_id"],
    )
    permit = await conn.fetchrow(
        "SELECT * FROM change_ledger.dispatch_permits WHERE change_id=$1 AND generation=$2",
        flow["change_id"], flow["generation"],
    )
    evidence_rows = await conn.fetch(
        "SELECT * FROM change_ledger.private_writer_evidence WHERE evidence_ref=ANY($1::text[])",
        [refs["receipt"], refs["outcome"], refs["completion"]],
    )
    evidence = {row["evidence_ref"]: row for row in evidence_rows}
    receipt, outcome, completion = (
        evidence.get(refs[name]) for name in ("receipt", "outcome", "completion")
    )
    assert attempt is not None and record is not None and permit is not None
    assert receipt is not None and outcome is not None and completion is not None

    bound = (
        "dispatch_cas_id", "dispatch_intent_id", "change_id", "call_id", "tenant_id",
        "company_id", "organization_ref", "base_fingerprint", "operation_kind",
        "approval_digest", "payload_digest", "permit_id", "permit_digest", "target_ref",
        "pre_version", "auth_epoch", "repair_authorization_id",
    )
    expected = tuple(
        attempt["expected_target_ref"] if field == "target_ref"
        else attempt["expected_pre_version"] if field == "pre_version"
        else attempt[field]
        for field in bound
    )
    checks = {
        "record active/APPLYING/DISPATCHED":
            record["claim_generation"] == attempt["claim_generation"]
            and record["base_fingerprint"] == attempt["base_fingerprint"]
            and record["execution_state"] in ("APPLYING", "APPLIED")
            and record["dispatch_state"] == "DISPATCHED",
        "permit dispatched and exact identity":
            permit["state"] == "DISPATCHED" and permit["call_id"] == attempt["call_id"]
            and permit["writer_host"] == attempt["writer_host_id"]
            and permit["lifecycle_epoch"] == attempt["auth_epoch"]
            and permit["permit_digest"] == attempt["permit_digest"],
        "attempt still entered":
            attempt["state"] == "POSSIBLY_EXECUTING"
            and attempt["com_entry_authorized_at"] is not None,
        "receipt full attempt binding": tuple(receipt[field] for field in bound) == expected,
        "outcome full attempt binding": tuple(outcome[field] for field in bound) == expected,
        "completion full attempt binding": tuple(completion[field] for field in bound) == expected,
        "receipt record type/role/result/stage/return":
            receipt["record_type"] == "DISPATCH_RECEIPT_V1"
            and receipt["signer_role"] == "writer_receipt"
            and receipt["writer_result_class"] == "CALL_RETURNED_SUCCESS"
            and receipt["writer_invocation_stage"] in ("ENTERED", "INVOKED")
            and receipt["writer_call_returned"] is True,
        "receipt process/session binding":
            receipt["process_instance_id"] == attempt["writer_process_instance_id"]
            and receipt["session_instance_id"] == attempt["onec_session_instance_id"],
        "outcome type/role/receipt/version":
            outcome["record_type"] in ("OUTCOME_EVIDENCE_V1", "OUTCOME_EVIDENCE_V2", "OUTCOME_EVIDENCE_V3")
            and outcome["signer_role"] == "verification_worker"
            and outcome["outcome_dispatch_receipt_id"] == receipt["writer_receipt_id"]
            and outcome["outcome_observed_version"] == receipt["writer_returned_version"],
        "outcome positive classifications":
            outcome["outcome_observation_complete"] is True
            and outcome["outcome_fields_match"] is True
            and outcome["outcome_movements_match"] is True
            and outcome["outcome_reader_health"] == "HEALTHY"
            and outcome["outcome_effect_presence"] == "PRESENT"
            and outcome["outcome_effect_identity"] == "MATCH"
            and outcome["outcome_attribution_result"] == "PROVEN"
            and bool(outcome["outcome_attribution_evidence_ref"])
            and outcome["outcome_expected_effect_digest"] == outcome["outcome_observed_effect_digest"]
            and outcome["outcome_uncertainty_count"] == 0,
        "outcome completion class link":
            outcome["outcome_completion_proof_class"] == completion["completion_proof_class"],
        "completion type/class/role/process":
            completion["record_type"] == "COMPLETION_PROOF_V1"
            and completion["completion_proof_class"] == "WRITER_CALL_RETURNED"
            and completion["signer_role"] == "writer_receipt"
            and completion["signer_service_id"] == attempt["writer_service_id"]
            and completion["signer_host_id"] == attempt["writer_host_id"]
            and completion["process_instance_id"] == attempt["writer_process_instance_id"],
        "POST target/pre-version/advanced checks":
            attempt["operation_kind"] == "POST"
            and receipt["target_ref"] == attempt["expected_target_ref"]
            and receipt["pre_version"] == attempt["expected_pre_version"]
            and outcome["outcome_pre_version"] == attempt["expected_pre_version"]
            and outcome["outcome_target_ref"] == attempt["expected_target_ref"]
            and outcome["outcome_observed_version"] != attempt["expected_pre_version"]
            and outcome["outcome_version_relation"] == "ADVANCED",
    }
    failed = [name for name, matched in checks.items() if not matched]
    assert not failed, f"success finalizer predicate mismatch: first={failed[0] if failed else None}; checks={checks!r}"


async def _attempt_snapshot(flow: dict[str, object]) -> tuple:
    conn: asyncpg.Connection = flow["conn"]
    change_id, cas_id, base = flow["change_id"], flow["cas_id"], flow["base"]
    identity = flow["identity"]
    names = (
        ("records", "change_id", change_id),
        ("dispatch_permits", "change_id", change_id),
        ("reservations", "change_id", change_id),
        ("dispatch_attempts", "dispatch_cas_id", cas_id),
        ("private_writer_attempt_evidence", "dispatch_cas_id", cas_id),
        ("physical_base_slots", "base_fingerprint", base),
        ("key_locks", "owner_change_id", change_id),
        ("writer_leases", "owner_change_id", change_id),
        ("holds", "change_id", change_id),
        ("events", "change_id", change_id),
    )
    result = []
    for table, column, value in names:
        rows = await conn.fetch(
            f'SELECT pg_catalog.to_jsonb(x) FROM change_ledger."{table}" x WHERE "{column}"=$1', value,
        )
        result.append((table, tuple(sorted(json.dumps(row[0], sort_keys=True, default=str) for row in rows))))
    # Snapshot the target lock by resource identity, not owner. This catches an owner mismatch
    # that would otherwise disappear from the child-owned resource query above.
    target_rows = await conn.fetch(
        "SELECT pg_catalog.to_jsonb(x) FROM change_ledger.target_locks x "
        "WHERE tenant_id=$1 AND company_id=$2 AND base_fingerprint=$3 AND target_ref=$4",
        identity["tenant_id"], identity["company_id"], base, identity["target_ref"],
    )
    result.append(("target_locks_by_resource", tuple(sorted(
        json.dumps(row[0], sort_keys=True, default=str) for row in target_rows
    ))))
    conflicting_owner_id = flow.get("conflicting_owner_id")
    if conflicting_owner_id is not None:
        owner_rows = await conn.fetch(
            "SELECT pg_catalog.to_jsonb(x) FROM change_ledger.records x WHERE change_id=$1",
            conflicting_owner_id,
        )
        result.append(("conflicting_target_lock_owner_record", tuple(sorted(
            json.dumps(row[0], sort_keys=True, default=str) for row in owner_rows
        ))))
        owner_events = await conn.fetch(
            "SELECT pg_catalog.to_jsonb(x) FROM change_ledger.events x WHERE change_id=$1",
            conflicting_owner_id,
        )
        result.append(("conflicting_target_lock_owner_events", tuple(sorted(
            json.dumps(row[0], sort_keys=True, default=str) for row in owner_events
        ))))
    repair_parent_id = flow.get("repair_parent_id")
    if repair_parent_id is not None:
        for table, col in (("records", "change_id"), ("holds", "change_id"), ("events", "change_id")):
            parent_rows = await conn.fetch(
                f'SELECT pg_catalog.to_jsonb(x) FROM change_ledger."{table}" x WHERE "{col}"=$1',
                repair_parent_id,
            )
            result.append((f"repair_parent_{table}", tuple(sorted(
                json.dumps(row[0], sort_keys=True, default=str) for row in parent_rows
            ))))
    return tuple(result)


async def test_s13_completion_outcome_target_lock_owner_mismatch_refuses_without_delta(
    ledger: L,
) -> None:
    flow = await _admitted_attempt(ledger, "lock-owner-mismatch")
    conn: asyncpg.Connection = flow["conn"]
    refs = await _seed_evidence(flow, "pre-write")
    identity = flow["identity"]
    # Give the target lock a real, in-scope record owner. This is an owner-fixture mutation in
    # the disposable schema; the accepted service call itself must notice and refuse atomically.
    conflict_owner = await ledger.approved(
        request_id=f"s13-lock-owner-conflict-{uuid.uuid4().hex}", kind="POST",
        base=flow["base"], target=identity["target_ref"],
    )
    await conn.execute(
        "UPDATE change_ledger.target_locks SET owner_change_id=$5 "
        "WHERE tenant_id=$1 AND company_id=$2 AND base_fingerprint=$3 AND target_ref=$4",
        identity["tenant_id"], identity["company_id"], flow["base"], identity["target_ref"],
        conflict_owner,
    )
    flow["conflicting_owner_id"] = conflict_owner
    lock = await conn.fetchrow(
        "SELECT owner_change_id FROM change_ledger.target_locks WHERE tenant_id=$1 "
        "AND company_id=$2 AND base_fingerprint=$3 AND target_ref=$4",
        identity["tenant_id"], identity["company_id"], flow["base"], identity["target_ref"],
    )
    assert lock is not None and lock["owner_change_id"] == conflict_owner
    before = await _attempt_snapshot(flow)
    try:
        await _finalizer(
            flow, "private_writer_record_recovered_not_invoked_v1", refs["receipt"],
        )
    except asyncpg.PostgresError as error:
        assert "LOCK_PLAN_STALE" in str(error), f"unexpected stable refusal: {error}"
    else:
        after_unexpected_accept = await _attempt_snapshot(flow)
        pytest.fail(
            "target-lock owner mismatch was accepted; expected LOCK_PLAN_STALE before terminal DML; "
            f"before={before!r}; after={after_unexpected_accept!r}"
        )
    assert await _attempt_snapshot(flow) == before, (
        "target-lock owner mismatch refusal changed attempt, evidence, resources, owner record, or events"
    )


async def test_s13_completion_outcome_normal_success_finalizer(ledger: L) -> None:
    flow = await _admitted_attempt(ledger, "success")
    conn: asyncpg.Connection = flow["conn"]
    assert await _private_call(
        conn,
        "SELECT change_ledger.private_writer_mark_invoking_v1("
        "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1,$1::jsonb),"
        "$2::uuid,$3::text,$4::bigint)",
        flow["identity_json"], flow["cas_id"], flow["instance_id"], flow["epoch"],
    ) is True
    assert await _private_call(
        conn,
        "SELECT change_ledger.private_writer_begin_com_entry_v1("
        "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1,$1::jsonb),"
        "$2::uuid,$3::text,$4::bigint)",
        flow["identity_json"], flow["cas_id"], flow["instance_id"], flow["epoch"],
    ) is True
    refs = await _seed_evidence(flow, "success")
    before = await _attempt_snapshot(flow)
    with pytest.raises(asyncpg.PostgresError, match="STALE_EPOCH"):
        await _finalizer(
            flow, "private_writer_record_verified_success_v1",
            refs["receipt"], refs["outcome"], refs["completion"],
            service_epoch=flow["epoch"] + 1,
        )
    assert await _attempt_snapshot(flow) == before, "stale service epoch changed ledger state"
    assert await _private_terminal_receipt(flow, refs["receipt"]) == refs["receipt"]
    await _assert_success_finalizer_preconditions(flow, refs)
    assert await _finalizer(
        flow, "private_writer_record_verified_success_v1",
        refs["receipt"], refs["outcome"], refs["completion"],
    ) == refs["outcome"]
    after = await _attempt_snapshot(flow)
    assert after != before
    record = await conn.fetchrow(
        "SELECT execution_state,verification_state,call_ownership,attribution,reservation_state,dispatch_state "
        "FROM change_ledger.records WHERE change_id=$1",
        flow["change_id"],
    )
    assert tuple(record) == (
        "APPLIED", "VERIFIED", "PROVEN_FINISHED", "PROVEN", "CONSUMED", "DISPATCHED",
    )
    reservation = await conn.fetchrow(
        "SELECT state FROM change_ledger.reservations WHERE change_id=$1", flow["change_id"],
    )
    assert reservation is not None and reservation["state"] == "CONSUMED"
    for table in ("key_locks", "writer_leases", "target_locks"):
        assert await conn.fetchval(
            f'SELECT NOT EXISTS(SELECT 1 FROM change_ledger."{table}" WHERE owner_change_id=$1)',
            flow["change_id"],
        ) is True, f"success finalizer left owned rows in {table}"
    assert await conn.fetchval(
        "SELECT active_dispatch_cas_id IS NULL FROM change_ledger.physical_base_slots "
        "WHERE base_fingerprint=$1", flow["base"],
    ) is True
    evidence_digests = await conn.fetchrow(
        "SELECT max(record_digest) FILTER (WHERE evidence_ref=$1) AS receipt_digest, "
        "max(record_digest) FILTER (WHERE evidence_ref=$2) AS outcome_digest, "
        "max(record_digest) FILTER (WHERE evidence_ref=$3) AS completion_digest, "
        "max(writer_returned_version) FILTER (WHERE evidence_ref=$1) AS observed_version, "
        "max(target_ref) FILTER (WHERE evidence_ref=$1) AS observed_target_ref "
        "FROM change_ledger.private_writer_evidence WHERE evidence_ref=ANY($4::text[])",
        refs["receipt"], refs["outcome"], refs["completion"],
        [refs["receipt"], refs["outcome"], refs["completion"]],
    )
    event_rows = await conn.fetch(
        "SELECT event_type,payload->'private_writer' AS private_writer_payload "
        "FROM change_ledger.events WHERE change_id=$1 "
        "AND event_type IN ('COMPLETE_SUCCESS','VERIFY_VERIFIED') ORDER BY event_type",
        flow["change_id"],
    )
    assert [row["event_type"] for row in event_rows] == ["COMPLETE_SUCCESS", "VERIFY_VERIFIED"]
    event_payloads = {}
    for row in event_rows:
        event_payload = row["private_writer_payload"]
        if isinstance(event_payload, str):
            event_payload = json.loads(event_payload)
        event_payloads[row["event_type"]] = event_payload
    assert event_payloads["COMPLETE_SUCCESS"] == {
        "receipt_ref": refs["receipt"], "receipt_digest": evidence_digests["receipt_digest"],
        "outcome_ref": refs["outcome"], "outcome_digest": evidence_digests["outcome_digest"],
        "completion_ref": refs["completion"], "completion_digest": evidence_digests["completion_digest"],
    }
    assert event_payloads["VERIFY_VERIFIED"] == {
        "outcome_ref": refs["outcome"], "outcome_digest": evidence_digests["outcome_digest"],
        "completion_ref": refs["completion"], "completion_digest": evidence_digests["completion_digest"],
        "observed_version": evidence_digests["observed_version"],
        "observed_target_ref": evidence_digests["observed_target_ref"],
    }
    attempt = await conn.fetchrow(
        "SELECT state FROM change_ledger.dispatch_attempts WHERE dispatch_cas_id=$1", flow["cas_id"],
    )
    assert attempt["state"] == "TERMINAL_WITH_EVIDENCE"
    # Exact replay is idempotent: it returns the same reference and changes no snapshot/event.
    replay_snapshot = await _attempt_snapshot(flow)
    assert await _finalizer(
        flow, "private_writer_record_verified_success_v1",
        refs["receipt"], refs["outcome"], refs["completion"],
    ) == refs["outcome"]
    assert await _attempt_snapshot(flow) == replay_snapshot
    changed_snapshot = await _attempt_snapshot(flow)
    with pytest.raises(asyncpg.PostgresError, match="RECOVERY_EVIDENCE_REJECTED"):
        await _finalizer(
            flow, "private_writer_record_verified_success_v1",
            refs["receipt"] + "-changed", refs["outcome"], refs["completion"],
        )
    assert await _attempt_snapshot(flow) == changed_snapshot


async def test_s13_completion_outcome_pre_write_no_effect_finalizer(ledger: L) -> None:
    flow = await _admitted_attempt(ledger, "pre-write")
    conn: asyncpg.Connection = flow["conn"]
    refs = await _seed_evidence(flow, "pre-write")
    before = await _attempt_snapshot(flow)
    assert await _finalizer(
        flow, "private_writer_record_recovered_not_invoked_v1", refs["receipt"],
    ) == refs["receipt"]
    after = await _attempt_snapshot(flow)
    assert after != before
    projection = await conn.fetchrow(
        "SELECT record_type,writer_invocation_stage,writer_call_returned,no_effect_evidence_digest "
        "FROM change_ledger.private_writer_evidence WHERE evidence_ref=$1", refs["receipt"],
    )
    assert tuple(projection[:3]) == ("DISPATCH_NO_ENTRY_RECEIPT_V1", "NOT_INVOKED", False)
    assert projection["no_effect_evidence_digest"] == hashlib.sha256(
        b"synthetic-pre-write-no-effect",
    ).hexdigest()
    record = await conn.fetchrow(
        "SELECT execution_state,dispatch_state,reservation_state,verification_state "
        "FROM change_ledger.records WHERE change_id=$1", flow["change_id"],
    )
    assert tuple(record) == ("FAILED_APPLY", "DISPATCHED", "RELEASED", "NOT_VERIFIED")
    permit = await conn.fetchrow(
        "SELECT state,call_id,lifecycle_epoch,permit_digest FROM change_ledger.dispatch_permits "
        "WHERE change_id=$1 AND generation=$2", flow["change_id"], flow["generation"],
    )
    assert tuple(permit) == (
        "DISPATCHED", flow["call_id"], flow["epoch"], flow["identity"]["permit_digest"],
    )
    reservation = await conn.fetchrow(
        "SELECT state FROM change_ledger.reservations WHERE change_id=$1", flow["change_id"],
    )
    assert reservation is not None and reservation["state"] == "RELEASED"
    assert await conn.fetchval(
        "SELECT NOT EXISTS(SELECT 1 FROM change_ledger.key_locks WHERE owner_change_id=$1)",
        flow["change_id"],
    ) is True
    assert await conn.fetchval(
        "SELECT NOT EXISTS(SELECT 1 FROM change_ledger.writer_leases WHERE owner_change_id=$1)",
        flow["change_id"],
    ) is True
    assert await conn.fetchval(
        "SELECT NOT EXISTS(SELECT 1 FROM change_ledger.target_locks WHERE owner_change_id=$1)",
        flow["change_id"],
    ) is True
    assert await conn.fetchval(
        "SELECT active_dispatch_cas_id IS NULL FROM change_ledger.physical_base_slots "
        "WHERE base_fingerprint=$1", flow["base"],
    ) is True
    completion_event = await conn.fetchrow(
        "SELECT event_type,payload->'private_writer' AS private_writer_payload "
        "FROM change_ledger.events WHERE change_id=$1 AND event_type='COMPLETE_PRE_WRITE_REFUSAL'",
        flow["change_id"],
    )
    evidence = await conn.fetchrow(
        "SELECT record_digest,no_effect_evidence_digest FROM change_ledger.private_writer_evidence "
        "WHERE evidence_ref=$1", refs["receipt"],
    )
    assert completion_event is not None and evidence is not None
    event_payload = completion_event["private_writer_payload"]
    if isinstance(event_payload, str):
        event_payload = json.loads(event_payload)
    expected_private_writer_payload = {
        "no_entry_receipt_ref": refs["receipt"],
        "no_entry_receipt_digest": evidence["record_digest"],
        "no_effect_proof": {
            "receipt_ref": refs["receipt"],
            "receipt_digest": evidence["record_digest"],
            "no_effect_evidence_digest": evidence["no_effect_evidence_digest"],
        },
    }
    assert completion_event["event_type"] == "COMPLETE_PRE_WRITE_REFUSAL"
    assert event_payload == expected_private_writer_payload
    attempt = await conn.fetchrow(
        "SELECT state,com_entry_authorized_at FROM change_ledger.dispatch_attempts WHERE dispatch_cas_id=$1",
        flow["cas_id"],
    )
    assert tuple(attempt) == ("TERMINAL_WITH_EVIDENCE", None)
    assert await _private_call(
        conn,
        "SELECT change_ledger.private_writer_mark_invoking_v1("
        "pg_catalog.jsonb_populate_record(NULL::change_ledger.private_writer_identity_v1,$1::jsonb),"
        "$2::uuid,$3::text,$4::bigint)",
        flow["identity_json"], flow["cas_id"], flow["instance_id"], flow["epoch"],
    ) is False
    replay_snapshot = await _attempt_snapshot(flow)
    assert await _finalizer(
        flow, "private_writer_record_recovered_not_invoked_v1", refs["receipt"],
    ) == refs["receipt"]
    assert await _attempt_snapshot(flow) == replay_snapshot
    changed_snapshot = await _attempt_snapshot(flow)
    with pytest.raises(asyncpg.PostgresError, match="RECOVERY_EVIDENCE_REJECTED"):
        await _finalizer(
            flow, "private_writer_record_recovered_not_invoked_v1", refs["receipt"] + "-changed",
        )
    assert await _attempt_snapshot(flow) == changed_snapshot


async def test_s13_completion_outcome_repair_pre_write_hands_target_lock_back_to_parent(
    ledger: L,
) -> None:
    flow = await _admitted_attempt(ledger, "repair-pre-write", with_repair_parent=True)
    conn: asyncpg.Connection = flow["conn"]
    parent_id = flow["repair_parent_id"]
    assert parent_id is not None
    refs = await _seed_evidence(flow, "pre-write")
    identity = flow["identity"]
    parent_before = await conn.fetchrow(
        "SELECT pg_catalog.to_jsonb(r) FROM change_ledger.records r WHERE change_id=$1", parent_id,
    )
    hold_before = await conn.fetch(
        "SELECT pg_catalog.to_jsonb(h) FROM change_ledger.holds h WHERE change_id=$1 ORDER BY hold_id",
        parent_id,
    )
    parent_events_before = await conn.fetch(
        "SELECT pg_catalog.to_jsonb(e) FROM change_ledger.events e WHERE change_id=$1 ORDER BY seq",
        parent_id,
    )
    target_before = await conn.fetchrow(
        "SELECT owner_change_id FROM change_ledger.target_locks WHERE tenant_id=$1 AND company_id=$2 "
        "AND base_fingerprint=$3 AND target_ref=$4",
        identity["tenant_id"], identity["company_id"], flow["base"], identity["target_ref"],
    )
    assert target_before is not None and target_before["owner_change_id"] == flow["change_id"]
    child_key_lock = await conn.fetchrow(
        "SELECT pg_catalog.to_jsonb(k) FROM change_ledger.key_locks k WHERE owner_change_id=$1",
        flow["change_id"],
    )
    child_lease = await conn.fetchrow(
        "SELECT pg_catalog.to_jsonb(w) FROM change_ledger.writer_leases w WHERE owner_change_id=$1",
        flow["change_id"],
    )
    assert child_key_lock is not None and child_lease is not None
    sibling_base = hashlib.sha256(f"s13-repair-sibling-{uuid.uuid4()}".encode()).hexdigest()
    sibling_target = f"s13-sibling-{uuid.uuid4().hex}"
    await conn.execute(
        "INSERT INTO change_ledger.targets(tenant_id,company_id,base_fingerprint,organization_ref,"
        "target_class,epoch) VALUES($1,$2,$3,'org-1','DISPOSABLE_CLONE',1)", T, C, sibling_base,
    )
    await conn.execute(
        "INSERT INTO change_ledger.physical_base_slots(base_fingerprint) VALUES($1)", sibling_base,
    )
    assert sibling_base != flow["base"]
    sibling_id = await ledger.approved(
        request_id=f"s13-repair-sibling-{uuid.uuid4().hex}", kind="POST",
        base=sibling_base, target=sibling_target,
    )
    sibling_budget = await conn.fetchrow(
        "SELECT * FROM change_ledger.change_budget WHERE change_id=$1", sibling_id,
    )
    sibling_writer = SqlChangeLedger(
        conn, actors={"requester": "clt_alice"}, private_writer_schema_enabled=True,
    )
    sibling_token = await sibling_writer.claim(
        Scope(T, C), sibling_id, key_hash="b" * 64, grant_id=sibling_budget["grant_id"],
        amount=sibling_budget["amount"], counts_create_update=sibling_budget["counts_create_update"],
        counts_post=sibling_budget["counts_post"],
    )
    assert sibling_token is not None
    sibling_key_before = await conn.fetchrow(
        "SELECT pg_catalog.to_jsonb(k) FROM change_ledger.key_locks k WHERE owner_change_id=$1",
        sibling_id,
    )
    sibling_lease_before = await conn.fetchrow(
        "SELECT pg_catalog.to_jsonb(w) FROM change_ledger.writer_leases w WHERE owner_change_id=$1",
        sibling_id,
    )
    assert sibling_key_before is not None and sibling_lease_before is not None
    before = await _attempt_snapshot(flow)
    assert await _finalizer(
        flow, "private_writer_record_recovered_not_invoked_v1", refs["receipt"],
    ) == refs["receipt"]
    after = await _attempt_snapshot(flow)
    assert after != before
    parent_after = await conn.fetchrow(
        "SELECT pg_catalog.to_jsonb(r) FROM change_ledger.records r WHERE change_id=$1", parent_id,
    )
    hold_after = await conn.fetch(
        "SELECT pg_catalog.to_jsonb(h) FROM change_ledger.holds h WHERE change_id=$1 ORDER BY hold_id",
        parent_id,
    )
    parent_events_after = await conn.fetch(
        "SELECT pg_catalog.to_jsonb(e) FROM change_ledger.events e WHERE change_id=$1 ORDER BY seq",
        parent_id,
    )
    assert parent_after == parent_before, "repair finalizer modified the historical parent record"
    assert hold_after == hold_before, "repair finalizer modified the parent's FAILED_VERIFY_HALT"
    assert parent_events_after == parent_events_before, "repair finalizer emitted an event on the parent"
    sibling_key_after = await conn.fetchrow(
        "SELECT pg_catalog.to_jsonb(k) FROM change_ledger.key_locks k WHERE owner_change_id=$1",
        sibling_id,
    )
    sibling_lease_after = await conn.fetchrow(
        "SELECT pg_catalog.to_jsonb(w) FROM change_ledger.writer_leases w WHERE owner_change_id=$1",
        sibling_id,
    )
    assert sibling_key_after == sibling_key_before, "repair handoff changed another change's key lock"
    assert sibling_lease_after == sibling_lease_before, "repair handoff changed another change's writer lease"
    target_after = await conn.fetchrow(
        "SELECT owner_change_id FROM change_ledger.target_locks WHERE tenant_id=$1 AND company_id=$2 "
        "AND base_fingerprint=$3 AND target_ref=$4",
        identity["tenant_id"], identity["company_id"], flow["base"], identity["target_ref"],
    )
    assert target_after is not None and target_after["owner_change_id"] == parent_id
    for table in ("key_locks", "writer_leases"):
        assert await conn.fetchval(
            f'SELECT NOT EXISTS(SELECT 1 FROM change_ledger."{table}" WHERE owner_change_id=$1)',
            flow["change_id"],
        ) is True, f"repair PRE_WRITE handoff retained call-owned {table}"
    terminal_events = await conn.fetch(
        "SELECT event_type,payload->'private_writer' AS private_writer_payload "
        "FROM change_ledger.events WHERE change_id=$1 AND event_type='COMPLETE_PRE_WRITE_REFUSAL'",
        flow["change_id"],
    )
    assert len(terminal_events) == 1
    assert terminal_events[0]["event_type"] == "COMPLETE_PRE_WRITE_REFUSAL"
    event_payload = terminal_events[0]["private_writer_payload"]
    if isinstance(event_payload, str):
        event_payload = json.loads(event_payload)
    receipt = await conn.fetchrow(
        "SELECT record_digest,no_effect_evidence_digest FROM change_ledger.private_writer_evidence "
        "WHERE evidence_ref=$1", refs["receipt"],
    )
    assert receipt is not None
    assert event_payload == {
        "no_entry_receipt_ref": refs["receipt"],
        "no_entry_receipt_digest": receipt["record_digest"],
        "no_effect_proof": {
            "receipt_ref": refs["receipt"], "receipt_digest": receipt["record_digest"],
            "no_effect_evidence_digest": receipt["no_effect_evidence_digest"],
        },
    }
    assert await conn.fetchval(
        "SELECT count(*) FROM change_ledger.events WHERE change_id=$1 "
        "AND event_type='COMPLETE_PRE_WRITE_REFUSAL'", flow["change_id"],
    ) == 1
    replay_snapshot = await _attempt_snapshot(flow)
    sibling_replay_before = (
        await conn.fetchrow(
            "SELECT pg_catalog.to_jsonb(k) FROM change_ledger.key_locks k WHERE owner_change_id=$1",
            sibling_id,
        ),
        await conn.fetchrow(
            "SELECT pg_catalog.to_jsonb(w) FROM change_ledger.writer_leases w WHERE owner_change_id=$1",
            sibling_id,
        ),
    )
    assert await _finalizer(
        flow, "private_writer_record_recovered_not_invoked_v1", refs["receipt"],
    ) == refs["receipt"]
    assert await _attempt_snapshot(flow) == replay_snapshot, (
        "repair PRE_WRITE terminal replay changed the handed-back target lock, parent, resources, or events"
    )
    sibling_replay_after = (
        await conn.fetchrow(
            "SELECT pg_catalog.to_jsonb(k) FROM change_ledger.key_locks k WHERE owner_change_id=$1",
            sibling_id,
        ),
        await conn.fetchrow(
            "SELECT pg_catalog.to_jsonb(w) FROM change_ledger.writer_leases w WHERE owner_change_id=$1",
            sibling_id,
        ),
    )
    assert sibling_replay_after == sibling_replay_before, (
        "repair PRE_WRITE replay changed another change's key lock or writer lease"
    )


async def test_s13_completion_outcome_setup_fails_closed_without_ready_coordinator(
    ledger: L,
) -> None:
    """Prove the legal setup blocker before attempting synthetic finalizer evidence."""
    conn = ledger.conn
    before = await _ledger_snapshot(conn)

    try:
        async with conn.transaction():
            await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", T, C)
            await conn.fetchval(
                "SELECT change_ledger.lifecycle_begin_recovery($1,$2)", T, C,
            )
    except asyncpg.PostgresError as error:
        assert error.sqlstate == "P0001"
        assert str(error).splitlines()[0] == "LIFECYCLE_COORDINATOR_UNAVAILABLE"
    else:
        raise AssertionError("lifecycle recovery unexpectedly established a READY coordinator")

    assert await _ledger_snapshot(conn) == before, "failed lifecycle setup changed disposable ledger state"
    assert await conn.fetchval(
        "SELECT count(*)=1 AND bool_and(NOT pg_catalog.has_function_privilege("
        "'operator_role',p.oid,'EXECUTE')) "
        "FROM pg_catalog.pg_proc p JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='change_ledger' AND p.proname='operator_resolve_v1'"
    ), "T16 operator_resolve_v1 ACL unexpectedly differs from the documented unqualified boundary"
