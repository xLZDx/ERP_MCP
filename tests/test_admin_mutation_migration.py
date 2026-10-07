from pathlib import Path


def test_admin_mutation_migration_is_additive_append_only_and_least_privilege():
    sql = Path("db/migrations/011_admin_mutation_control.sql").read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS row_version" in sql
    assert "CREATE TABLE IF NOT EXISTS bag.admin_audit_events" in sql
    assert "CREATE TABLE IF NOT EXISTS bag.admin_idempotency" in sql
    assert "BEFORE UPDATE OR DELETE ON bag.admin_audit_events" in sql
    assert "business_ai_control_api" in sql
    assert "GRANT INSERT ON bag.semantic_profile_events, bag.admin_audit_events" in sql
    assert "REVOKE DELETE ON ALL TABLES IN SCHEMA bag FROM business_ai_control_api" in sql
    assert "REVOKE UPDATE, DELETE ON bag.audit_events, bag.admin_audit_events" in sql
    assert "INSERT INTO bag.schema_migrations" not in sql
