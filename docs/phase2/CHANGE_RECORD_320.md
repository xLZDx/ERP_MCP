# Change record 320 — disposable PostgreSQL effective-grant snapshot

## Ownership and scope

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Evidence executor: Codex; query execution: database-reviewer role.
- Scope: fresh, invocation-owned disposable PostgreSQL 16.14 only. No configured lane, local persistent database, COM, or 1C data was used.
- This records a partial grant measurement, not S13 acceptance or authorization to install the candidate.

## Exact candidate and disposable environment

- Candidate: `db/phase2/027_private_writer_admission_schema.sql`.
- SHA-256 before and after: `F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F`.
- Fresh fixture applied migrations 001–026 followed by candidate 027. PostgreSQL reported version 16.14 and system identifier `7701040933950963751`.
- First bounded run: generated container `r2-s13-dump-4c9063c7ca4b-a`, disposable database `g1x_e8008688`; its catalog query produced the table/column/sequence and routine/type counts below, then its report query hit a syntax error before function/type privilege predicates.
- One targeted follow-up used a new invocation-owned container `r2-s13-dump-ab84c6fee279-a`, database `g1x_c8add701`. The generated ownership label matched before migration. Cleanup was checked afterward: the database and exact container name were both absent. No DSN, token, or secret was emitted. No repository or configured-lane state changed.

## Visible measured privileges

The targeted role set was `requester_role`, `approver_role`, `operator_role`, `writer_role`, `worker_role`, `auditor_role`, `checkpoint_role`, `business_ai_private_writer`, `private_writer_evidence_ingest`, and `ledger_owner`.

- All ten roles had database `CONNECT=true`, `CREATE=false`, `TEMP=true`.
- In `change_ledger`, all ten had `USAGE=true`; only `ledger_owner` had `CREATE=true`.
- In `living`, all ten had `USAGE=false` and `CREATE=false`.
- In `public`, all ten had `USAGE=true`, `CREATE=false`.
- No membership edges were returned for the selected roles. The two private service roles were login, `NOINHERIT`, and had none of superuser, `BYPASSRLS`, replication, database-creator, or role-creator attributes. `ledger_owner` was non-login and `NOINHERIT`.
- `role_table_grants` and `role_column_grants` showed no direct table or column grants to `business_ai_private_writer` or `private_writer_evidence_ingest`. Legacy actor roles had the candidate's expected SELECT grants; `ledger_owner` held full ownership rights on its objects.
- Sequence grants were limited to `ledger_owner` with `USAGE` on two sequences. There were no private-service sequence grants.
- Aggregate effective predicates for the selected runtime roles reported tables 73/3843, columns 716/22500, sequences 0/54. These totals include legacy roles and must not be interpreted as private-service grants.
- `role_routine_grants` showed 13 routine EXECUTE grants for `business_ai_private_writer` and no EXECUTE grant for `private_writer_evidence_ingest`. In the targeted query, visible `has_function_privilege(role, routine_oid, 'EXECUTE')=true` rows included 13 private-writer routines, 15 auditor routines, and 9 checkpoint routines. The full role/routine matrix was combined into an output that was truncated after `requester_role`; other booleans and the false-row list are `NOT_RECOVERABLE` and are not inferred.
- Visible `has_type_privilege(..., 'USAGE')=true` rows included six private-writer types, two evidence-ingest types, one requester type, two worker types, and one writer type. Corresponding generated array types also appeared. PUBLIC-derived usage was visible for 12 types in `living`, but the target roles lacked `living` schema USAGE. The exact complete type predicate matrix is `NOT_RECOVERABLE` from the truncated output.

## Acceptance and remaining work

This is runtime evidence for candidate 027 in a fresh disposable cluster only. It does not establish installed lane grants, prove the complete effective routine/type predicate matrix, validate real 1C rights, or establish the physical writer's transaction boundary. Candidate 027 remains uninstalled and the private-service functions remain ungranted in configured environments (`NOT_VERIFIED`).

The database-reviewer also reports that an earlier report query failed from a query-syntax defect after migration application; this was not a migration failure. A later targeted query captured visible rows but the combined output truncation prevents recovering every role/routine/type boolean. No further cluster was started in this pass. Codex owns deciding whether the still-missing matrix is required for the next disposable qualification; if required, the next step is a narrowly projected, per-role result with bounded output. Иван stack remains the technical owner of the remote host boundary; a licensed COM session and reviewed `818HA_p2diff` destination/type mapping are still absent, so the physical 1C writer boundary remains unimplemented.

## Targeted five-role predicate follow-up — superseding detail

One final fresh, owned PostgreSQL 16.14 disposable cluster was used to avoid truncation. Exact
candidate SHA remained unchanged; the generated label matched before migration, and both the
throwaway database and exact container name were absent after cleanup. No configured database or
repository file was touched.

Visible true `has_function_privilege(role, routine_oid, 'EXECUTE')` results:

- `business_ai_private_writer` — 13 exact versioned functions: `private_writer_admit_v1`,
  `private_writer_attach_recovered_receipt_v1`, `private_writer_begin_com_entry_v1`,
  `private_writer_close_and_advance_v1`, `private_writer_finish_barrier_v1`,
  `private_writer_lookup_barrier_v1`, `private_writer_lookup_v1`,
  `private_writer_mark_invoking_v1`, `private_writer_record_recovered_not_invoked_v1`,
  `private_writer_record_recovered_terminal_v1`, `private_writer_record_terminal_v1`,
  `private_writer_record_verified_success_v1`, `private_writer_startup_recovery_state_v1`.
- `private_writer_evidence_ingest` — **0** executable routines.
- `checkpoint_role` — 9 routines: `attach_permit_signature`, `caller_role`,
  `canonical_content_hash`, `checkpoint_payload`, `keyed_signature`, `ledger_head`,
  `record_checkpoint`, `row_in_scope`, `set_scope`.
