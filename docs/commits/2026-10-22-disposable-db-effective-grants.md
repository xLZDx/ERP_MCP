# Change record: capture disposable-database effective grants

Date: 2026-10-22  
Scope: read-only WP0 database privilege observation; no repository behavior changed.

## Evidence collected

The database-reviewer loaded the disposable lane connection through `LaneEnv` in process and queried PostgreSQL catalogs without printing the DSN or credentials. No files, database state, or processes were changed.

- The connected database was `business_ai`; the `change_ledger` schema is absent. S13 object grants therefore remain `NOT_VERIFIED` on this database.
- `bag.schema_migrations` contained versions 1–14. `SELECT version,name,applied_at FROM bag.schema_migrations WHERE version=15` returned zero rows, so migration 015 is not recorded as applied here.
- `bag.record_capability_observation(...)` is `SECURITY DEFINER`; its observed ACL includes `EXECUTE` for `PUBLIC`. `has_function_privilege` consequently reports execution for application, admin, control, and owner roles. This is consistent with the missing migration 015 and does not establish an issue on Ivan's separate stack.
- Role flags: `business_ai` is superuser with `BYPASSRLS`, role/database creation and replication privileges; `business_ai_admin`, `business_ai_control_api`, and `business_ai_app` are non-superuser roles without `BYPASSRLS`. No direct membership edges among those four roles were found.
- Effective table privileges were checked with `has_table_privilege`; catalog ACLs were used because `information_schema.role_table_grants` exposed only admin grants under the inspection session. The app role has SELECT over app tables and INSERT on `audit_events`; admin has management-table SELECT/INSERT/UPDATE, audit/migration SELECT and `semantic_profile_events` INSERT; control has scoped management SELECT/INSERT/UPDATE, including `admin_audit_events` and `admin_idempotency`.

## Interpretation and limits

The source change in `db/migrations/015_capability_observation_execute_boundary.sql` has not been applied to this disposable database. The observed PUBLIC privilege is therefore runtime evidence for the pre-015 database state, not proof that the revised migration failed. The superuser role will retain PostgreSQL superuser capabilities even after ordinary ACL revocation; the intended post-migration checks concern PUBLIC plus the named app/admin/control roles.

This inspection does not prove grants on Ivan's host, production, or a database with the S13 schema. It did not apply migration 015. No conclusion about a production or shared-system privilege is made.

## Verification state and next action

- Completed: read-only catalog and effective-role inspection on the local disposable lane database.
- Not run: migration application or post-migration privilege verification.
- Next: after in-scope coding is complete, the authorized test and database-review roles should apply migration 015 only to the disposable lane and verify PUBLIC is revoked, `business_ai_app` retains the required EXECUTE privilege, and `business_ai_admin`/`business_ai_control_api` do not gain it. Keep the superuser finding separate from ordinary ACL checks.
- S13 grant qualification remains open because this database has no `change_ledger` schema.

## Ownership

- Accountable task owner: operator.
- Executor: Codex.
- Read-only inspection role: database-reviewer.
- Next verification owners: functional-test-reviewer and database-reviewer, after coding is complete.
