"""PostgreSQL-backed Admin API acceptance coverage for S4 R2-US-016 (TC046-048).

This module owns a uniquely named, loopback-only disposable PostgreSQL container. It exercises
the registered Starlette routes, signed Admin OAuth tokens, pinned private evidence, and the
actual promotion SQL port. It never targets a configured/shared database.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import asyncpg
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.routing import Route

from business_ai_gateway.admin_api import register_admin_routes
from business_ai_gateway.db import Database
from business_ai_gateway.evidence_index import ApprovedEvidenceProvider, EvidenceApproval
from business_ai_gateway.evidence_store import PrivateEvidenceStore, _write_new
from business_ai_gateway.external_evidence import EvidenceClass, EvidenceParserProfile, EvidenceScope
from business_ai_gateway.phase2.promotion_sql import actor_role_for_subject
from business_ai_gateway.settings import Settings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TENANT = "promotion-test-tenant"
SOURCE = "promotion-test-source"
MODEL = "model-test"
ADMIN_AUDIENCE = "https://identity.example.test/admin"
ADMIN_SCOPE = "erp_mcp:admin"
PAYLOAD = b"key,date,currency,amount\ntest-row,2026-11-05,MDL,12.34\n"
PROMOTION_SQL = Path(__file__).resolve().parents[2] / "db" / "phase2"
PROMOTION_MIGRATIONS = (
    "001_living_registry.sql",
    "002_job_cursor_functions.sql",
    "003_security_hardening.sql",
)


def _docker(*args: str, timeout: int = 30) -> str:
    completed = subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True, timeout=timeout
    )
    return completed.stdout.strip()


@pytest.fixture(scope="module")
def disposable_postgres_dsn():
    """Start and always remove this test module's own PostgreSQL container."""
    container = "erp-s4-promotion-tests-" + uuid.uuid4().hex[:12]
    _docker(
        "run", "--detach", "--rm", "--name", container,
        "--env", "POSTGRES_USER=postgres", "--env", "POSTGRES_PASSWORD=local-only-test",
        "--publish", "127.0.0.1::5432", "postgres:16.14",
    )
    try:
        published = _docker("port", container, "5432/tcp")
        match = re.fullmatch(r"127\.0\.0\.1:(\d+)", published)
        if match is None:
            raise RuntimeError("disposable PostgreSQL did not bind to loopback")
        port = int(match.group(1))
        deadline = time.monotonic() + 60
        last_error = None
        while time.monotonic() < deadline:
            try:
                _docker("exec", container, "pg_isready", "-U", "postgres", timeout=5)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                last_error = exc
                time.sleep(0.2)
        else:
            raise RuntimeError("disposable PostgreSQL did not become ready") from last_error
        yield f"postgresql://postgres:local-only-test@127.0.0.1:{port}/postgres"
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container],
            check=False, capture_output=True, text=True, timeout=30,
        )


class _RouteRegistrar:
    def __init__(self):
        self.routes = []

    def custom_route(self, path, *, methods):
        def register(handler):
            self.routes.append(Route(path, handler, methods=methods))
            return handler
        return register


class _FixedJWKS:
    def __init__(self, key):
        self.key = key

    def get_signing_key_from_jwt(self, _token):
        return SimpleNamespace(key=self.key)


def _keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _token(private_key: bytes, subject: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "https://identity.example.test/",
            "aud": ADMIN_AUDIENCE,
            "sub": subject,
            "iat": now,
            "exp": now + 300,
            "scope": ADMIN_SCOPE,
            "azp": "promotion-test-client",
            "groups": [],
        },
        private_key,
        algorithm="RS256",
    )


def _profile(company_id: str) -> EvidenceParserProfile:
    scope = EvidenceScope(
        source_id=SOURCE,
        company_id=company_id,
        configuration_fingerprint="a" * 64,
        semantic_profile_fingerprint="b" * 64,
        period_start=date(2026, 11, 1),
        period_end=date(2026, 12, 1),
        currency="MDL",
        timezone="Europe/Chisinau",
    )
    return EvidenceParserProfile("promotion-fixture", "v1", EvidenceClass.BANK_STATEMENT, scope)


