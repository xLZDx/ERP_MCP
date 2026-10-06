from pathlib import Path


def test_admin_platform_role_migration_is_additive_and_read_only_for_runtime():
    sql = Path("db/migrations/010_admin_platform_roles.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS bag.platform_role_bindings" in sql
    assert "PLATFORM_ADMIN" in sql
    assert "SOURCE_ADMIN" in sql
    assert "ACCESS_ADMIN" in sql
    assert "PROFILE_ADMIN" in sql
    assert "AUDITOR" in sql
    assert "GRANT SELECT ON bag.platform_role_bindings TO business_ai_app" in sql
    assert "INSERT, UPDATE ON bag.platform_role_bindings TO business_ai_app" not in sql
    assert "DELETE ON bag.platform_role_bindings TO business_ai_app" not in sql
    assert "platform_role_bindings_scope_check" in sql
    assert "role_name <> 'PLATFORM_ADMIN' AND source_id IS NOT NULL" in sql
    assert "INSERT INTO bag.schema_migrations" not in sql
