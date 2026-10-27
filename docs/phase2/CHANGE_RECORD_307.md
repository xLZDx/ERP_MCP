# Change Record 307 — normalize private-writer ACLs across the candidate schema

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and closure owner: Codex.
- Technical boundary: ERP_MCP S13 PostgreSQL candidate migration 027.
- Acceptance: `S13-ACL-SOURCE-ROLE-MAP-01`.
- State: the previously reviewed candidate hash is not the current file hash. The current candidate bytes are not source-reviewed yet; no parser, test, migration, or database write was run after the current edits, and runtime qualification remains open.

## Change and reason

A database-reviewer source audit found that migration 027 validated an already-existing private writer or evidence-ingest login role's attributes and memberships but revoked object access only for a fixed list of new S13 tables. Such a role could conditionally retain direct grants on older relations, sequences, routines, or schemas. This was a possible grant path, not evidence that those grants existed in the configured database.

The candidate now rejects replication-capable existing roles and fails closed if either private role owns the current database or any in-database schema, relation, routine, type, extension, or large object. It revokes database `CREATE` from both roles and checks the effective privilege, normalizes global and `change_ledger`-local `ledger_owner` defaults for tables, sequences, routines and types, and revokes their direct table/column, sequence, routine, type, and schema `CREATE` grants across non-system schemas. It revokes their direct large-object ACLs. In `change_ledger`, it revokes `PUBLIC` and both private roles before restoring only the explicit S13 function allowlist. The post-revoke predicate refuses any remaining reachable application-schema DDL/data/routine rights or PUBLIC/private-role large-object data rights or reachable unapproved type USAGE.

The independent reviewer noted a potential false positive: `living.record_migration` has PostgreSQL's default PUBLIC EXECUTE ACL. Migration 003 revokes `USAGE` on schema `living` from PUBLIC and does not grant it to the new private roles. The effective-reachability predicate therefore now requires schema `USAGE` before treating table/column, sequence, or routine ACLs as usable. This preserves fail-closed checks for objects the roles can actually name without broadening the migration to revoke unrelated public API grants.

## Affected contracts and paths

- `db/phase2/027_private_writer_admission_schema.sql` — candidate role-attribute, ownership, database/schema/object/large-object ACL normalization and effective-privilege checks.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` — seeded pre-existing role acceptance under `S13-ACL-SOURCE-ROLE-MAP-01`.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md` and `docs/phase2/artifacts/WP0_WP2_CURRENT_TURN_RECHECK_2026-10-26.md` — current source identity, review history, and runtime limitation.

## Evidence and limitations

- A read-only reviewer query through the repository lane environment found database `business_ai` (configured port 18432, PostgreSQL server port 5432) with no `change_ledger` schema. The reviewer did not inspect grant catalogs, apply a migration, or print a DSN/secret. Effective S13 grants remain `NOT_MEASURABLE` there.
- Source re-reviews confirmed the ownership catalog set, database CREATE revocation/check, replication-attribute rejection, and direct-grant/large-object normalization on the hashes listed below. Review evidence is hash-specific; it does not automatically carry forward to later bytes.
- Candidate migration SHA-256: `76A191BE062AF74CB3556D674D38CC366D4E82EAF5775A84BC1F721A21384D40`.
- Earlier focused disposable SQL evidence applies only to the earlier migration hash `D5F22EAF09DA1B2A0ED4CC6D29F70860EF6D55459FF2EA1F381B932FA4C46525`; it is stale for this ACL candidate. No result is claimed for the current hash.
- Tests, SQL parsing, migration application, effective-grant measurement after installation, COM, staging, commit, and push: `NOT_RUN` for the current source.

## Ordered next steps