def _request_body(*, company_id, revision_id, evidence_ref, acceptance_id=None, expected_version=0):
    return {
        "tenant_id": TENANT,
        "source_id": SOURCE,
        "company_id": str(company_id),
        "expected_version": expected_version,
        "acceptance_id": str(acceptance_id or uuid.uuid4()),
        "evidence_ref": evidence_ref,
        "revision_id": str(revision_id),
    }


async def _apply_phase2(conn):
    for name in PROMOTION_MIGRATIONS:
        raw = (PROMOTION_SQL / name).read_bytes()
        await conn.execute(
            "SELECT set_config('living.migration_checksum',$1,false)", hashlib.sha256(raw).hexdigest()
        )
        await conn.execute(raw.decode("utf-8"))


@pytest.fixture
async def product_env(disposable_postgres_dsn, tmp_path):
    """A fresh database, actual Admin API route, pinned evidence, and least-privilege logins."""
    admin = await asyncpg.connect(disposable_postgres_dsn)
    db_name = "promotion_it_" + uuid.uuid4().hex[:12]
    created = False
    pools = []
    try:
        await admin.execute(f'CREATE DATABASE "{db_name}"')
        created = True
        db_dsn = disposable_postgres_dsn.rsplit("/", 1)[0] + "/" + db_name
        role_suffix = uuid.uuid4().hex[:10]
        runtime_login, control_login, promotion_login = (
            f"bag_rt_{role_suffix}", f"bag_ctl_{role_suffix}", f"bag_pr_{role_suffix}"
        )
        await admin.execute(f"CREATE ROLE {runtime_login} LOGIN PASSWORD 'runtime-only-test' NOSUPERUSER")
        await admin.execute(f"CREATE ROLE {control_login} LOGIN PASSWORD 'control-only-test' NOSUPERUSER")
        await admin.execute(f"CREATE ROLE {promotion_login} LOGIN PASSWORD 'promotion-only-test' NOSUPERUSER")
        owner = await asyncpg.connect(db_dsn)
        await _apply_phase2(owner)
        await owner.execute("CREATE SCHEMA bag")
        await owner.execute(
            """
            CREATE TABLE bag.platform_role_bindings(
                binding_id uuid PRIMARY KEY, principal_kind text NOT NULL,
                principal_id text NOT NULL, role_name text NOT NULL, source_id text,
                expires_at timestamptz, revoked_at timestamptz
            );
            CREATE TABLE bag.admin_audit_events(
                event_id uuid PRIMARY KEY, occurred_at timestamptz NOT NULL DEFAULT now(),
                request_id uuid NOT NULL, actor_subject text NOT NULL, actor_client_id text NOT NULL,
                action text NOT NULL, target_type text NOT NULL, target_id text, source_id text,
                company_id uuid, reason text, safe_change_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                outcome text NOT NULL, detail_code text, policy_version text NOT NULL
            );
            """
        )
        await owner.execute(
            f"GRANT USAGE ON SCHEMA bag TO {control_login}; "
            f"GRANT SELECT ON bag.platform_role_bindings TO {control_login}; "
            f"GRANT INSERT, SELECT ON bag.admin_audit_events TO {control_login}"
        )

        company_id = uuid.uuid4()
        subject = "promotion-admin-" + uuid.uuid4().hex
        actor_role = actor_role_for_subject(subject)
        await owner.execute("CREATE ROLE " + actor_role + " NOLOGIN")
        await owner.execute(
            f"GRANT living_promoter TO {actor_role} WITH INHERIT TRUE, SET FALSE"
        )
        await owner.execute(
            f"GRANT {actor_role} TO {promotion_login} WITH INHERIT FALSE, SET TRUE"
        )
        await owner.execute(
            "INSERT INTO bag.platform_role_bindings(binding_id,principal_kind,principal_id,"
            "role_name,source_id) VALUES($1,'subject',$2,'PROFILE_ADMIN',$3)",
            uuid.uuid4(), subject, SOURCE,
        )
        await owner.execute("INSERT INTO living.tenants(tenant_id) VALUES($1)", TENANT)
        await owner.execute(
            "INSERT INTO living.sources(tenant_id,source_id,company_id) VALUES($1,$2,$3)",
            TENANT, SOURCE, str(company_id),
        )
        await owner.execute(
            "INSERT INTO living.role_scope(role_name,tenant_id,source_id,company_id) "
            "VALUES('living_worker',$1,$2,$3),($4,$1,$2,$3)",
            TENANT, SOURCE, str(company_id), actor_role,
        )
        await owner.execute(
            "INSERT INTO living.trusted_reviewers(role_name,tenant_id,source_id,active,expires_at) "
            "VALUES('living_worker',$1,$2,true,now()+interval '1 day')", TENANT, SOURCE,
        )

        store = PrivateEvidenceStore.create(tmp_path)
        profile = _profile(str(company_id))
        receipt = store.ingest_normalized(
            PAYLOAD, profile=profile, expected_scope=profile.scope,
            validated_profiles=frozenset({profile.fingerprint()}),
            retention_policy_id="promotion-test-retention",
            approved_retention_policies=frozenset({"promotion-test-retention"}),
            expected_document_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        )
        evidence_id = receipt.private_blob_ref.removeprefix("private:")
        evidence_ref = receipt.private_blob_ref
        approval = EvidenceApproval(
            evidence_id, receipt, profile, "promotion-test-retention",
            datetime.now(UTC) - timedelta(minutes=1), datetime.now(UTC) + timedelta(hours=1),
        )
        index_path = store._root / "approved-evidence.json"
        index_bytes = json.dumps(
            {"schema_version": 1, "entries": [approval.as_record()]},
            sort_keys=True, separators=(",", ":"),
        ).encode()
        _write_new(index_path, index_bytes)
        provider = ApprovedEvidenceProvider(
            store, index_path, hashlib.sha256(index_bytes).hexdigest()
        )

        revisions = [uuid.uuid4(), uuid.uuid4()]
        attestation_ids = []
        revision_digests = [hashlib.sha256(f"candidate-{i}".encode()).hexdigest() for i in range(2)]
        for revision_id, revision_digest in zip(revisions, revision_digests, strict=True):
            attestation_id = uuid.uuid4()
            await owner.execute(
                "INSERT INTO living.observations(tenant_id,source_id,observation_id,object_id,"
                "revision_id,kind,digest,observed_at) VALUES($1,$2,$3,$4,$5,'OBSERVED',$6,now())",
                TENANT, SOURCE, uuid.uuid4(), "candidate-model", revision_id, revision_digest,
            )
            await owner.execute(
                "INSERT INTO living.attestations(tenant_id,source_id,attestation_id,revision_id,"
                "proposer_subject,observer_subject,evidence_ref,evidence_digest,decision,expires_at) "
                "VALUES($1,$2,$3,$4,$5,'living_worker',$6,$7,'APPROVE',now()+interval '1 hour')",
                TENANT, SOURCE, attestation_id, revision_id, "candidate-author-" + uuid.uuid4().hex,
                evidence_ref, hashlib.sha256(f"{revision_digest}:{evidence_ref}".encode()).hexdigest(),
            )
            attestation_ids.append(attestation_id)
        await owner.execute(
            "INSERT INTO living.accepted_heads(tenant_id,source_id,model_key,version) "
            "VALUES($1,$2,$3,0)", TENANT, SOURCE, MODEL,
        )

        for role, password in ((control_login, "control-only-test"),
                               (promotion_login, "promotion-only-test")):
            pool = await asyncpg.create_pool(
                db_dsn.replace("postgres:local-only-test@", f"{role}:{password}@"),
                min_size=1, max_size=3,
            )
            pools.append(pool)
        control_db = Database(db_dsn.replace(
            "postgres:local-only-test@", f"{control_login}:control-only-test@"
        ))
        control_db.pool = pools[0]
        promotion_db = Database(
            db_dsn.replace("postgres:local-only-test@", f"{promotion_login}:promotion-only-test@")
        )
        promotion_db.pool = pools[1]
        runtime = SimpleNamespace(
            admin_db=control_db,
            db=control_db,
            model_promotion_db=promotion_db,
            evidence_provider=provider,
            rate_limit=SimpleNamespace(check=_async_noop),
            start=_async_noop,
        )
        settings = Settings(
            environment="test",
            oauth_enabled=True,
            oauth_issuer="https://identity.example.test/",
            oauth_audience="https://identity.example.test/mcp",
            oauth_jwks_url="https://identity.example.test/jwks",
            oauth_required_scope="onec:read",
            admin_api_enabled=True,
            admin_mutations_enabled=True,
            admin_ui_enabled=False,
            admin_oauth_audience=ADMIN_AUDIENCE,
            admin_oauth_required_scope=ADMIN_SCOPE,
            database_url=db_dsn.replace("postgres:local-only-test@", f"{runtime_login}:runtime-only-test@"),
            admin_control_database_url=db_dsn.replace(
                "postgres:local-only-test@", f"{control_login}:control-only-test@"
            ),
            model_promotion_database_url=db_dsn.replace(
                "postgres:local-only-test@", f"{promotion_login}:promotion-only-test@"
            ),
            evidence_store_root=str(store._root),
            evidence_approval_index=str(index_path),
            evidence_approval_sha256=hashlib.sha256(index_bytes).hexdigest(),
        )
        registrar = _RouteRegistrar()
        api = register_admin_routes(registrar, settings, runtime)
        private_key, public_key = _keypair()
        api.verifier._jwks = _FixedJWKS(public_key)
        app = Starlette(routes=registrar.routes)
        token = _token(private_key, subject)
        yield SimpleNamespace(
            owner=owner, admin=admin, db_dsn=db_dsn, db_name=db_name,
            pools=pools, app=app, token=token, subject=subject, actor_role=actor_role,
            promotion_db=promotion_db, promotion_login=promotion_login,
            company_id=company_id, revisions=revisions, revision_digests=revision_digests,
            evidence_ref=evidence_ref, evidence_id=evidence_id, provider=provider,
            attestation_ids=attestation_ids,
        )
    finally:
        for pool in reversed(pools):
            await pool.close()
        if "owner" in locals():
            await owner.close()
        if created:
            await admin.execute(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)')
        await admin.close()


