"""Static G1 migration contract checks; not a replacement for PostgreSQL integration."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "db" / "phase2"


def test_g1_migration_files_present():
    assert (MIGRATIONS / "001_living_registry.sql").is_file()
    assert (MIGRATIONS / "002_job_cursor_functions.sql").is_file()


def test_g1_core_boundaries_declared():
    sql = (MIGRATIONS / "001_living_registry.sql").read_text(encoding="utf-8")
    required = (
        "CREATE TABLE IF NOT EXISTS living.observations",
        "CREATE TABLE IF NOT EXISTS living.accepted_heads",
        "CREATE TABLE IF NOT EXISTS living.jobs",
        "CREATE TABLE IF NOT EXISTS living.cursors",
        "CREATE TABLE IF NOT EXISTS living.outbox",
        "ENABLE ROW LEVEL SECURITY",
        "FORCE ROW LEVEL SECURITY",
        "observations_immutable",
        "acceptance_immutable",
        "living.as_known_at",
        "living.as_effective_at",
        "living.promote_head",
    )
    assert all(fragment in sql for fragment in required)
    assert "business_ai_app" not in sql


def test_g1_transaction_operations_declared():
    sql = (MIGRATIONS / "002_job_cursor_functions.sql").read_text(encoding="utf-8")
    for fragment in ("living.acquire_job", "living.finish_job",
                     "STALE_JOB_FENCE", "living.commit_cursor_page",
                     "STALE_CURSOR_OR_SCOPE", "CONFLICTING_EVENT_DIGEST"):
        assert fragment in sql
