# WP2 effective-grants recheck — 2026-10-22

## Scope and method

This is a point-in-time, read-only audit of the disposable PostgreSQL database exposed on host loopback port `18432`. Connections used the repository virtual environment, `LaneEnv.load()`, and per-role DSNs loaded only in process. Queries ran in read-only transactions and inspected role attributes, memberships, `bag` table grants, `has_table_privilege`, `has_function_privilege`, function ACL entries, and the aggregate schema-migration version range. No DSN, secret, or business-table row was emitted or queried; no migration, test, or file write was performed. The source migration and verifier were read only to compare the intended grant boundary with the measured database state.

The observed database was `business_ai`. The report records current effective privileges; it does not establish the identity of a future service process or a production writer boundary.

## Role attributes

| Role | Effective attributes and memberships |
|---|---|
| `business_ai` | Superuser; can create roles and databases; replication and RLS bypass attributes are enabled. It has no non-system role memberships. This owner/admin identity is not evidence that an application uses it. |
| `business_ai_admin` | No superuser, role/database creation, replication, or RLS-bypass attributes; no non-system role memberships. |
| `business_ai_app` | No superuser, role/database creation, replication, or RLS-bypass attributes; no non-system role memberships. |
| `business_ai_control_api` | No superuser, role/database creation, replication, or RLS-bypass attributes; no non-system role memberships. |

## Effective `bag` table privileges

`has_table_privilege` agreed with the per-role grant rows. No table grant to `business_ai_admin`, `business_ai_app`, or `business_ai_control_api` was grantable.

| Role | Effective table privileges |
|---|---|
| `business_ai` | All seven table privilege types on all 17 inspected `bag` relations; this is consistent with its superuser attribute. |
| `business_ai_admin` | `SELECT` on 15 relations, `INSERT` on 12, and `UPDATE` on 11. `INSERT`, `SELECT`, and `UPDATE`: `access_grants`, `business_role_assignments`, `business_role_capabilities`, `business_roles`, `capability_overrides`, `companies`, `company_scope_mappings`, `platform_role_bindings`, `semantic_mappings`, `semantic_profiles`, `sources`. `INSERT` and `SELECT`: `semantic_profile_events`. `SELECT` only: `audit_events`, `schema_migrations`, `source_capabilities`. |
| `business_ai_app` | `SELECT` on 14 relations; `INSERT` only on `audit_events`. `SELECT` only: `access_grants`, `business_role_assignments`, `business_role_capabilities`, `business_roles`, `capability_overrides`, `companies`, `platform_role_bindings`, `schema_migrations`, `semantic_mappings`, `semantic_profile_events`, `semantic_profiles`, `source_capabilities`, `sources`. There is no `company_scope_mappings` grant. |
| `business_ai_control_api` | `SELECT` on 17 relations, `INSERT` on 12, and `UPDATE` on 10. `INSERT`, `SELECT`, and `UPDATE`: `access_grants`, `admin_idempotency`, `business_role_assignments`, `capability_overrides`, `companies`, `company_scope_mappings`, `platform_role_bindings`, `semantic_mappings`, `semantic_profiles`, `sources`. `INSERT` and `SELECT`: `admin_audit_events`, `semantic_profile_events`. `SELECT` only: `audit_events`, `business_role_capabilities`, `business_roles`, `schema_migrations`, `source_capabilities`. |

No row-level security policy is inferred from these grant results. The separate WP0 inventory reports no RLS-enabled or forced-RLS relation among the inspected `bag` tables; that is table metadata, not a substitute for application-level authorization review.

## Effective function privileges

Seven `bag` routines were checked. For `business_ai_app`, `business_ai_admin`, and `business_ai_control_api`, five returned `has_function_privilege(..., 'EXECUTE') = true`; two trigger functions returned `false`:

- `invalidate_semantic_profiles_on_metadata_drift()`
- `invalidate_validated_profile_on_mapping_change()`

The five routines returning `true` for those three roles were `native_reconciliation_evidence_valid(evidence jsonb)`, `record_capability_observation(...)`, `reject_admin_audit_mutation()`, `reject_audit_mutation()`, and `reject_semantic_profile_event_mutation()`. These are effective privileges, not necessarily direct per-role ACL entries: `record_capability_observation(...)` is executable by all three roles through a `PUBLIC EXECUTE` ACL. Trigger execution does not establish that an application role can invoke a trigger function directly.

