from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_capability_drift_migration_is_additive_and_admin_ack_is_narrow():
    sql = (ROOT / "db/migrations/004_capability_drift_lifecycle.sql").read_text(
        encoding="utf-8"
    )

    assert "ADD COLUMN IF NOT EXISTS previous_metadata_fingerprint text" in sql
    assert "ADD COLUMN IF NOT EXISTS drift_status text NOT NULL DEFAULT 'UNKNOWN'" in sql
    assert "drift_detected_at timestamptz" in sql
    assert "drift_acknowledged_at timestamptz" in sql
    assert "GRANT UPDATE (drift_status, drift_acknowledged_at)" in sql
    assert "VALUES (4)" in sql
    assert "DROP TABLE" not in sql.upper()


def test_capability_observation_boundary_has_no_fake_fingerprint_or_runtime_ack():
    sql = (ROOT / "db/migrations/014_capability_observation_boundary.sql").read_text(
        encoding="utf-8"
    )
    assert "ALTER COLUMN metadata_fingerprint DROP NOT NULL" in sql
    assert "'NEEDS_VALIDATION'" in sql
    assert "SECURITY DEFINER" in sql
    assert "REVOKE INSERT, UPDATE ON bag.source_capabilities FROM business_ai_app" in sql
    assert "GRANT UPDATE (evidence_json) ON bag.source_capabilities TO business_ai_app" in sql
    assert "GRANT EXECUTE ON FUNCTION bag.record_capability_observation" in sql
    assert "schema_migrations" not in sql
    assert "metadata-error" not in sql
