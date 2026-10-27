# Change record 245 — protect private-writer lifecycle and lock bindings

Date: 2026-10-25  
Scope: source-only S13 coordinator hardening; no service, database, or COM runtime was exercised.

## What changed

- `PrivateWriterService` now freezes the base-dispatch lock, terminal-mutation lock, and pending T16 resolution-map reference after construction.
- The class-level operation-to-writer-method routing table is now a read-only mapping, preventing item mutation from redirecting a closed operation to another writer method.
- Ordinary assignment/deletion of startup readiness, serving epoch, startup-recovery snapshot, and active-quiescence task state is rejected. The internal lifecycle setter accepts only exact bool readiness, positive integer-or-`None` epochs, the expected recovery-state type, and a nonzero barrier UUID paired with an `asyncio.Task`.
- Same-value lifecycle updates are idempotent; internal startup, reset, and quiescence sites use the setter. The fail-stop `_restart_required` latch retains its separate serialized setter.
- Readiness can become true only when the validated startup snapshot and matching positive service epoch are present, with a readiness reference, no pending calls or open barriers, and no restart latch. A quiescence task cannot be cleared before it is done.
- The `S13-SERVICE-CONFIG-IMMUTABILITY-01` prerequisite now tests lifecycle mutation refusal and valid startup/quiesce transitions while preserving zero collaborator calls on rejected mutation.
- Current source SHA-256: `FA33E1B12C48428F8643852EC437D8B483E073B559B86A03030EA189163FC4AD`.

## Why

Replacing `_base_dispatch_lock` or `_terminal_mutation_lock` could split synchronization from existing operations. Directly assigning `_startup_complete` or `_service_epoch` could bypass startup recovery, and replacing `_active_quiesce` could break the retained barrier-task ownership used to prevent early release. These fields need ordinary caller mutation blocked while validated internal transitions remain available.

## Scope and verification state

- This source change does not establish authenticated host/build provenance, effective database grants, COM payload mapping, a live listener, or runtime transaction semantics. It does not defend against deliberately malicious same-process use of `object.__setattr__` or mutation of a private dict through introspection.
- Static source inspection only; no tests/checks/build/CI, SQL parsing, migration, database operation, COM call, listener start, stage, commit, or push ran. `S13-SERVICE-CONFIG-IMMUTABILITY-01` remains `NOT_RUN`.

## Ownership and next action

- Accountable task owner: operator; executor: Codex.
- Later scenario owners: `functional-test-reviewer` and `e2e-runner`; relevant source review: Python/reliability/security reviewers after coding closure.
- Next: continue source closure. After code is complete, qualify internal lifecycle transitions, direct mutation refusal, barrier-task retention, and error cleanup before considering any service enablement.