The same read-only inspection found 14 rows in `bag.schema_migrations`, versions 1 through 14, with no version 15. Migration `db/migrations/015_capability_observation_execute_boundary.sql` is therefore not applied in this database. Its source revokes `EXECUTE` from `PUBLIC`, `business_ai_admin`, and `business_ai_control_api`, grants it to `business_ai_app`, and checks those conditions; `scripts/verify_schema.py` asserts the same boundary. The currently observed `PUBLIC EXECUTE` is a real environment drift from that source contract, not evidence that migration 015 is incorrect. The expected post-015 effective privileges remain **NOT_VERIFIED** until the disposable schema is brought to the declared migration level and re-audited. No migration was run during this audit.

The pre-existing mutable WP0 evidence draft said that all seven routines were executable by app/admin/control. This recheck contradicts that sentence; the draft has since been corrected. It does not determine whether direct `EXECUTE` is required for the two trigger functions.

## S13 boundary and 1C evidence

The `change_ledger` schema was absent in this database, so S13 installed grants and the effective privileges for a private writer cannot be measured here. S13 grants remain **NOT_VERIFIED** until the approved disposable schema is bootstrapped and audited after implementation.

The existing `testlane/onec_extension/STATUS.md` records CT14 `CT14Писатель` measurements on clone `818HA_p2diff`, including the measured object/right inventory (53 objects) and refusal of deletion and administrative rights. `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` sections 4 and 7 corroborate the measured clone rights and reconciliation. These are clone results only; they do not establish live Ivan-host grants.

## Limits and next actions

- No exact audit timestamp was recorded; the date above is the host-context date, not a query timestamp.
- The WP0 draft's all-seven statement and CT14 path have been corrected in the current working tree while preserving its unrelated pending edits. Exact-patch review and local commit remain pending. Accountable owner: operator; executor: Codex. The author of the pre-existing transport-verification paragraph is not established here.
- After the coding phase is complete, the functional/E2E test roles may prepare the approved disposable database through migration 015 and run the mapped schema verification. Then `database-reviewer` must re-read the installed ACLs in a read-only transaction. Accountable owner: operator; executor: Codex; no separately named database-service owner is established in the reviewed project records.
- Recheck `change_ledger` only after the S13 disposable schema exists; until then no S13 grant or writer-boundary acceptance is implied. The owner of the future installed schema has not been established; `database-reviewer` owns the independent grant review, not the service.
- No test, scan, migration, database write, COM call, service restart, push, or PR was performed.

## Read-only effective-grants reconfirmation — current-turn database-reviewer audit (2026-10-23)

The `database-reviewer` performed a second catalog-only inspection from `D:\Repo\ERP_MCP` using `.venv\Scripts\python.exe`, `LaneEnv.load()`, and the configured disposable testbed target at host loopback port `18432`. The environment target value was inspected only in process; DSNs, credentials, tokens, business rows, and query values were not printed or saved. For each of `business_ai_admin`, `business_ai_app`, and `business_ai_control_api` (plus the owner context), the reviewer opened a database session and made the transaction read-only before catalog SELECTs. It queried `pg_roles`, `pg_auth_members`, `information_schema.role_table_grants`, `has_table_privilege`, and `has_function_privilege` for the configured roles/routines. No schema/data write, migration, test, check, COM call, or service action occurred.

The database was `business_ai`, PostgreSQL `16.15` (`server_version_num=160015`). The container-side address differed from loopback because host port `18432` is published by Docker; the configured host target was loopback. `change_ledger` remained absent, so installed S13 grants and writer-role rights remain **NOT_VERIFIED**. The role flags/membership state and effective table/function privilege layout matched the 2026-10-22 inventory above: `business_ai` retained superuser/create-role/create-database/replication/RLS-bypass attributes; the three application roles lacked those attributes and had no memberships among the inspected set. The reviewer observed `information_schema.role_table_grants` row totals of 211 in owner context, 38 for admin, 15 for app, and 39 for control; the seven inspected `bag` routines had effective EXECUTE for all seven in owner context and five true/two false for each application role, matching the detailed function list above. No precise query timestamp was captured; this is a same-turn reconfirmation, not a time-stamped audit event.

**Limit:** this is local disposable-lane evidence only. It does not establish Ivan-host/production rights, application process identity, post-migration `bag` grants, S13 `change_ledger` ACLs, or the physical writer transaction boundary. Those remain unverified. Recheck the new S13 schema only after coding is complete and only in an approved disposable database.

## Read-only repeat by the database-reviewer — current continuation

The database reviewer repeated the catalog inspection for this continuation using the repository venv, `LaneEnv.load().dsn('admin')`, and a session configured with `default_transaction_read_only=on`; it explicitly began `READ ONLY` and rolled back. No query values, DSNs, credentials, tokens, or business rows were emitted. It reconfirmed database `business_ai`, PostgreSQL `16.15` (`160015`), current role `business_ai_admin`, schema `bag` present, and schema `change_ledger` absent.