- `writer_role` — 17 routines: `caller_role`, `canonical_content_hash`,
  `change_ledger_begin_apply_v1`, `checkpoint_payload`, `declare_anchor_gap`,
  `keyed_signature`, `ledger_head`, `observe_target`, `private_writer_dispatch_intent_for_call_v1`,
  `record_dispatch_receipt`, `record_evidence`, `renew_writer_lease`, `requested_by_caller`,
  `require_dispatch_receipt`, `row_in_scope`, `set_scope`, `verify_dispatch_payload`.
- `worker_role` — 24 routines: `amount_consumed`, `caller_role`, `cancel_permit`,
  `canonical_content_hash`, `check_anchor`, `checkpoint_payload`, `declare_anchor_gap`,
  `declare_unclean_restart`, `keyed_signature`, `ledger_head`, `lifecycle_checkpoint_suffix`,
  `lifecycle_permit_epoch`, `lifecycle_status`, `private_writer_dispatch_intent_for_call_v1`,
  `private_writer_issue_permit_v1`, `private_writer_permit_binding_for_intent_v1`,
  `record_evidence`, `release_claim`, `requested_by_caller`, `revoke_change`, `row_in_scope`,
  `set_scope`, `verify_chain`, `verify_inconclusive_v1`.
- `add_epoch_dependency_v1` was absent from the true rows for these roles, consistent with the
  intended withheld grant. This is not a complete false-row matrix.

Visible `has_type_privilege(role, type_oid, 'USAGE')` rows included 12 `change_ledger` types for
`business_ai_private_writer`, 4 for `private_writer_evidence_ingest`, 2 for `worker_role`, and 1 for
`writer_role`, plus each generated array type. `checkpoint_role` had no `change_ledger` type usage
rows. All five roles also had `USAGE=true` on 12 `living` composite row types and their arrays,
but `living` schema `USAGE=false`, so that schema does not expose those types to these roles.

For these five roles, database predicates were `CONNECT=true`, `CREATE=false`, `TEMP=true`; schema
predicates were `change_ledger USAGE=true/CREATE=false`, `living USAGE=false/CREATE=false`, and
`public USAGE=true/CREATE=false`. The attempt to query database ACL attribution returned no row
because its predicate used `privilege_type='TEMP'`; PostgreSQL spells the ACL value `TEMPORARY`.
Thus effective TEMP is measured but its source is `NOT_COLLECTED`. No global TEMP revoke or other
ACL change was attempted. These are candidate-cluster results only; installed lane privileges stay
`NOT_VERIFIED`.

A final attempt to recover only the `TEMPORARY` ACL attribution returned a tool truncation message
without its nested execution identifier, generated container name, query rows, or cleanup result.
No claim is made about that invocation's output or cleanup. It was not repeated and no broad Docker
inspection or cleanup was attempted because the invocation identity was unavailable. Codex owns a
future bounded retry only if needed; preserve the nested execution ID and emit one short, per-role
row at a time. Do not change `PUBLIC` or database ACLs based on the missing attribution.

## Recovered TEMPORARY attribution — superseding that gap

A subsequent bounded database-reviewer invocation captured the exact ACL rows and verified
cleanup. On PostgreSQL 16.14 with candidate SHA unchanged, container
`r2-s13-dump-b2843ce7a9be-a` and database `g1x_604c92c8` were confirmed absent after their harness
contexts. For `business_ai_private_writer`, `private_writer_evidence_ingest`, `checkpoint_role`,
`writer_role`, and `worker_role`, effective `TEMP=true`, direct role `TEMPORARY=false`, and
`PUBLIC TEMPORARY=true`. `PUBLIC` itself had direct/effective `TEMPORARY=true`. Therefore these
five roles inherit the measured temporary-object capability from PUBLIC. No ACL was changed.

The prior tool-truncated attempt still has no recovered invocation identifier or cleanup result;
this successful run is a separate clean fixture and does not prove that earlier invocation's
cleanup. Any cleanup reconciliation for that unidentified invocation must use a scoped, read-only
inventory first and only perform cleanup when exact ownership can be established.

## Bounded harness-container inventory

This turn ran the read-only `docker ps -a --filter "name=r2-s13-dump-"` inventory. It returned seven
matching containers, all `Exited` 9–11 days ago; none of the exact container names from the
current-turn grant fixtures was present, and no matching container was running. No container was
removed. These older exited containers are pre-existing and their ownership was not established.
This bounded inventory rules out a currently running container with the S13 dump-harness name
prefix, but it cannot establish whether an unidentifiable historical invocation committed a
throwaway database before its container exited. No remote service or configured database was
accessed by this inventory.

## TEMPORARY privilege disposition

The database-reviewer searched in-scope `db/`, `src/`, and `tests/` for `CREATE TEMP`,
`CREATE TEMPORARY`, `TEMP TABLE`, `CREATE TABLE pg_temp`, and `INTO pg_temp`; no temporary-table
creation/use was found. The `pg_temp` matches are security-definer search-path clauses. Candidate
027 lines 96–106 revokes and verifies database `CREATE`, but does not revoke `TEMPORARY`.

Disposition: **leave the PUBLIC ACL unchanged**. The repository does not prove that the target
database is dedicated or inventory external callers, and `PUBLIC` applies to all database roles;
revoking it could break callers outside this repository. Removing a direct TEMP grant from only the
five roles would not override the inherited PUBLIC privilege. Treat the measured capability as an
inherited compatibility privilege. Revisit only after proving database dedication or inventorying
affected roles and planning explicit regrants. This audit did not change the candidate migration or
any ACL.
