"""Release gate guards: unresolved security contracts must never be mistaken for a pass.

These tests are static preflight lint over the SQL text; real PostgreSQL integration remains
mandatory (see test_g1_postgres_integration.py). Nothing here is executed on PostgreSQL.
"""
from pathlib import Path

MIGRATION_DIR = Path(__file__).resolve().parents[2] / "db" / "phase2"


def test_migrations_are_isolated_from_r1_schema():
    for path in sorted(MIGRATION_DIR.glob("*.sql")):
        body = path.read_text(encoding="utf-8").lower()
        assert "bag.sources" not in body
        assert "bag.access_grants" not in body
        assert "business_ai_app" not in body
        assert "business_ai_admin" not in body


def test_migrations_must_be_explicitly_transactional():
    for path in sorted(MIGRATION_DIR.glob("*.sql")):
        body = path.read_text(encoding="utf-8").strip().lower()
        assert body.startswith("--")
        assert "begin;" in body
        assert body.endswith("commit;")


def test_unapproved_sql_does_not_claim_release_authority():
    for path in MIGRATION_DIR.glob("*.sql"):
        body = path.read_text(encoding="utf-8").lower()
        assert "production go granted" not in body
        assert "drop schema bag" not in body
        assert "grant all on schema bag" not in body