`business_ai` has `SUPERUSER`, `CREATEROLE`, `CREATEDB`, `REPLICATION`, and `BYPASSRLS`; the inspected `business_ai_admin`, `business_ai_app`, and `business_ai_control_api` roles have none of those attributes and no membership edges among the four roles. Across 17 `bag` relations, `has_table_privilege` totals were: admin `SELECT 15 / INSERT 12 / UPDATE 11`, app `SELECT 14 / INSERT 1`, and control API `SELECT 17 / INSERT 12 / UPDATE 10`; all three had no `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER`. The owner had all seven privileges over all 17 relations. Across seven inspected `bag` routines, each application role had effective `EXECUTE` on five and lacked it on `invalidate_semantic_profiles_on_metadata_drift()` and `invalidate_validated_profile_on_mapping_change()`; owner had all seven. These are `bag` lane observations only. They do not measure `change_ledger`, Ivan/production rights, the future writer identity, or the physical COM transaction boundary. No migration, test, check, database write, COM call, or service action occurred.

## Follow-up S13 catalog eligibility recheck — 2026-10-23

A database reviewer performed a catalog-only check against the configured disposable lane using the repository `.venv\Scripts\python.exe`, `LaneEnv.load()`, and `env.dsn('admin')`. The credential remained in-process. The session set `default_transaction_read_only=on`, began `READ ONLY`, queried the database identity and `pg_roles`, checked `pg_auth_members` for memberships involving `business_ai%`, queried `information_schema.role_table_grants` for `change_ledger`, then rolled back. No business rows or credential-bearing values were printed.

The observed database was `business_ai` on PostgreSQL `16.15`; `change_ledger` was absent. `information_schema.role_table_grants` returned no rows for that schema. `business_ai` was LOGIN/SUPERUSER/BYPASSRLS/INHERIT; `business_ai_admin`, `business_ai_app`, and `business_ai_control_api` were LOGIN/INHERIT and not SUPERUSER/BYPASSRLS. There were no `business_ai%` membership edges among the inspected roles. Since no S13 relations or routines existed, there were no S13 object arguments for `has_table_privilege` or `has_function_privilege`; effective S13 table/function grants remain **NOT_VERIFIED**. This result is a disposable-lane eligibility check, not Ivan-host/production evidence and not a private-writer boundary measurement.

No schema change, migration, database write, test, check, COM call, service action, restart, push, or PR occurred.

## Direct control-role catalog retry — current continuation

A `database-reviewer` performed the single bounded direct-role retry requested for `business_ai_control_api`. It used the repository `.venv\Scripts\python.exe`, `LaneEnv.load().dsn('control')`, and `asyncpg.connect(timeout=5)`. A preliminary attempt to import `psycopg` failed with `ModuleNotFoundError` before any connection was made; the retry used the available `asyncpg` driver. The successful session set `default_transaction_read_only=on`, explicitly began `READ ONLY`, queried only catalog/effective-privilege data, and rolled back. DSN/password values, business rows and tokens were not emitted. No further connection attempt was made.

The session connected to `business_ai` on PostgreSQL `16.15` with both `current_user` and `session_user` equal to `business_ai_control_api`. The role has `LOGIN` and `INHERIT`; it is not `SUPERUSER`, `CREATEROLE`, `CREATEDB`, `REPLICATION`, or `BYPASSRLS`. There are no membership edges among `business_ai`, `business_ai_app`, `business_ai_admin`, and `business_ai_control_api`.

For `bag`, `has_table_privilege` found control API `SELECT` on all 17 relations, `INSERT` on 12, and `UPDATE` on 10; it found no `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER`. The exact relation lists are in the role table above. Among the seven inspected routines, effective `EXECUTE` was true for `native_reconciliation_evidence_valid(evidence jsonb)`, `record_capability_observation(...)`, `reject_admin_audit_mutation()`, `reject_audit_mutation()`, and `reject_semantic_profile_event_mutation()`; it was false for `invalidate_semantic_profiles_on_metadata_drift()` and `invalidate_validated_profile_on_mapping_change()`. Catalog `EXECUTE` on trigger functions does not establish ordinary direct-call reachability.

`change_ledger` remains absent, so no S13 relation, routine, role grant or writer transaction boundary could be measured. The outcome closes only the pending control-role connection retry and adds current `bag`/`public` disposable-lane evidence; it is not evidence about Ivan's host, production, or effective S13 rights. No migration, test, check, database write, COM call, service action, restart, push or PR occurred.
