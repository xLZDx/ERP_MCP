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
