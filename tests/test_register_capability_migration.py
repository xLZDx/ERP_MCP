from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_register_capability_profile_migration_is_additive_and_json_scoped():
    sql = (ROOT / "db/migrations/005_register_capability_profiles.sql").read_text(
        encoding="utf-8"
    )

    assert "register_capabilities_json jsonb NOT NULL DEFAULT '{}'::jsonb" in sql
    assert "jsonb_typeof(register_capabilities_json) = 'object'" in sql
    assert "VALUES (5)" in sql
    assert "DROP TABLE" not in sql.upper()
