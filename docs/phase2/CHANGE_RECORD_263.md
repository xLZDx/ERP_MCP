# Change Record 263 — preallocate kill-switch recovery run ID

## What changed

- In candidate migration 027, `kill_switch_v1` now allocates its recovery `run_id` after input and
  entitlement validation but before acquiring the exclusive namespace-2 kill-switch fence.
- The deferred recovery helper receives that exact ID. Its existing source adds the ID to the
  namespace-6 global fence set before recovery row locks.
- Updated the S13 lock/grant inventory with the source finding, correction, and qualification limit.

## Why

The prior source allocated a sweep-run ID only after taking the exclusive switch lock. The accepted
rank contract and existing `S13-FENCE-ENTRY-14-01` prerequisite require generated global IDs to be
allocated before the first ranked lock; the ID must then be fenced before recovery row locks. Moving
the allocation closes that source-order mismatch without changing the recovery transaction or
event behavior.

## Evidence and limits

- Candidate source: `db/phase2/027_private_writer_admission_schema.sql:7439-7444`.
- Helper ID fencing: `db/phase2/027_private_writer_admission_schema.sql:9154-9195`.
- Existing qualification criterion: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:100`.
- Candidate migration SHA-256 after this change:
  `5F1120750E2BBD82C7A8EFB22A5E6C2AFE62552FE415451D63AEE798E2B9B8DD`.

No SQL parser, tests, checks, build, CI, migration, database write, COM call, staging, commit, or
push was run. Source ordering is inspected but not independently reviewed or runtime-proven;
qualification remains `NOT_RUN`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. After coding closes, the database-reviewer owns
the relevant source and installed-grant review; functional-test-reviewer owns the direct SQL case,
and e2e-runner owns the service-driven kill-switch recovery journey. Next: continue the all-path
S13 source closure, then parse and qualify the exact candidate only in the authorized disposable
database.