1. Codex: close remaining in-scope S13/S14 source code; after code closure, obtain an exact-hash ACL source review for the current candidate before functional qualification.
2. Codex: complete remaining in-scope S13 coding; the operational COM `OneCWritePort` and reviewed clone destination crosswalk are still absent.
3. After coding closes, functional-test-reviewer and e2e-runner: add and run the seeded-role ACL and mapped S13 scenarios on invocation-owned disposable databases.
4. Database-reviewer: measure effective roles, object grants, schema/database privileges, type and large-object ACLs, exact function execution, and type USAGE on an approved disposable database after candidate installation.
- Final source-only DB review of exact SHA `76A191BE062AF74CB3556D674D38CC366D4E82EAF5775A84BC1F721A21384D40` found no syntax issue or bypass in the stated effective-reachability contract. The `USAGE` gates correctly distinguish object ACLs from objects a role can name; table-level `REVOKE` plus `has_any_column_privilege` detects column-only residue. The reviewer confirmed PG16 routine and large-object predicates are structurally coherent. The predicate intentionally fails closed if a PUBLIC-executable routine remains in an application schema the private role can use; it does not revoke unrelated public API grants. `CONNECT`, session-local `TEMP`, and schema/type `USAGE` are outside the reviewed persistent-DML boundary. Review only; no test/parser/database action.

**2026-10-26 schema-local default-ACL closure:** a source recheck found PostgreSQL schema-specific default privileges are additive to global defaults. Candidate 027 therefore now revokes PUBLIC and both private service roles from `ledger_owner` defaults for tables, sequences and routines both globally and in `change_ledger`. The disposable acceptance criterion now explicitly requires verification of both layers. Current candidate SHA-256 `DD7A1F1F63F0ED0935D685051885DF24E43F3C6B1A1D0E5ED62F55402B2F2EF2`; exact current-hash source review is pending. No parser, tests, migration, DB operation, COM, stage, commit or push ran after this edit.

**2026-10-26 user-defined-type ACL hardening:** the source audit found a non-blocking least-privilege gap for future types: PostgreSQL grants default USAGE on newly created user-defined types to PUBLIC, and existing type grants were not included in migration 027's current-object predicate. Candidate 027 now normalizes global and `change_ledger`-local `ledger_owner` type defaults, revokes direct type USAGE from the two private roles across non-system schemas, revokes PUBLIC/private-role type USAGE on current `change_ledger` types before the explicit per-type allowlist, and checks reachable type USAGE. The disposable acceptance now seeds type grants and checks type defaults/effective privilege. Current candidate SHA-256 `F83FD11BB1BC3E3B83876FC25128E0BA10AACCDD2C2102681A44B4DA51B8FA33`; exact-delta source review found no actionable issue. This is least-privilege hardening, not an established write-bypass. No parser, tests, migration, DB, COM, stage, commit or push ran after this edit.

- Final exact-delta source review of SHA-256 `F83FD11BB1BC3E3B83876FC25128E0BA10AACCDD2C2102681A44B4DA51B8FA33` found no actionable issue. The reviewer confirmed global and schema-local default `USAGE ON TYPES` revokes, safely quoted per-type direct revocation (including generated row/array types), the schema-`USAGE`-gated `has_type_privilege` assertion, and later explicit type grants for writer/evidence roles. This closes a least-privilege/default-ACL gap, not a demonstrated persistent writer-access bypass. Applying the change still requires adequate migration grant/owner authority and fails transactionally if unavailable. No SQL parse, tests, migration, or database query/write ran.

**2026-10-26 current-turn source identity reconciliation:** the current on-disk candidate `db/phase2/027_private_writer_admission_schema.sql` hashes to SHA-256 `47983E7958BB2C48C978B324CD2587D7165F835CDBCC1AACBB2A2213D99E2293`. The latest ACL-specific exact-delta source review above applies only to `F83FD11BB1BC3E3B83876FC25128E0BA10AACCDD2C2102681A44B4DA51B8FA33`; it is not evidence for the present bytes. The current hash is recorded in Change Record 311's NaN-budget review context, which did not review the ACL delta. Therefore current-hash ACL review is `NOT_RUN`. The current file still contains the later-reported ACL sections, but matching content has not been established by a byte-level diff against the reviewed hash. No parser, test, check, database operation, migration, stage, commit, or push was run for this reconciliation. Next: continue source coding, then request a focused source-only review of the final candidate hash before disposable qualification.
