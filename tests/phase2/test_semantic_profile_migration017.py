"""Focused PostgreSQL contract test for semantic-profile migration 017."""
from __future__ import annotations

import json
from uuid import uuid4

import asyncpg
import pytest

from _pg_harness import disposable_cluster
from scripts.migrate import load_migrations, migrate

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _cases() -> list[dict[str, str]]:
    return [
        {"case_id": f"case-{index}", "status": "PASS", "native_report_ref": f"reports/{index}"}
        for index in range(10)
    ]


async def _insert_profile(
    conn: asyncpg.Connection, source_id: str, profile_id, evidence: dict
) -> None:
    await conn.execute(
        """INSERT INTO bag.semantic_profiles(
             profile_id,source_id,preset_id,profile_name,profile_version,status,
             metadata_fingerprint,capability_fingerprint,profile_fingerprint,
             preset_repository,preset_upstream_sha,validation_evidence_json,
             created_by,validated_by,validated_at
           ) VALUES($1,$2,$3,'synthetic profile',1,'VALIDATED',$4,$4,$4,
                    'synthetic fixture',$5,$6::jsonb,'test','test',now())""",
        profile_id,
        source_id,
        f"migration017-{profile_id}",
        "a" * 64,
        "a" * 40,
        json.dumps(evidence),
    )


@pytest.mark.asyncio
async def test_migration_017_preserves_legacy_rows_but_requires_machine_basis_on_writes():
    async with disposable_cluster() as (dsn, container_name, _owner_token):
        print(
            f"Disposable PostgreSQL target: {container_name}; "
            "the repository harness binds it to 127.0.0.1 and verifies ownership for cleanup."
        )
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(
                "CREATE ROLE business_ai_app NOLOGIN; "
                "CREATE ROLE business_ai_admin NOLOGIN; "
                "CREATE ROLE business_ai_control_api NOLOGIN; "
                "CREATE ROLE business_ai_capability_writer NOLOGIN; "
                "CREATE ROLE business_ai_capability_acceptor NOLOGIN"
            )
            migrations = load_migrations()
            assert [migration.version for migration in migrations] == list(range(1, 18))
            await migrate(conn, migrations[:16])

            source_id = f"b3-migration017-{uuid4().hex}"
            await conn.execute(
                "INSERT INTO bag.sources(source_id,project,kind,display_name,base_url) "
                "VALUES($1,'onec','onec_odata','Synthetic B3 migration fixture',"
                "'https://synthetic.example.invalid/odata')",
                source_id,
            )

            legacy_id = uuid4()
            legacy_evidence = {"native_reconciliation_cases": _cases()}
            await _insert_profile(conn, source_id, legacy_id, legacy_evidence)

            await migrate(conn, migrations)

            recorded = await conn.fetchrow(
                "SELECT name,checksum FROM bag.schema_migrations WHERE version=17"
            )
            assert recorded is not None
            assert recorded["name"] == migrations[-1].name
            assert recorded["checksum"] == migrations[-1].checksum
            constraint = await conn.fetchrow(
                """SELECT convalidated,pg_get_constraintdef(oid) AS definition
                   FROM pg_constraint
                   WHERE conrelid='bag.semantic_profiles'::regclass
                     AND conname='semantic_profiles_validation_machine_evidence_only'"""
            )
            assert constraint is not None
            assert constraint["convalidated"] is False
            assert "evidence_basis" in constraint["definition"]

            assert await conn.fetchval(
                "SELECT validation_evidence_json->>'evidence_basis' "
                "FROM bag.semantic_profiles WHERE profile_id=$1",
                legacy_id,
            ) is None
            with pytest.raises(asyncpg.CheckViolationError) as legacy_update:
                await conn.execute(
                    "UPDATE bag.semantic_profiles SET profile_name='updated' WHERE profile_id=$1",
                    legacy_id,
                )
            assert legacy_update.value.constraint_name == (
                "semantic_profiles_validation_machine_evidence_only"
            )

            invalid_evidence = (
                {"native_reconciliation_cases": _cases()},
                {"native_reconciliation_cases": _cases(), "evidence_basis": None},
                {"native_reconciliation_cases": _cases(), "evidence_basis": "NATIVE"},
            )
            for evidence in invalid_evidence:
                with pytest.raises(asyncpg.CheckViolationError) as invalid_insert:
                    await _insert_profile(conn, source_id, uuid4(), evidence)
                assert invalid_insert.value.constraint_name == (
                    "semantic_profiles_validation_machine_evidence_only"
                )

            machine_id = uuid4()
            machine_evidence = {
                "native_reconciliation_cases": _cases(),
                "evidence_basis": "MACHINE",
            }
            await _insert_profile(conn, source_id, machine_id, machine_evidence)
            with pytest.raises(asyncpg.CheckViolationError) as machine_update:
                await conn.execute(
                    "UPDATE bag.semantic_profiles "
                    "SET validation_evidence_json=jsonb_set(validation_evidence_json, "
                    "'{evidence_basis}', '\"NATIVE\"'::jsonb) WHERE profile_id=$1",
                    machine_id,
                )
            assert machine_update.value.constraint_name == (
                "semantic_profiles_validation_machine_evidence_only"
            )
            assert await conn.fetchval(
                "SELECT count(*) FROM bag.semantic_profiles WHERE profile_id=$1 "
                "AND validation_evidence_json->>'evidence_basis'='MACHINE'",
                machine_id,
            ) == 1
        finally:
            await conn.close()
