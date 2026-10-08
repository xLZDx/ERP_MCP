"""Static preflight lint of the G1 migration text; not a replacement for PostgreSQL integration.

These checks only grep the SQL files. Nothing here is executed on PostgreSQL.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "phase2"


def test_g1_migration_files_present():
    """Static preflight lint: all three migrations exist."""
    assert (MIGRATIONS / "001_living_registry.sql").is_file()
    assert (MIGRATIONS / "002_job_cursor_functions.sql").is_file()
    assert (MIGRATIONS / "003_security_hardening.sql").is_file()


def test_g1_core_boundaries_declared():
    """Static preflight lint: core tables, RLS, immutability and bitemporal APIs are declared."""
    sql = (MIGRATIONS / "001_living_registry.sql").read_text(encoding="utf-8")
    required = (
        "CREATE TABLE IF NOT EXISTS living.observations",
        "CREATE TABLE IF NOT EXISTS living.accepted_heads",
        "CREATE TABLE IF NOT EXISTS living.jobs",
        "CREATE TABLE IF NOT EXISTS living.cursors",
        "CREATE TABLE IF NOT EXISTS living.outbox",
        "CREATE TABLE IF NOT EXISTS living.schema_migrations",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS",
        "observations_immutable",
        "acceptance_immutable",
        "BEFORE TRUNCATE",
        "ingest_seq bigint GENERATED ALWAYS AS IDENTITY",
        "NEW.recorded_at := clock_timestamp()",
        "digest IS NOT NULL AND digest ~",
        "UNIQUE(tenant_id,source_id,model_key,to_version)",
        "jobs_one_running_per_source",
        "CONFLICTING_DIGEST",
        "IDEMPOTENCY_CONFLICT",
        "living.as_known_at",
        "living.as_effective_at",
        "living.promote_head",
    )
    missing = [fragment for fragment in required if fragment not in sql]
    assert not missing, missing
    assert "business_ai_app" not in sql


def test_g1_transaction_operations_declared():
    """Static preflight lint: job/cursor APIs, distinct error codes and null-safe checks exist."""
    sql = (MIGRATIONS / "002_job_cursor_functions.sql").read_text(encoding="utf-8")
    for fragment in ("living.acquire_job", "living.finish_job", "living.renew_lease",
                     "STALE_JOB_FENCE", "living.commit_cursor_page",
                     "SCOPE_REVOKED", "CURSOR_ALREADY_APPLIED",
                     "STALE_CURSOR_OR_SCOPE", "CONFLICTING_EVENT_DIGEST",
                     "IS DISTINCT FROM", "clock_timestamp()"):
        assert fragment in sql, fragment
    # lock order source -> job -> cursor -> outbox is textual order inside commit_cursor_page
    body = sql[sql.index("CREATE OR REPLACE FUNCTION living.commit_cursor_page"):]
    order = [body.index(x) for x in ("FROM living.sources", "FROM living.jobs",
                                     "FROM living.cursors", "INSERT INTO living.outbox")]
    assert order == sorted(order)


def test_g1_security_hardening_declared():
    """Static preflight lint: roles, grants, definer pinning and promote guards are declared."""
    sql = (MIGRATIONS / "003_security_hardening.sql").read_text(encoding="utf-8")
    for fragment in ("living_owner", "living_worker", "living_reader", "living_promoter",
                     "NOBYPASSRLS", "REVOKE ALL ON SCHEMA living FROM PUBLIC",
                     "REVOKE EXECUTE ON ALL FUNCTIONS", "ALTER DEFAULT PRIVILEGES",
                     "SECURITY DEFINER SET search_path = pg_catalog, pg_temp",
                     "CREATE TABLE IF NOT EXISTS living.role_scope",
                     "CREATE TABLE IF NOT EXISTS living.attestations",
                     "living.set_scope", "APPROVER_NOT_INDEPENDENT", "EVIDENCE_NOT_FOUND"):
        assert fragment in sql, fragment
    assert "TO living_promoter" in sql
    assert "ON living.tenants" in sql
    for fragment in ("living.add_role_scope", "living.rebase_scope", "living.claim_outbox",
                     "living.finish_outbox", "living_publisher", "ACCEPTANCE_ID_REUSED",
                     "CONFLICTING_ATTESTATION"):
        assert fragment in sql, fragment


def test_g1_migrations_are_whole_file_guarded():
    """Static preflight lint: each migration body runs only when its version is newly recorded."""
    for name, version in (("001_living_registry.sql", "001"), ("002_job_cursor_functions.sql", "002"),
                          ("003_security_hardening.sql", "003")):
        sql = (MIGRATIONS / name).read_text(encoding="utf-8")
        assert f"IF living.record_migration('{version}'" in sql, name
        assert "EXECUTE $body$" in sql and "$body$;\nEND IF;\nEND $mig$;" in sql, name
        if not name.startswith("003"):  # 003 keeps FOR SHARE only in the publisher claim/finish APIs
            assert "FOR SHARE" not in sql, name
