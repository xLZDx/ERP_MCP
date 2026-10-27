# WP2 Effective Grants Recheck — 2026-10-26

## Ownership and disposition

- Accountable owner: operator, by explicit delegation.
- Executor: Codex; read-only catalog observation performed by the `database-reviewer` role.
- Technical boundary: disposable PostgreSQL instance used for ERP_MCP phase-2 work.
- Result: candidate S13 grants are `NOT_MEASURABLE`; migration 027 was not installed.

## Invocation and transaction

Generated 2026-10-26 09:42:21 UTC. The read-only script ran from `D:\Repo\ERP_MCP`, imported `LaneEnv` from `scripts.real1c.gateway_client`, called `LaneEnv.load()`, and connected with `asyncpg.connect(env.dsn("admin"), timeout=10, command_timeout=15)`. The connection, DSN and credentials were not printed. Catalog reads ran inside `conn.transaction(isolation="repeatable_read", readonly=True)`.

## Catalog scope and observed result

- Session/server context: `current_database()`, `current_user`, `session_user`, transaction isolation/read-only settings, `current_setting('server_version')`, and `inet_server_port()`.
- Candidate schema/type: `to_regnamespace('change_ledger')` and `to_regtype('change_ledger.private_writer_identity_v1')` both showed the candidate absent.
- Role attributes: `pg_roles` for `business_ai_admin`, `business_ai_app`, `business_ai_control_api`, `business_ai`, `business_ai_private_writer`, `private_writer_evidence_ingest`, `ledger_owner`, and `worker_role`.
- Memberships: `pg_auth_members` joined to `pg_roles` for those names.
- Table grants: `information_schema.role_table_grants` filtered to `table_schema='change_ledger'`; no rows returned.
- Routine ACLs: `pg_proc` joined to `pg_namespace`, filtered to `change_ledger` and candidate private-writer/legacy mutation names, selecting owner, `prosecdef`, and `has_function_privilege` for the listed roles. No routine rows existed, so `has_function_privilege` was not evaluated for any candidate routine.
- The current database was `business_ai`, server version PostgreSQL 16.15, port 5432. Existing `business_ai_admin`, `business_ai_app`, and `business_ai_control_api` were non-superuser and `NOBYPASSRLS`; separate role `business_ai` was superuser and `BYPASSRLS`.

## Evidence boundary and next action

This read-only result does not prove post-install grants, deny a candidate grant, or qualify migration 027. Do not install the candidate merely to produce an ACL result before source coding and review close. Codex owns continuing source closure; after the candidate reaches the approved disposable qualification phase, install it there and repeat the exact per-role `has_function_privilege`, membership, table-grant and owner checks. No database state, grants, files outside the ERP_MCP repository, or migration state were changed by the catalog review.
