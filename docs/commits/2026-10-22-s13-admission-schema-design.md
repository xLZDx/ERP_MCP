# Change record: define S13 durable admission schema direction

Date: 2026-10-22  
Scope: PostgreSQL durable dispatch-attempt and recovery-barrier design; documentation only.

## What changed

- Added an implementation design for recording S12's existing dispatch CAS as a durable attempt, with process binding and one-way invocation state.
- Defined the separation between the single S12 authorization transition and durable physical-call progress; rejected a separate admission authorization claim.
- Defined scope epoch/barrier tables as a proposal that keeps the existing lifecycle epoch authoritative and captures the complete pre-barrier call set.
- Recorded transaction, lock, failure, migration, qualification, and ownership constraints.
- Linked the proposal from the current S13 acceptance map without changing its formal gate state.

## Why

`PrivateWriterService` already depends on an `AdmissionStore` protocol, but no durable adapter exists. The design must give the private service restart-safe idempotency without competing with S12's existing `PERMITTED → DISPATCHED` CAS.

## Evidence and limits

- Existing CAS source: `db/phase2/012_dispatch_session_hardening.sql:136-165`; prior definition and permit state are in `db/phase2/004_change_ledger.sql:774-812`.
- Frozen call identity and attempt requirements: `docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md:139-147`.
- Writer service adapter interface: `src/erp_mcp_private_writer/service.py:130-158`; this change does not implement it.
- Lock-order proposal: `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`.
- Acceptance-state reconciliation: `docs/phase2/S13_ACCEPTANCE_MAP_AND_MIGRATION_INVENTORY.md` still records `NOT_STARTED / NOT_APPROVED`; this proposal does not advance that gate.
- This is a design proposal only. No code, tests, checks, build, CI, migration, database write, COM call, or service action was performed for this artifact.

## Ownership and next step

- Accountable owner: operator; executor: Codex.
- Next: reconcile the design against the exact S12 schema and effective grant map with database, reliability, and security reviewers; then seek exact GPT-PM review before additive migration work. Keep all write routes disabled until disposable qualification.
