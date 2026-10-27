# Change Record 354 — migration 027 applied in a disposable database; privileges measured

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session; measurement run by the functional-test-reviewer agent at HEAD 735c904.
- Documentation only. No source or SQL changed.

## Method

Disposable cluster and throwaway database from `tests/phase2/_pg_harness.py` (gate variable `ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1`), migrations 001-026 applied as `test_s13_checkpoint_suffix_functional.py` does, then `db/phase2/027_private_writer_admission_schema.sql`. Privileges read with `has_function_privilege`, `has_table_privilege`, `has_schema_privilege`, `pg_roles` and `pg_default_acl`. Containers created by the run were removed; other containers were not touched.

## Result (MEASURED, single fresh chain)

- 027 applies without error and applies a second time without error. Neither role existed before 027.
- Both roles: LOGIN, NOINHERIT, not superuser, bypassrls, createrole, createdb or replication; no role memberships in either direction; no database CREATE; schema `change_ledger` USAGE yes, CREATE no.
- `business_ai_private_writer`: EXECUTE on 13 SECURITY DEFINER `private_writer_*_v1` functions (lookup, lookup_barrier, startup_recovery_state, admit, mark_invoking, begin_com_entry, record_terminal, attach_recovered_receipt, record_verified_success, record_recovered_not_invoked, record_recovered_terminal, close_and_advance, finish_barrier) out of 295 functions in the schema; no privilege on any of the 63 relations or sequences; USAGE on 6 composite types.
- `private_writer_evidence_ingest`: no function EXECUTE, no relation privilege, USAGE on one type (`private_writer_barrier_ack_v1`).
- PUBLIC: no function EXECUTE, relation privilege or type USAGE in `change_ledger`. `pg_default_acl` has three rows and none grants to either role or PUBLIC.
- Both roles keep PostgreSQL default USAGE on schema `public` (CREATE is false); 027 does not revoke it.
- No grant broader than needed was found.

## Not covered

Behavior of the writer functions, tenant scoping inside the SECURITY DEFINER bodies, credential setup (roles are created with LOGIN and no password), an upgraded (non-fresh) database, whether the second apply leaves the privilege state unchanged. The writer stays UNQUALIFIED. Stale `r2-s13-dump-*` containers on this machine predate the run and were not touched.
