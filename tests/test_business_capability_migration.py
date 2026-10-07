import re
from pathlib import Path

from business_ai_gateway.business_policy import CAPABILITY_KEYS


def test_business_capability_migration_separates_roles_assignments_and_overrides():
    sql = Path("db/migrations/012_business_capability_policy.sql").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS bag.business_roles" in sql
    assert "CREATE TABLE IF NOT EXISTS bag.business_role_capabilities" in sql
    assert "CREATE TABLE IF NOT EXISTS bag.business_role_assignments" in sql
    assert "CREATE TABLE IF NOT EXISTS bag.capability_overrides" in sql
    assert "effect IN ('allow','deny')" in sql
    assert "business_ai_app" in sql and "GRANT SELECT ON" in sql
    assert "INSERT INTO bag.schema_migrations" not in sql
    assert "onec.raw.read" not in sql


def test_seeded_capabilities_match_runtime_allowlist():
    sql = Path("db/migrations/012_business_capability_policy.sql").read_text(
        encoding="utf-8"
    )
    section = sql.split(
        "INSERT INTO bag.business_role_capabilities(role_id, capability_key)",
        1,
    )[1].split("ON CONFLICT(role_id, capability_key)", 1)[0]
    seeded = {
        capability
        for _role, capability in re.findall(
            r"\('([^']+)','([^']+)'\)",
            section,
        )
    }

    assert seeded == CAPABILITY_KEYS - {"onec.raw.read"}
