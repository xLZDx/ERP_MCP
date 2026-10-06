"""Non-destructive synthetic restore drill: creates two NEW PostgreSQL containers.

Existing databases/containers are never accepted, reused, stopped or removed. Retains backup,
evidence and both disposable instances so an operator can inspect them afterward.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import asyncpg

from business_ai_gateway.db import Database

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

ROLES = (
    "CREATE ROLE business_ai_app NOLOGIN; "
    "CREATE ROLE business_ai_admin NOLOGIN; "
    "CREATE ROLE business_ai_control_api NOLOGIN;"
)


def command(*args: str, env=None, timeout=120) -> str:
    try:
        return subprocess.run(
            args, cwd=REPO, env=env, check=True, capture_output=True, text=True, timeout=timeout
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        detail = re.sub(r"postgres(?:ql)?://\S+", "postgresql://REDACTED", detail)
        detail = re.sub(r"(?i)(password|secret|token)\s*[=:]\s*\S+", r"\1=REDACTED", detail)
        raise RuntimeError(
            f"child command failed: {Path(str(args[0])).name}; {detail[-1200:]}"
        ) from None


async def new_postgres(name: str, *, host_port: int | None = None) -> str:
    command(
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "-e",
        "POSTGRES_DB=business_ai",
        "-e",
        "POSTGRES_USER=business_ai",
        "-e",
        "POSTGRES_PASSWORD=synthetic-drill-only",
        "-p",
        f"127.0.0.1:{host_port or ''}:5432",
        "postgres:16-alpine",
    )
    deadline = time.monotonic() + 60
    while True:
        try:
            command(
                "docker",
                "exec",
                name,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-U",
                "business_ai",
                timeout=5,
            )
            break
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if time.monotonic() >= deadline:
                raise RuntimeError("Disposable PostgreSQL startup timed out") from None
            await asyncio.sleep(0.5)
    command(
        "docker",
        "exec",
        name,
        "psql",
        "-U",
        "business_ai",
        "-d",
        "business_ai",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        ROLES,
    )
    port = command("docker", "port", name, "5432/tcp").rsplit(":", 1)[-1]
    if not port.isdigit():
        raise RuntimeError("Unexpected loopback port binding")
    return f"postgresql://business_ai:synthetic-drill-only@127.0.0.1:{port}/business_ai"


async def seed_prior_schema(conn):
    company = uuid.uuid4()
    profile = uuid.uuid4()
    await conn.execute("""
        INSERT INTO bag.sources(source_id,project,kind,display_name,base_url,
                                username_secret_ref,password_secret_ref)
        VALUES('restore-synthetic','onec','onec_auto','Synthetic restore fixture',
               'https://synthetic.example.invalid/odata','synthetic-user-ref','synthetic-pass-ref')
    """)
    await conn.execute(
        """
        INSERT INTO bag.companies(company_id,source_id,external_ref,display_name)
        VALUES($1,'restore-synthetic','synthetic-organization','Synthetic Organization')
    """,
        company,
    )
    await conn.execute(
        """
        INSERT INTO bag.access_grants(grant_id,principal_kind,principal_id,source_id,company_id)
        VALUES($1,'subject','synthetic-operator','restore-synthetic',$2)
    """,
        uuid.uuid4(),
        company,
    )
    await conn.execute(
        """
        INSERT INTO bag.source_capabilities(source_id,metadata_fingerprint,compatibility_status,
            adapter_profile,metadata_supported,json_supported,atom_supported,entity_set_count,
            evidence_json,register_capabilities_json)
        VALUES('restore-synthetic',$1,'SUPPORTED','ODATA_JSON_V3',true,true,false,1,
               '{"kind":"SYNTHETIC_RESTORE_FIXTURE"}',
               '{"DrCrTurnovers":{"available":false,"evidence_source":"synthetic"}}')
    """,
        "a" * 64,
    )
    await conn.execute(
        """
        INSERT INTO bag.semantic_profiles(profile_id,source_id,company_id,preset_id,profile_name,
            profile_version,status,metadata_fingerprint,capability_fingerprint,
            profile_fingerprint,preset_repository,preset_upstream_sha,created_by,
            validation_evidence_json)
        VALUES($1,'restore-synthetic',$2,'synthetic','Restore fixture',1,'NEEDS_VALIDATION',
               $3,$3,$3,'synthetic fixture only',$3,'synthetic-operator',
               '{"reconciliation_status":"NOT_RUN","kind":"SYNTHETIC_RESTORE_FIXTURE"}')
    """,
        profile,
        company,
        "a" * 64,
    )
    await conn.execute(
        """
        INSERT INTO bag.semantic_mappings(mapping_id,profile_id,canonical_concept,mapping_json)
        VALUES($1,$2,'restore.fixture','{"kind":"SYNTHETIC_RESTORE_FIXTURE"}')
    """,
        uuid.uuid4(),
        profile,
    )
    await conn.execute(
        """
        INSERT INTO bag.semantic_profile_events(event_id,profile_id,actor,action)
        VALUES($1,$2,'synthetic-operator','CREATED')
    """,
        uuid.uuid4(),
        profile,
    )
    for outcome in ("success", "denied", "error"):
        await conn.execute(
            """
            INSERT INTO bag.audit_events(event_id,principal_subject,client_id,tool_name,
                source_id,company_id,outcome,duration_ms,detail_code,request_id)
            VALUES($1,'synthetic-operator','synthetic-client','restore.fixture',
                   'restore-synthetic',$2,$3,0,'SYNTHETIC_RESTORE_FIXTURE',$4)
        """,
            uuid.uuid4(),
            company,
            outcome,
            uuid.uuid4(),
        )


async def fingerprint(conn) -> dict:
    names = await conn.fetch("""
        SELECT tablename FROM pg_tables WHERE schemaname='bag' ORDER BY tablename
    """)
    result = {}
    for row in names:
        name = row["tablename"]
        if not re.fullmatch(r"[a-z_]+", name):
            raise RuntimeError("Unsafe schema table identifier")
        documents = await conn.fetch(
            f'SELECT to_jsonb(t)::text AS document FROM bag."{name}" t ORDER BY document'
        )
        content = "\n".join(r["document"] for r in documents).encode()
        result[name] = {"rows": len(documents), "sha256": hashlib.sha256(content).hexdigest()}
    return result


async def run(artifact_dir: Path):
    from scripts.migrate import load_migrations, migrate

    started = time.monotonic()
    run_id = uuid.uuid4().hex[:12]
    source = f"erpmcp-restore-source-{run_id}"
    target = f"erpmcp-restore-target-{run_id}"
    print(f"Creating NEW disposable instances: {source}, {target}", flush=True)
    source_url = await new_postgres(source)
    source_conn = await asyncpg.connect(source_url)
    try:
        for migration in load_migrations():
            if migration.version > 7:
                break
            await source_conn.execute(migration.sql)
        await seed_prior_schema(source_conn)
        # Use the real identity-aware runner for integration v8/v9 plus Admin 010-013.
        # Raw SQL execution would create schema objects without the immutable ledger columns.
        await migrate(source_conn, load_migrations())
        before = await fingerprint(source_conn)
    finally:
        await source_conn.close()
    backup = artifact_dir / "control-plane.dump"
    command(
        "docker",
        "exec",
        source,
        "pg_dump",
        "-U",
        "business_ai",
        "-d",
        "business_ai",
        "-Fc",
        "-f",
        "/tmp/control-plane.dump",
    )
    command("docker", "cp", f"{source}:/tmp/control-plane.dump", str(backup))
    target_url = await new_postgres(target)
    command("docker", "cp", str(backup), f"{target}:/tmp/control-plane.dump")
    command(
        "docker",
        "exec",
        target,
        "pg_restore",
        "-U",
        "business_ai",
        "-d",
        "business_ai",
        "--exit-on-error",
        "/tmp/control-plane.dump",
    )
    target_conn = await asyncpg.connect(target_url)
    try:
        after = await fingerprint(target_conn)
    finally:
        await target_conn.close()
    if before != after:
        raise RuntimeError("Restored row fingerprints differ")
    runtime_db = Database(target_url)
    try:
        await runtime_db.start()
        await runtime_db.assert_schema()
        assert await runtime_db.ping()
    finally:
        await runtime_db.close()
    test_env = {
        **os.environ,
        "BAG_PRIVILEGE_TEST_DATABASE_URL": target_url,
        "PYTHONPATH": str(REPO / "src"),
    }
    privileges = command(sys.executable, "scripts/check_db_privileges.py", env=test_env)
    tests = command(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_registry_postgres_integration.py",
        env=test_env,
    )
    result = {
        "kind": "SYNTHETIC_LOCAL_RESTORE_DRILL",
        "status": "PASS",
        "release_sha": command("git", "rev-parse", "HEAD"),
        "postgres_version": command("docker", "exec", target, "postgres", "--version"),
        "source_container": source,
        "restored_container": target,
        "migration_path": "empty -> legacy v1-v7 -> seed -> identity-aware v1-v13 -> backup -> fresh instance restore",
        "backup_sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "tables": after,
        "privileges": privileges,
        "integration_tests": tests,
        "runtime_schema_readiness": "PASS",
        "duration_seconds": round(time.monotonic() - started, 3),
        "native_reconciliation": "NOT_RUN",
        "production_pitr": "NOT_RUN",
    }
    (artifact_dir / "evidence.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2), flush=True)
    print(f"Artifacts retained at {artifact_dir}; containers retained for inspection.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path)
    args = parser.parse_args()
    # Always a new directory: refuses to overwrite an earlier drill artifact.
    output = args.artifact_dir
    if output is None:
        output = Path(tempfile.mkdtemp(prefix="erp-mcp-restore-"))
    else:
        output.mkdir(parents=True, exist_ok=False)
    asyncio.run(run(output.resolve()))
