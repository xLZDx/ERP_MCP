from pathlib import Path


def test_business_capability_migration_separates_roles_assignments_and_overrides():
    sql = Path("db/migrations/010_business_capability_policy.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS bag.business_roles" in sql
    assert "CREATE TABLE IF NOT EXISTS bag.business_role_capabilities" in sql
    assert "CREATE TABLE IF NOT EXISTS bag.business_role_assignments" in sql
    assert "CREATE TABLE IF NOT EXISTS bag.capability_overrides" in sql
    assert "effect IN ('allow','deny')" in sql
    assert "business_ai_app" in sql and "GRANT SELECT ON" in sql
    assert "VALUES (10)" in sql
