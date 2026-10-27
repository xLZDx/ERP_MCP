# Change Record 316 — skip generated array types during ACL normalization

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and closure owner: Codex.
- Technical boundary: ERP_MCP S13 candidate migration 027 type-ACL normalization.
- Acceptance: `S13-ACL-GENERATED-ARRAY-TYPES-01`.
- State: source correction implemented; the focused five-case disposable suite is green; broader ACL and E2E coverage remains open.

## Finding and change

The functional-test reviewer ran the existing focused S13 SQL qualification using an invocation-
owned PostgreSQL disposable database. Migration setup failed before every test body when the
application-schema ACL loop attempted `REVOKE USAGE ON TYPE` for PostgreSQL's generated array type
`living._schema_migrations`. PostgreSQL rejects direct array-type ACL changes and requires
privileges to be controlled through the element type. The same loop existed for `change_ledger`.

Both catalog scans in migration 027 now filter `pg_type.typelem=0`, which keeps element/base,
composite and domain types in direct normalization while excluding generated arrays. Their
privilege behavior continues to derive from the corresponding element type. The S13 disposable
acceptance prerequisites now record this constraint and require both schema paths to install.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — global application-schema and
  `change_ledger` type ACL loops.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` —
  `S13-ACL-GENERATED-ARRAY-TYPES-01`.

## Evidence and verification

- Before fix, exact candidate SHA-256:
  `47983E7958BB2C48C978B324CD2587D7165F835CDBCC1AACBB2A2213D99E2293`.
- Reviewer command: `uv run pytest -q tests/phase2/test_s13_current_turn_sql.py`.
- Result before fix: 3 setup errors in 25.95 seconds; no test body executed. PostgreSQL SQLSTATE
  `0LP01`: `cannot set privileges of array types; Set the privileges of the element type instead`.
  Failing dynamic statements were at migration 027 lines 11541–11542 for `living._schema_migrations`
  and the analogous `change_ledger` loop.
- The harness output leaked a very large SQL diagnostic through `asyncpg.PostgresError.context`.
  The functional-test reviewer removed that context field from emitted diagnostics while retaining
  a bounded query length/hash/snippet. The test-file change is separate from production code and
  its pre-edit SHA-256 was
  `98A4519BB7C9E1E4B17AF13661EEA4CC14CCB585B3BDCAEB65C0DDF63689841B`.
- Post-fix migration SHA-256:
  `9D0B5B2A30D6FB1C6185F10D60310745BC79EC175C71D691C44FE09B0A6249FF`.
- Post-fix reviewer command: `uv run pytest -q tests/phase2/test_s13_current_turn_sql.py`.
- Post-fix result: 5 passed in 49.93 seconds on candidate migration SHA-256
  `9D0B5B2A30D6FB1C6185F10D60310745BC79EC175C71D691C44FE09B0A6249FF`; test file SHA-256
  `77F134128DC70064DE5C858DD06537AE40B2F16E28A9A023C9CD7C7A9A2AB453`. This includes both new
  array normalization and reachable-PUBLIC rollback cases. The label-verified invocation-owned
  PostgreSQL cluster cleanup completed without error.
- A separate expanded seeded pre-existing-grants/default-ACL case passed in 10.16 seconds at the
  same migration hash. Test file SHA-256 at that case was
  `19A7182BBE3945FCBE42CDC0A7923717BFB742C63643F509A832F46A0C63362D`. It covered direct database,
  schema, table, column, sequence, routine, domain-type and large-object grants; database/schema
  CREATE; allowed versus withheld function execution; and global plus `change_ledger`-local default
  ACL behavior for owner-created tables, sequences, routines and types. Broader ownership-class
  rollback cases and T16 service E2E remain open; this is not full S13 ACL/S13/COM acceptance.
- Six additional PostgreSQL 16 disposable ownership rollback cases passed in 50.26 seconds on the
  same candidate migration hash; test file SHA-256 at that run was
  `01C77D51A78BB586DB219BED1AC2C1D768A165E1C231FBCE49F49E25927E20D0`. Covered relation, sequence,
  routine, user-defined type, large object, and current-database ownership. Each returned the exact
  `PRIVATE_WRITER_ROLE_OWNS_OBJECT` refusal, rolled back candidate objects, and preserved ownership.
  Schema ownership passed separately. Extension ownership remains `NOT_RUN` pending a safe,
  portable disposable fixture; the consolidated suite has not yet been rerun.
- No configured lane/business database, production service, COM, or migration was used/applied.
  No staging, commit, or push occurred.

## Ordered next steps

1. Functional-test-reviewer: assess a portable extension-ownership fixture, then run the full
   consolidated focused suite and report exact-hash results/unrun classes.
2. E2E runner: own the service-driven T16 operator-resolution/checkpoint
   replay journey in the prerequisites, using test doubles for unavailable COM and reporting that
   limitation.
3. Database-reviewer: after functional/E2E completion, inspect exact final migration bytes and
   independently review ACL semantics; then qualify effective grants only in an approved
   invocation-owned disposable database.
4. Operator-accountable / Codex-executor: retain the separate blockers for a licensed COM writer,
   approved clone field crosswalk, and installed effective-grant evidence; do not grant or enable
   candidate routes from source-only evidence.
