from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_company_migration_preserves_source_scope_and_runtime_read_only_policy():
    sql = (ROOT / "db/migrations/003_company_scope_and_audit_provenance.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE IF NOT EXISTS bag.companies" in sql
    assert "UNIQUE(source_id, external_ref)" in sql
    assert "FOREIGN KEY(company_id, source_id)" in sql
    assert "company_id IS NULL OR (source_id IS NOT NULL AND all_sources = false)" in sql
    assert "effect text NOT NULL DEFAULT 'allow'" in sql
    assert "CHECK (effect IN ('allow', 'deny'))" in sql
    assert "GRANT SELECT ON bag.companies TO business_ai_app" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON bag.companies TO business_ai_admin" in sql
    assert "audit_events_response_bytes_nonnegative" in sql
    assert "DROP TABLE" not in sql.upper()
    assert "ADD COLUMN IF NOT EXISTS request_id uuid NOT NULL" in sql
    assert "ADD COLUMN IF NOT EXISTS metadata_fingerprint text" in sql
    assert "ADD COLUMN IF NOT EXISTS response_bytes bigint" in sql
    assert "GRANT SELECT ON bag.companies TO business_ai_app" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON bag.companies TO business_ai_admin" in sql
    assert "VALUES (3)" in sql
