# Change Record 190 — Recheck requester independence when consuming T16/T17 cosign

## What changed

Both candidate terminal paths now reject a stored approval whose approver maps to the same person
as the change requester: T16 checks inline in `operator_resolve_v1`, and T17 checks in the shared
`consume_two_person_cosign` helper. The shared helper retains the operator/requester,
witness/requester, operator/witness, and witness/approver independence checks. It is explicitly
owned by `ledger_owner` and revoked from `PUBLIC` and every named application/private role, so
callers must reach it through a protected terminal entry point.

## Why

The approval-writing path already checks approver independence, but terminal recovery must not
rely only on that earlier path. Both terminal implementations need the guard: the T16 function has
an inline cosign path, while T17 uses the shared helper. Rechecking the approver/requester
relationship at consumption makes legacy or otherwise inconsistent approval rows fail closed,
including aliases joined by the candidate person registry. PostgreSQL grants new functions
`EXECUTE` to `PUBLIC` unless explicitly revoked; leaving the T17 `SECURITY DEFINER` helper
callable directly would allow cosign-consumption outside the parent terminal transition.

## Affected contract and paths

- `db/phase2/027_private_writer_admission_schema.sql`,
  `change_ledger.consume_two_person_cosign`.
- T16 consumer: `operator_resolve_v1` inline signer check. T17 consumer:
  `operator_close_failed_verify_v1` through `consume_two_person_cosign`.
- The operator may still be the approver when the recovery witness is a distinct person; the
  witness may not be the requester or approver, and the approver may not be the requester.
- No application grant, caller route, migration selection, or runtime writer behavior changed.
- Candidate 027 SHA-256 after this source update: `C3CA1A6FF9E6A2A7F56B717456F8A7F35B782FB6A34387C62A779660DC1099DA`.

## Verification state

Manual source/ACL inspection only. No SQL parser, test/check, database operation, migration, COM call,
staging, commit, or push was run. Candidate 027 remains unparsed, uninstalled, and ungranted;
runtime acceptance remains `NOT_RUN` and effective privileges remain `NOT_VERIFIED`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue source-only trigger/FK/effect and
caller/grant closure; after code is complete, assign the relevant cases to the database-reviewer,
functional-test-reviewer, and e2e-runner roles before any disposable qualification or cutover.
