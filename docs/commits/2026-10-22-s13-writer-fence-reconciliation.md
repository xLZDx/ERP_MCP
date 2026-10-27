# Change record: reconcile the private writer fence design

Date: 2026-10-22  
Scope: S13 private writer service and database-fence documentation; documentation only.

## What changed

- Reconciled `S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` with the selected per-scope protocol: ordinary scoped mutations take a shared transaction fence; recovery and barrier transitions take its exclusive counterpart; both require a canonical internal lock order.
- Explicitly superseded the earlier global singleton-mutex/`MUTATION_BUSY` candidate so it is not mistaken for the active direction.
- Updated admission ordering: only non-locking identity validation may precede fence-key derivation; authoritative scope, lifecycle, epoch, and admission checks run while the shared fence is held.
- Kept cross-scope unique-index conflict domains, complete source-path coverage, bounded refusal semantics, and physical COM quiescence as unresolved implementation and qualification requirements.
- Replaced the ambiguous phrase “full global lock order” with “complete source-wide lock order.”

## Why

The active scope-fence design selected after the correlated PM Bridge review uses compatible shared/exclusive per-scope fencing with canonical internal ordering. The private writer design still described a global serial mutex as its candidate implementation. Leaving both directions active would misdirect S13 code and tests. The new wording records the current design choice while preserving the unresolved source-wide proof and explicitly withholding migration approval.

## Contracts and limits

- This is a design reconciliation, not SQL implementation, migration approval, runtime qualification, S13 acceptance, `READY`, or deployment authorization.
- The per-scope fence alone does not order concurrent mutators or cross-scope unique-index conflicts; the full conflict domain and lock graph still require review.
- Effective S13 grants remain `NOT_VERIFIED` because the inspected disposable database has no `change_ledger` schema.
- Recovery remains refused and lifecycle remains `NOT_READY`; COM remains outside PostgreSQL transactions and requires its own stale-epoch, lookup, idempotency, and quiescence proof.

## Review and verification state

- Read-only `database-reviewer` review found no BLOCKER or MAJOR. One MINOR requested replacing “full global lock order” with “complete source-wide lock order”; this change closes that finding. Role: `database-reviewer`; model: role default GPT-6 Luna; reasoning effort: not exposed in returned agent metadata.
- The selected direction is linked to PM Bridge design review request `875580c2-0610-452c-bf74-678f455bf59e` and reply `cecff738-6524-4a08-8636-7c48575aaef5`. This is design guidance, not approval of a migration.
- No tests, checks, builds, CI, migrations, database writes, COM calls, or service actions were run for this documentation change.

## Ownership and next step

- Accountable owner: operator; executor: Codex.
- Ivan stack is the technical owner of the host/connection boundary; database/reliability reviewers own the later source-order review.
- Next: define the precise fence key derivation, timeout-to-refusal mapping, and every cross-scope unique-conflict ordering case before proposing an additive migration. Do not remove the refusal or `NOT_READY` state before exact-path evidence exists.
