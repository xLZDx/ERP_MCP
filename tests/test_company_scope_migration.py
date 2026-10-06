from pathlib import Path


def test_company_scope_mapping_migration_is_profile_bound_and_readable_by_runtime():
    sql = Path("db/migrations/011_company_scope_mappings.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS bag.company_scope_mappings" in sql
    assert "REFERENCES bag.semantic_profiles(profile_id)" in sql
    assert "literal_kind IN ('guid','string')" in sql
    assert "GRANT SELECT ON bag.company_scope_mappings TO business_ai_app" in sql
    assert "business_ai_control_api" in sql
    assert "VALUES (11)" in sql
