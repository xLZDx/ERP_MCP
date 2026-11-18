"""Exercise the candidate T16 resolver and verifier against synthetic trust in disposable PostgreSQL.

This uses an invocation-owned disposable database. It does not qualify production trust roots or
ACLs, writer runtime composition, terminalization or slot replay, or startup recovery.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import UUID, uuid4

import asyncpg
import pytest

pytest_plugins = ("test_s13_current_turn_sql",)

from business_ai_gateway.phase2 import ed25519
from business_ai_gateway.phase2.change.evidence import (
    CompletionProof,
    DispatchAttempt,
    DispatchReceipt,
    OutcomeEvidenceV3,
    PostCompletionChallenge,
    PostCompletionReadAttestation,
    canonical_json_bytes,
    challenged_read_request_digest,
    outcome_observation_digest,
    seal_record_fixture,
)
from erp_mcp_private_writer.evidence_trust import (
    EvidenceScope,
)
from erp_mcp_private_writer.postgres_attempt_source import PostgresEvidenceAttemptSource
from erp_mcp_private_writer.postgres_evidence_resolver import PostgresWriterEvidenceResolver
from erp_mcp_private_writer.postgres_evidence_trust import PostgresEvidenceTrustSource
from erp_mcp_private_writer.production_evidence_verifier import ProductionEvidenceVerifier
from erp_mcp_private_writer.service import CallIdentity
from test_s13_current_turn_sql import L, _seed_evidence_lookup_attempt

pytestmark = pytest.mark.integration

_EVIDENCE_LOADER = (
    "change_ledger.private_writer_load_evidence_records_v1(uuid,uuid,text,text,text,text,uuid,bigint,text,text[])"
)
_TRUST_LOADER = (
    "change_ledger.private_writer_load_trust_snapshot_v1(text,text,text,text,text,text[],text[],uuid[],text,text,boolean)"
)
_ATTEMPT_LOADER = (
    "change_ledger.private_writer_evidence_attempt_v1(uuid,uuid,text,text,text,text)"
)
_ATTEMPT_TYPE = "change_ledger.private_writer_evidence_attempt_v1"
_PROCESS_PREFIX = b"ERP_MCP_R2:S13:PROCESS-INSTANCE:v1\n"
_KEY_VERSION = "synthetic-test-v1"


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _signer_seed(label: str) -> bytes:
    return hashlib.sha256(("S13-T16-SYNTHETIC-TEST:" + label).encode()).digest()


def _signed_record(kind: type, fields: dict[str, object], label: str):
    return seal_record_fixture(kind, fields, _signer_seed(label))


def _target_role_dsn(admin_dsn: str, database: str, password: str) -> str:
    parts = urlsplit(admin_dsn)
    return urlunsplit((
        parts.scheme,
        f"private_writer_evidence_ingest:{quote(password, safe='')}@{parts.hostname}:{parts.port}",
        "/" + database,
        parts.query,
        parts.fragment,
    ))


async def _insert_signer(conn: asyncpg.Connection, *, key_id: str, role: str,
                         service: str, host: str, scope: EvidenceScope) -> None:
    valid_from = datetime(2000, 1, 1, tzinfo=UTC)
    valid_until = datetime(2100, 1, 1, tzinfo=UTC)
    public = ed25519.public_key_from_seed(_signer_seed(key_id))
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_signer_key_versions"
        "(key_id,key_version,public_key,signer_role,service_id,host_id,valid_from,valid_until) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8)",
        key_id, _KEY_VERSION, public, role, service, host, valid_from, valid_until,
    )
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_signer_key_scopes"
        "(key_id,key_version,tenant_id,company_id,organization_ref,base_fingerprint) "
        "VALUES($1,$2,$3,$4,$5,$6)",
        key_id, _KEY_VERSION, scope.tenant_id, scope.company_id,
        scope.organization_ref, scope.base_fingerprint,
    )


async def _insert_process(conn: asyncpg.Connection, *, process_id: str, service: str,
                          host: str, supervisor_key: str, created: datetime) -> None:
    boot_id = str(uuid4())
    fields = {
        "attestation_version": "1", "process_instance_id": process_id,
        "host_boot_id": boot_id, "service_id": service, "host_id": host,
        "os_pid": 4321, "process_created_at": _stamp(created),
        "supervisor_key_id": supervisor_key, "supervisor_key_version": _KEY_VERSION,
    }
    signed = _PROCESS_PREFIX + canonical_json_bytes(fields)
    signature = ed25519.sign(_signer_seed(supervisor_key), signed)
    await conn.execute(
        "INSERT INTO change_ledger.private_writer_process_attestations"
        "(process_instance_id,host_boot_id,service_id,host_id,os_pid,process_created_at,"
        "supervisor_key_id,supervisor_key_version,signature) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
        UUID(process_id), UUID(boot_id), service, host, 4321, created,
        supervisor_key, _KEY_VERSION, signature,
    )


async def _insert_evidence(conn: asyncpg.Connection, *, ref: str, record,
                           attempt: asyncpg.Record, signer: tuple[str, str, str],
                           role_projection: dict[str, object]) -> None:
    key_id, service_id, host_id = signer
    signed = canonical_json_bytes(record.to_dict())
    values: dict[str, object] = {
        "evidence_ref": ref,
        "record_type": {
            DispatchReceipt: "DISPATCH_RECEIPT_V1",
            OutcomeEvidenceV3: "OUTCOME_EVIDENCE_V3",
            CompletionProof: "COMPLETION_PROOF_V1",
            PostCompletionChallenge: "POST_COMPLETION_CHALLENGE_V1",
            PostCompletionReadAttestation: "POST_COMPLETION_READ_ATTESTATION_V1",
        }[type(record)],
        "signed_bytes": signed,
        "signed_bytes_sha256": hashlib.sha256(signed).digest(),
        "record_digest": record.calculated_digest(),
        "tenant_id": attempt["tenant_id"], "company_id": attempt["company_id"],
        "organization_ref": attempt["organization_ref"],
        "base_fingerprint": attempt["base_fingerprint"],
        "change_id": attempt["change_id"],
        "claim_generation": attempt["claim_generation"],
        "dispatch_generation": attempt["dispatch_generation"],
        "call_id": attempt["call_id"], "dispatch_cas_id": attempt["dispatch_cas_id"],
        "dispatch_intent_id": attempt["dispatch_intent_id"],
        "operation_kind": attempt["operation_kind"],
        "approval_digest": attempt["approval_digest"],
        "payload_digest": attempt["payload_digest"], "permit_id": attempt["permit_id"],
        "permit_digest": attempt["permit_digest"],
        "target_ref": attempt["expected_target_ref"],
        "pre_version": attempt["expected_pre_version"], "auth_epoch": attempt["auth_epoch"],
        "repair_authorization_id": attempt["repair_authorization_id"],
        "signer_key_id": key_id, "signer_key_version": _KEY_VERSION,
        "signer_role": record.signer_role if type(record) is DispatchReceipt else (
            record.role if type(record) is OutcomeEvidenceV3 else
            record.signer_role if type(record) in (CompletionProof, PostCompletionChallenge)
            else record.signer_role
        ),
        "signer_service_id": service_id, "signer_host_id": host_id,
        "signed_at": datetime.strptime(
            record.started_at if type(record) is DispatchReceipt else
            record.observed_at if type(record) is CompletionProof else
            record.issued_at if type(record) is PostCompletionChallenge else
            record.completed_at if type(record) is PostCompletionReadAttestation else record.observed_at,
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ).replace(tzinfo=UTC),
        "trust_registry_revision": 1,
        "verified_at": await conn.fetchval("SELECT clock_timestamp()"),
        "validator_build_id": "synthetic-test-fixture-only",
        "process_instance_id": (
            record.writer_process_instance_id if type(record) in (DispatchReceipt, CompletionProof) else
            record.process_instance_id if type(record) is PostCompletionReadAttestation else None
        ),
        "session_instance_id": (
            str(record.onec_session_instance_id)
            if getattr(record, "onec_session_instance_id", None) is not None else None
        ),
        **role_projection,
    }
    columns = tuple(values)
    marks = ",".join(f"${index}" for index in range(1, len(columns) + 1))
    await conn.execute(
        f"INSERT INTO change_ledger.private_writer_evidence({','.join(columns)}) VALUES({marks})",
        *(values[column] for column in columns),
    )


def _record_set(attempt: asyncpg.Record, started: datetime):
    tenant, company, org, base = (attempt[name] for name in (
        "tenant_id", "company_id", "organization_ref", "base_fingerprint",
    ))
    scope = EvidenceScope(tenant, company, org, base)
    host = attempt["writer_host_id"]
    writer_service = attempt["writer_service_id"]
    verifier_service, supervisor_service, reader_service = (
        "s13-t16-verifier", "s13-t16-supervisor", "s13-t16-reader",
    )
    writer_key, verifier_key, supervisor_key, reader_key = (
        "s13-t16-writer-key", "s13-t16-verifier-key", "s13-t16-supervisor-key",
        "s13-t16-reader-key",
    )
    receipt_id, challenge_id = str(uuid4()), str(uuid4())
    common = {
        "tenant_id": tenant, "company_id": company, "organization_ref": org,
        "base_fingerprint": base, "change_id": str(attempt["change_id"]),
        "claim_generation": attempt["claim_generation"],
        "dispatch_generation": attempt["dispatch_generation"],
        "dispatch_cas_id": str(attempt["dispatch_cas_id"]),
        "call_id": str(attempt["call_id"]), "operation_kind": attempt["operation_kind"],
    }
    h = "a" * 64
    receipt = _signed_record(DispatchReceipt, {
        "receipt_version": "1", **common,
        "request_id": str(uuid4()), "approval_digest_version": "2",
        "target_class": "synthetic-test", "expected_target_ref": attempt["expected_target_ref"],
        "expected_pre_version": attempt["expected_pre_version"],
        "approval_digest": attempt["approval_digest"], "auth_epoch": attempt["auth_epoch"],
        "permit_id": str(attempt["permit_id"]), "permit_digest": attempt["permit_digest"],
        "receipt_id": receipt_id, "dispatch_generation": attempt["dispatch_generation"],
        "writer_service_id": writer_service, "writer_host_id": host,
        "writer_process_instance_id": str(attempt["writer_process_instance_id"]),
        "onec_session_id": None,
        "onec_session_instance_id": attempt["onec_session_instance_id"],
        "started_at": _stamp(started), "write_invocation_stage": "ENTERED",
        "call_returned": True, "returned_at": _stamp(started + timedelta(seconds=1)),
        "result_class": "CONDITIONAL_VERSION_CONFLICT", "returned_target_ref": None,
        "returned_version": None, "no_effect_evidence_digest": None, "error_family": None,
        "mapping_version": "test-v1", "configuration_fingerprint": h,
        "approved_payload_digest": attempt["payload_digest"],
        "mapped_property_manifest_sha256": h, "COM_operation_manifest_sha256": h,
        "signer_key_id": writer_key, "key_version": _KEY_VERSION,
        "signer_role": "writer_receipt", "algorithm": "Ed25519",
        "signed_payload_digest": h, "signature": "",
    }, writer_key)
    completion = _signed_record(CompletionProof, {
        "proof_version": "1", "completion_proof_id": str(uuid4()), **common,
        "writer_process_instance_id": str(attempt["writer_process_instance_id"]),
        "onec_session_instance_id": attempt["onec_session_instance_id"],
        "proof_class": "WRITER_CALL_RETURNED", "source_service_id": writer_service,
        "source_host_id": host,
        "source_process_instance_id": str(attempt["writer_process_instance_id"]),
        "source_session_instance_id": None,
        "observed_session_instance_id": attempt["onec_session_instance_id"],
        "evidence_ref": "synthetic-writer-return", "evidence_digest": h,
        "observed_at": _stamp(started + timedelta(seconds=2)),
        "signer_key_id": writer_key, "key_version": _KEY_VERSION,
        "signer_role": "writer_receipt", "algorithm": "Ed25519",
        "canonical_evidence_digest": h, "signature": "",
    }, writer_key)
    challenge = _signed_record(PostCompletionChallenge, {
        "challenge_version": "1", "challenge_id": challenge_id,
        **{key: value for key, value in common.items() if key != "operation_kind"},
        "completion_proof_digest": completion.calculated_digest(),
        "verifier_service_id": verifier_service, "verifier_host_id": host,
        "verification_sequence_floor": 4, "challenge_nonce": h,
        "query_spec_digest": _digest("t16-query-spec"),
        "read_attestor_service_id": reader_service, "read_attestor_host_id": host,
        "issued_at": _stamp(started + timedelta(seconds=3)),
        "issuer_service_id": supervisor_service, "issuer_host_id": host,
        "signer_key_id": supervisor_key, "key_version": _KEY_VERSION,
        "signer_role": "completion_supervisor", "algorithm": "Ed25519",
        "canonical_challenge_digest": h, "signature": "",
    }, supervisor_key)
    seq = 5
    read_base = {
        "attestation_version": "1", "attestation_id": str(uuid4()),
        **{key: value for key, value in common.items() if key != "operation_kind"},
        "challenge_id": challenge_id,
        "challenge_nonce_digest": hashlib.sha256(challenge.challenge_nonce.encode("ascii")).hexdigest(),
        "query_spec_digest": challenge.query_spec_digest,
        "source_response_digest": _digest("synthetic-read-response"),
        "verification_sequence": seq,
        "process_instance_id": str(uuid4()), "attestor_service_id": reader_service,
        "attestor_host_id": host, "completed_at": _stamp(started + timedelta(seconds=5)),
        "signer_key_id": reader_key, "key_version": _KEY_VERSION,
        "signer_role": "read_attestor", "algorithm": "Ed25519",
        "canonical_attestation_digest": h, "signature": "",
    }
    read_base["query_request_digest"] = challenged_read_request_digest(challenge, seq)
    outcome_fields: dict[str, object] = {
        "evidence_version": "3",
        **{key: value for key, value in common.items()
           if key not in {"dispatch_generation", "dispatch_cas_id"}},
        "dispatch_receipt_id": receipt_id,
        "approval_digest": attempt["approval_digest"],
        "verifier_service_id": verifier_service, "verifier_host_id": host,
        "signer_key_id": verifier_key, "key_version": _KEY_VERSION,
        "algorithm": "Ed25519", "role": "verification_worker",
        "observed_at": _stamp(started + timedelta(seconds=4)),
        "read_session_id": "synthetic-read-session", "target_ref": attempt["expected_target_ref"],
        "pre_version": attempt["expected_pre_version"],
        "observed_version": "synthetic-competing-version", "document_posting_state": "POSTED",
        "field_snapshot_digest": h, "lines_digest": h, "movement_multiset": (),
        "registrar": attempt["expected_target_ref"], "register_catalogue_version": "synthetic-v1",
        "movement_count_by_register": {}, "movement_digest_by_register": {},
        "movement_multiset_digest": hashlib.sha256(b"[]").hexdigest(),
        "expected_effect_digest": h, "observed_effect_digest": "b" * 64,
        "fields_match": False, "movements_match": False,
        "version_relation": "DIFFERENT_COMPETING_WRITER", "reader_health": "HEALTHY",
        "observation_complete": True, "effect_presence": "ABSENT",
        "effect_identity": "NO_GOVERNED_EFFECT", "completion_proof_class": "WRITER_CALL_RETURNED",
        "attribution_result": "COMPETING_WRITER",
        "attribution_evidence_ref": "synthetic-independent-competitor",
        "uncertainties": (), "canonical_evidence_digest": h, "signature": "",
        "document_shape_revision": "synthetic-shape-v1", "configuration_fingerprint": h,
        "oracle_id": "synthetic-post-oracle", "oracle_version": "v1",
        "oracle_digest": h, "expected_effect_schema_version": "synthetic-effects-v1",
        "completion_proof_digest": completion.calculated_digest(),
        "post_completion_challenge_id": challenge_id,
        "verification_sequence": seq, "read_attestation_digest": "0" * 64,
    }
    outcome_draft = OutcomeEvidenceV3(outcome_fields)
    read_base["outcome_observation_digest"] = outcome_observation_digest(outcome_draft)
    read = _signed_record(PostCompletionReadAttestation, read_base, reader_key)
    outcome_fields["read_attestation_digest"] = read.calculated_digest()
    outcome = _signed_record(OutcomeEvidenceV3, outcome_fields, verifier_key)
    records = (receipt, outcome, completion, challenge, read)
    signers = (
        (writer_key, writer_service, host), (verifier_key, verifier_service, host),
        (writer_key, writer_service, host), (supervisor_key, supervisor_service, host),
        (reader_key, reader_service, host),
    )
    projections = (
        {"writer_receipt_id": UUID(receipt_id), "writer_invocation_stage": "ENTERED",
         "writer_result_class": "CONDITIONAL_VERSION_CONFLICT", "writer_call_returned": True,
         "writer_returned_at": started + timedelta(seconds=1)},
        {"outcome_evidence_version": 3, "outcome_dispatch_receipt_id": UUID(receipt_id),
         "outcome_target_ref": outcome.target_ref, "outcome_pre_version": outcome.pre_version,
         "outcome_observed_version": outcome.observed_version,
         "outcome_expected_effect_digest": outcome.expected_effect_digest,
         "outcome_observed_effect_digest": outcome.observed_effect_digest,
         "outcome_fields_match": False, "outcome_movements_match": False,
         "outcome_observation_complete": True, "outcome_reader_health": "HEALTHY",
         "outcome_effect_presence": "ABSENT", "outcome_effect_identity": "NO_GOVERNED_EFFECT",
         "outcome_version_relation": "DIFFERENT_COMPETING_WRITER",
         "outcome_attribution_result": "COMPETING_WRITER",
         "outcome_attribution_evidence_ref": outcome.attribution_evidence_ref,
         "outcome_uncertainty_count": 0, "outcome_completion_proof_class": completion.proof_class,
         "outcome_completion_proof_digest": completion.calculated_digest(),
         "outcome_challenge_id": UUID(challenge_id), "outcome_verification_sequence": seq,
         "outcome_observation_digest": read.outcome_observation_digest,
         "outcome_read_attestation_digest": read.calculated_digest()},
        {"completion_proof_id": UUID(completion.completion_proof_id),
         "completion_proof_class": completion.proof_class},
        {"challenge_id": UUID(challenge_id), "challenge_sequence_floor": 4},
        {"read_attestation_sequence": seq,
         "read_attestation_outcome_digest": read.outcome_observation_digest},
    )
    return records, scope, signers, projections


@pytest.mark.asyncio
async def _run_s13_t16_evidence_acceptance(ledger: L, *, exercise_resolver: bool) -> None:
    conn = ledger.conn
    password = secrets.token_urlsafe(32)
    pool: asyncpg.Pool | None = None
    grants_installed = False
    try:
        # Credential material is sent to PostgreSQL over this invocation-owned cluster only.
        alter = await conn.fetchval(
            "SELECT pg_catalog.format('ALTER ROLE %I PASSWORD %L', "
            "'private_writer_evidence_ingest', $1::text)", password,
        )
        await conn.execute(alter)
        await conn.execute(f"GRANT EXECUTE ON FUNCTION {_EVIDENCE_LOADER} TO private_writer_evidence_ingest")
        grants_installed = True
        await conn.execute(f"GRANT EXECUTE ON FUNCTION {_TRUST_LOADER} TO private_writer_evidence_ingest")
        if exercise_resolver:
            await conn.execute(f"GRANT USAGE ON TYPE {_ATTEMPT_TYPE} TO private_writer_evidence_ingest")
            await conn.execute(f"GRANT EXECUTE ON FUNCTION {_ATTEMPT_LOADER} TO private_writer_evidence_ingest")

        flow = await _seed_evidence_lookup_attempt(conn, evidence_count=0)
        attempt = await conn.fetchrow(
            "SELECT * FROM change_ledger.dispatch_attempts WHERE dispatch_cas_id=$1",
            flow["dispatch_cas_id"],
        )
        assert attempt is not None
        started = await conn.fetchval("SELECT clock_timestamp() - interval '30 seconds'")
        records, scope, signers, projections = _record_set(attempt, started)
        # Independent synthetic signers have disjoint service identities as required by trust policy.
        for key_id, role, service, host in (
            ("s13-t16-writer-key", "writer_receipt", attempt["writer_service_id"], attempt["writer_host_id"]),
            ("s13-t16-verifier-key", "verification_worker", "s13-t16-verifier", attempt["writer_host_id"]),
            ("s13-t16-supervisor-key", "completion_supervisor", "s13-t16-supervisor", attempt["writer_host_id"]),
            ("s13-t16-reader-key", "read_attestor", "s13-t16-reader", attempt["writer_host_id"]),
        ):
            await _insert_signer(conn, key_id=key_id, role=role, service=service, host=host, scope=scope)
        await _insert_process(
            conn, process_id=attempt["writer_process_instance_id"], service=attempt["writer_service_id"],
            host=attempt["writer_host_id"], supervisor_key="s13-t16-supervisor-key",
            created=started - timedelta(minutes=2),
        )
        reader_process = records[4].process_instance_id
        await _insert_process(
            conn, process_id=reader_process, service="s13-t16-reader", host=attempt["writer_host_id"],
            supervisor_key="s13-t16-supervisor-key", created=started - timedelta(minutes=2),
        )
        await conn.execute(
            "INSERT INTO change_ledger.private_writer_oracle_artifacts"
            "(tenant_id,company_id,organization_ref,base_fingerprint,operation_kind,oracle_id,oracle_version,"
            "document_shape_revision,configuration_fingerprint,oracle_digest,query_plan_digest,"
            "expected_effect_schema_version) VALUES($1,$2,$3,$4,'POST',$5,'v1',$6,$7,$8,$9,$10)",
            scope.tenant_id, scope.company_id, scope.organization_ref, scope.base_fingerprint,
            "synthetic-post-oracle", "synthetic-shape-v1", "a" * 64, "a" * 64,
            "a" * 64, "synthetic-effects-v1",
        )
        await conn.execute(
            "INSERT INTO change_ledger.private_writer_outcome_version_floors"
            "(tenant_id,company_id,organization_ref,base_fingerprint,operation_kind,minimum_version,policy_revision) "
            "VALUES($1,$2,$3,$4,'POST',3,1)",
            scope.tenant_id, scope.company_id, scope.organization_ref, scope.base_fingerprint,
        )
        # Use exact resolver-derived references and insert the typed projections alongside bytes.
        evidence_refs = tuple(PostgresWriterEvidenceResolver.evidence_ref(record) for record in records)
        assert len(set(evidence_refs)) == 5
        for index, (record, signer, projection, ref) in enumerate(
                zip(records, signers, projections, evidence_refs, strict=True)):
            await _insert_evidence(
                conn, ref=ref, record=record, attempt=attempt, signer=signer,
                role_projection=projection,
            )
            await conn.execute(
                "INSERT INTO change_ledger.private_writer_attempt_evidence"
                "(dispatch_cas_id,dispatch_intent_id,evidence_ref,evidence_purpose) "
                "VALUES($1,$2,$3,$4)", attempt["dispatch_cas_id"], attempt["dispatch_intent_id"],
                ref, ("WRITER_RECEIPT", "OUTCOME", "COMPLETION", "POST_COMPLETION_CHALLENGE", "READ_ATTESTATION")[index],
            )

        # The fixture's Db object owns the DSN and generated throwaway database identity.
        fixture_dsn = ledger.db.dsn
        database_name = ledger.db.name
        pool = await asyncpg.create_pool(
            _target_role_dsn(fixture_dsn, database_name, password),
            min_size=1, max_size=2,
        )
        async with pool.acquire() as role_conn:
            role_row = await role_conn.fetchrow("SELECT session_user::text, current_user::text, current_database()")
            assert tuple(role_row) == (
                "private_writer_evidence_ingest", "private_writer_evidence_ingest", database_name,
            )
            admin_identity = await conn.fetchrow(
                "SELECT current_database(), inet_server_addr()::text, inet_server_port()",
            )
            ingest_identity = await role_conn.fetchrow(
                "SELECT current_database(), inet_server_addr()::text, inet_server_port()",
            )
            assert tuple(ingest_identity) == tuple(admin_identity)

        exact_refs = tuple(PostgresWriterEvidenceResolver.evidence_ref(record) for record in records)
        async with pool.acquire() as role_conn:
            rows = await role_conn.fetch(
                "SELECT evidence_ref,record_type,signed_bytes FROM "
                "change_ledger.private_writer_load_evidence_records_v1($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                attempt["dispatch_cas_id"], attempt["call_id"], attempt["tenant_id"],
                attempt["company_id"], attempt["organization_ref"], attempt["base_fingerprint"],
                attempt["change_id"], attempt["claim_generation"], attempt["operation_kind"],
                list(exact_refs),
            )
        assert tuple(row["evidence_ref"] for row in rows) == exact_refs
        assert tuple(row["signed_bytes"] for row in rows) == tuple(
            canonical_json_bytes(record.to_dict()) for record in records
        )
        parsed_attempt = DispatchAttempt(
            tenant_id=attempt["tenant_id"], company_id=attempt["company_id"],
            organization_ref=attempt["organization_ref"], base_fingerprint=attempt["base_fingerprint"],
            change_id=str(attempt["change_id"]), claim_generation=attempt["claim_generation"],
            dispatch_generation=attempt["dispatch_generation"], dispatch_cas_id=str(attempt["dispatch_cas_id"]),
            call_id=str(attempt["call_id"]), operation_kind=attempt["operation_kind"],
            approval_digest=attempt["approval_digest"], auth_epoch=attempt["auth_epoch"],
            permit_id=str(attempt["permit_id"]), permit_digest=attempt["permit_digest"],
            expected_target_ref=attempt["expected_target_ref"],
            expected_pre_version=attempt["expected_pre_version"],
            writer_service_id=attempt["writer_service_id"], writer_host_id=attempt["writer_host_id"],
            writer_process_instance_id=attempt["writer_process_instance_id"],
            onec_session_instance_id=attempt["onec_session_instance_id"],
        )
        verified = await ProductionEvidenceVerifier(PostgresEvidenceTrustSource(pool)).verify_set(
            tuple(row["signed_bytes"] for row in rows), attempt=parsed_attempt,
        )
        assert tuple(type(value.record) for value in verified) == (
            DispatchReceipt, OutcomeEvidenceV3, CompletionProof,
            PostCompletionChallenge, PostCompletionReadAttestation,
        )
        assert len({value.trust_revision for value in verified}) == 1
        if exercise_resolver:
            resolver = PostgresWriterEvidenceResolver(
                pool,
                PostgresEvidenceAttemptSource(pool),
                ProductionEvidenceVerifier(PostgresEvidenceTrustSource(pool)),
            )
            identity = CallIdentity(
                tenant_id=attempt["tenant_id"], company_id=attempt["company_id"],
                organization_ref=attempt["organization_ref"], change_id=str(attempt["change_id"]),
                generation=attempt["claim_generation"], call_id=str(attempt["call_id"]),
                operation=attempt["operation_kind"], target_ref=attempt["expected_target_ref"],
                target_version=attempt["expected_pre_version"], epoch=attempt["auth_epoch"],
                payload_digest=attempt["payload_digest"], permit_id=str(attempt["permit_id"]),
                permit_digest=attempt["permit_digest"], base_fingerprint=attempt["base_fingerprint"],
                host_id=attempt["writer_host_id"],
                repair_authorization_id=attempt["repair_authorization_id"],
            )
            resolved = await resolver.load_conditional_conflict_terminal_records(
                identity, UUID(str(attempt["dispatch_cas_id"])), *exact_refs,
            )
            assert tuple(type(value) for value in (
                resolved.receipt, resolved.outcome, resolved.completion,
                resolved.post_completion_challenge, resolved.read_attestation,
            )) == (
                DispatchReceipt, OutcomeEvidenceV3, CompletionProof,
                PostCompletionChallenge, PostCompletionReadAttestation,
            )
            assert tuple(value.record for value in resolved.verified_records) == (
                resolved.receipt, resolved.outcome, resolved.completion,
                resolved.post_completion_challenge, resolved.read_attestation,
            )
            assert resolved.expected_scope == scope
    finally:
        try:
            if pool is not None:
                await pool.close()
        finally:
            try:
                if grants_installed:
                    if exercise_resolver:
                        await conn.execute(
                            f"REVOKE EXECUTE ON FUNCTION {_ATTEMPT_LOADER} "
                            "FROM private_writer_evidence_ingest",
                        )
                        await conn.execute(
                            f"REVOKE USAGE ON TYPE {_ATTEMPT_TYPE} "
                            "FROM private_writer_evidence_ingest",
                        )
                    await conn.execute(
                        f"REVOKE EXECUTE ON FUNCTION {_EVIDENCE_LOADER} "
                        "FROM private_writer_evidence_ingest",
                    )
                    await conn.execute(
                        f"REVOKE EXECUTE ON FUNCTION {_TRUST_LOADER} "
                        "FROM private_writer_evidence_ingest",
                    )
                    assert await conn.fetchval(
                        "SELECT NOT pg_catalog.has_function_privilege('private_writer_evidence_ingest',$1,'EXECUTE') "
                        "AND NOT pg_catalog.has_function_privilege('private_writer_evidence_ingest',$2,'EXECUTE')",
                        _EVIDENCE_LOADER, _TRUST_LOADER,
                    ) is True
                    if exercise_resolver:
                        assert await conn.fetchval(
                            "SELECT NOT pg_catalog.has_function_privilege("
                            "'private_writer_evidence_ingest',$1,'EXECUTE') "
                            "AND NOT pg_catalog.has_type_privilege("
                            "'private_writer_evidence_ingest',$2,'USAGE')",
                            _ATTEMPT_LOADER, _ATTEMPT_TYPE,
                        ) is True
            finally:
                await conn.execute("ALTER ROLE private_writer_evidence_ingest PASSWORD NULL")


@pytest.mark.asyncio
async def test_s13_t16_evidence_verifier_checks_five_signed_envelopes(ledger: L) -> None:
    await _run_s13_t16_evidence_acceptance(ledger, exercise_resolver=False)


@pytest.mark.asyncio
async def test_s13_t16_resolver_loads_and_verifies_five_signed_envelopes(ledger: L) -> None:
    await _run_s13_t16_evidence_acceptance(ledger, exercise_resolver=True)
