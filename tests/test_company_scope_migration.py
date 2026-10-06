from pathlib import Path


def test_company_scope_mapping_migration_is_profile_bound_candidate_only_configuration():
    sql = Path("db/migrations/013_company_scope_mappings.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS bag.company_scope_mappings" in sql
    assert "REFERENCES bag.semantic_profiles(profile_id)" in sql
    assert "literal_kind IN ('guid','string')" in sql
    assert "GRANT SELECT ON bag.company_scope_mappings TO business_ai_app" not in sql
    assert "GRANT SELECT, INSERT, UPDATE ON bag.company_scope_mappings TO business_ai_control_api" in sql
    assert "business_ai_control_api" in sql
    assert "INSERT INTO bag.schema_migrations" not in sql