async def _async_noop(**_kwargs):
    return None


async def _client(env):
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://testserver"
    )
    return client, {"Authorization": f"Bearer {env.token}"}


async def test_tc046_promote_binds_authenticated_subject_scope_and_pinned_evidence_bytes(product_env):
    env = product_env
    revision_id = env.revisions[0]
    acceptance_id = uuid.uuid4()
    body = _request_body(
        company_id=env.company_id, revision_id=revision_id,
        evidence_ref=env.evidence_ref, acceptance_id=acceptance_id,
    )
    client, headers = await _client(env)
    try:
        try:
            await env.provider.read_manifest_after_access_gate(
                SOURCE, env.company_id, env.evidence_id
            )
        except Exception as exc:
            pytest.fail(f"test evidence fixture cannot be read: {type(exc).__name__}: {exc}")
        response = await client.post(
            f"/admin/v1/sources/{SOURCE}/models/{MODEL}/promote", json=body, headers=headers
        )
        assert response.status_code == 200, (response.text, await env.owner.fetch(
            "SELECT action,outcome,detail_code FROM bag.admin_audit_events ORDER BY occurred_at"
        ))
        assert response.json() == {"outcome": "PROMOTED", "code": None, "new_version": 1}
        head = await env.owner.fetchrow(
            "SELECT revision_id,version FROM living.accepted_heads "
            "WHERE tenant_id=$1 AND source_id=$2 AND model_key=$3", TENANT, SOURCE, MODEL,
        )
        event = await env.owner.fetchrow(
            "SELECT acceptance_id,model_key,from_version,to_version,accepted_revision,"
            "approver_subject,independent_evidence_ref FROM living.acceptance_events "
            "WHERE tenant_id=$1 AND source_id=$2", TENANT, SOURCE,
        )
        assert head["revision_id"] == revision_id and head["version"] == 1
        assert event["acceptance_id"] == acceptance_id
        assert event["model_key"] == MODEL and event["from_version"] == 0 and event["to_version"] == 1
        assert event["accepted_revision"] == revision_id
        assert event["approver_subject"] == env.actor_role
        assert env.subject not in event["approver_subject"]
        assert event["independent_evidence_ref"] == env.evidence_ref
        manifest = await env.provider.read_manifest_after_access_gate(
            SOURCE, env.company_id, env.evidence_id
        )
        assert manifest["document_sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
        assert manifest["scope_sha256"] == _profile(str(env.company_id)).scope.fingerprint()
        assert await env.owner.fetchval(
            "SELECT count(*) FROM living.acceptance_events WHERE approver_subject=$1 "
            "AND independent_evidence_ref=$2", env.actor_role, env.evidence_ref,
        ) == 1

        # An identical replay is valid only while current database role/scope authorization remains.
        replay = await client.post(
            f"/admin/v1/sources/{SOURCE}/models/{MODEL}/promote", json=body, headers=headers
        )
        assert replay.status_code == 200 and replay.json()["new_version"] == 1
        await env.owner.execute(
            "DELETE FROM living.role_scope WHERE role_name=$1 AND tenant_id=$2 AND source_id=$3 "
            "AND company_id=$4", env.actor_role, TENANT, SOURCE, str(env.company_id),
        )
        denied_replay = await client.post(
            f"/admin/v1/sources/{SOURCE}/models/{MODEL}/promote", json=body, headers=headers
        )
        assert denied_replay.status_code == 403, denied_replay.text
        assert await env.owner.fetchval(
            "SELECT count(*) FROM living.acceptance_events WHERE tenant_id=$1 AND source_id=$2",
            TENANT, SOURCE,
        ) == 1
    finally:
        await client.aclose()


async def test_tc047_stale_expected_head_returns_409_without_acceptance_write(product_env):
    env = product_env
    body = _request_body(
        company_id=env.company_id, revision_id=env.revisions[0],
        evidence_ref=env.evidence_ref, expected_version=1,
    )
    client, headers = await _client(env)
    try:
        response = await client.post(
            f"/admin/v1/sources/{SOURCE}/models/{MODEL}/promote", json=body, headers=headers
        )
        assert response.status_code == 409, (response.text, await env.owner.fetch(
            "SELECT action,outcome,detail_code FROM bag.admin_audit_events ORDER BY occurred_at"
        ))
        assert response.json()["outcome"] == "REJECTED_CAS"
        assert response.json()["code"] == "STALE_ACCEPTED_HEAD"
        assert await env.owner.fetchval(
            "SELECT version FROM living.accepted_heads WHERE tenant_id=$1 AND source_id=$2 "
            "AND model_key=$3", TENANT, SOURCE, MODEL,
        ) == 0
        assert await env.owner.fetchval(
            "SELECT count(*) FROM living.acceptance_events WHERE tenant_id=$1 AND source_id=$2",
            TENANT, SOURCE,
        ) == 0
    finally:
        await client.aclose()


async def test_tc048_incompatible_and_revoked_rollback_are_denied_without_head_change(product_env):
    env = product_env
    client, headers = await _client(env)
    route = f"/admin/v1/sources/{SOURCE}/models/{MODEL}"
    try:
        incompatible = {
            "tenant_id": TENANT, "source_id": SOURCE, "company_id": str(env.company_id),
            "expected_version": 0, "acceptance_id": str(uuid.uuid4()),
            "evidence_ref": env.evidence_ref, "to_version": 99,
        }
        unknown_target = await client.post(route + "/rollback", json=incompatible, headers=headers)
        assert unknown_target.status_code == 409
        assert unknown_target.json() == {"error": "ROLLBACK_TARGET_UNKNOWN"}
        assert await env.owner.fetchval(
            "SELECT count(*) FROM living.acceptance_events WHERE tenant_id=$1 AND source_id=$2",
            TENANT, SOURCE,
        ) == 0

        # Establish two durable heads through the same authenticated product route.
        for version, revision_id in enumerate(env.revisions):
            promote = _request_body(
                company_id=env.company_id, revision_id=revision_id,
                evidence_ref=env.evidence_ref, expected_version=version,
            )
            response = await client.post(route + "/promote", json=promote, headers=headers)
            assert response.status_code == 200, (response.text, await env.owner.fetch(
                "SELECT action,outcome,detail_code FROM bag.admin_audit_events ORDER BY occurred_at"
            ))
        async with env.owner.transaction():
            await env.owner.execute("SET LOCAL ROLE living_worker")
            await env.owner.fetchval("SELECT living.set_scope($1,$2,$3)", TENANT, SOURCE,
                                     str(env.company_id))
            await env.owner.fetchval("SELECT living.revoke_attestation($1,$2,$3)",
                                     TENANT, SOURCE, env.attestation_ids[0])
        rollback = {
            "tenant_id": TENANT, "source_id": SOURCE, "company_id": str(env.company_id),
            "expected_version": 2, "acceptance_id": str(uuid.uuid4()),
            "evidence_ref": env.evidence_ref, "to_version": 1,
        }
        denied = await client.post(route + "/rollback", json=rollback, headers=headers)
        assert denied.status_code == 409, denied.text
        assert denied.json() == {"outcome": "REJECTED_REVOKED", "code": "EVIDENCE_REVOKED",
                                 "new_version": None}
        head = await env.owner.fetchrow(
            "SELECT revision_id,version FROM living.accepted_heads "
            "WHERE tenant_id=$1 AND source_id=$2 AND model_key=$3", TENANT, SOURCE, MODEL,
        )
        assert head["revision_id"] == env.revisions[1] and head["version"] == 2
        assert await env.owner.fetchval(
            "SELECT count(*) FROM living.acceptance_events WHERE tenant_id=$1 AND source_id=$2",
            TENANT, SOURCE,
        ) == 2
    finally:
        await client.aclose()


async def test_promotion_role_guard_allows_set_only_actor_chain_but_rejects_direct_owner_grant(
    product_env,
):
    env = product_env
    # The ordinary actor path is promotion-login -> SET-only r2p_* -> living_promoter;
    # TC046 exercises that valid path end-to-end. Direct sensitive-role grants must fail closed.
    await env.promotion_db.assert_promotion_role()
    await env.owner.execute(f"GRANT living_owner TO {env.promotion_login}")
    with pytest.raises(RuntimeError, match="least-privilege contract"):
        await env.promotion_db.assert_promotion_role()


async def test_promotion_role_guard_rejects_nested_set_only_sensitive_role_chain(product_env):
    env = product_env
    await env.promotion_db.assert_promotion_role()

    intermediary = "r2p_nested_" + uuid.uuid4().hex[:12]
    await env.owner.execute(f"CREATE ROLE {intermediary} NOLOGIN")
    await env.owner.execute(
        f"GRANT {intermediary} TO {env.actor_role} WITH INHERIT FALSE, SET TRUE"
    )
    await env.owner.execute(
        f"GRANT living_owner TO {intermediary} WITH INHERIT FALSE, SET TRUE"
    )

    with pytest.raises(RuntimeError, match="least-privilege contract"):
        await env.promotion_db.assert_promotion_role()
