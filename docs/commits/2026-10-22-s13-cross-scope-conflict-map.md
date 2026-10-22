# Change record: map S13 cross-scope unique conflicts

Date: 2026-10-22  
Scope: S13 database-fence source design; documentation only.

## What changed

- Extended the selected scope-fence and private-writer designs with the source-audited cross-scope unique-conflict domains.
- Recorded caller-controlled global `change_id` as a per-key lock domain, including dependent keys and sweep counters/failures that reuse it.
- Recorded optional caller-controlled `grant_id` in `budget_admin` as a separate global per-key lock domain.
- Distinguished scoped unique keys, generated surrogate UUIDs, and the new writer schema's unresolved call-ID uniqueness contract.

## Why

A per-scope shared/exclusive fence prevents recovery from overlapping participating changes in that scope, but it does not order transactions in different scopes that contend on a globally unique caller-supplied identifier. Treating it as complete would leave the original `records.change_id` primary key and caller-selected grant IDs outside the recovery lock-order proof.

## Source evidence

- `db/phase2/004_change_ledger.sql`: `records.change_id` is the primary key at lines 213–215; `propose` accepts a caller-supplied ID at 495–499 and inserts it at 530–534. Its logical idempotency index includes tenant/company at 253–255.
- `db/phase2/008_change_hardening_b.sql`: final `propose` retains the caller-supplied ID at 220–221 and insert at 266–270; later `records_scope_change_uniq` adds a composite unique key but does not drop the global primary key at 1862–1867.
- Dependent global keys reference that record identity: reservations (`004`, 360–371), claim tokens and dispatch permits (`004`, 309–331), change budget (`008`, 52–53), business keys and override bindings (`005`, 80–129), call deadlines and sweep counters (`006`, 37–66), evidence and receipts (`005`, 80–93; `016`, 51–71), and sweep-failure rows (`008`, 830–835).
- `budget_admin` accepts an optional `p_grant_id`, locks/updates an existing grant, or inserts that ID (`008`, 608–635); the grants table uses a global primary key (`004`, 351–359).
- `call_id` is supplied to dispatch permits (`004`, 777–809; final form `009`, 637–681), but source migrations 004–026 do not declare a unique constraint on it. The new writer-admission schema must choose and enforce its uniqueness domain.

## Review and verification state

- Read-only database-reviewer source audit recommended sorted namespaced per-key locks after the scope fence and before any row/conflict lock, at minimum for caller-controlled `change_id` and `grant_id`; it found no source basis for a global singleton mutex. The audit also confirmed that generated surrogate UUIDs do not justify global serialization and that scoped composite keys remain covered only when every path enters the fence.
- Role: `database-reviewer`; model: role default GPT-6 Luna; reasoning effort: not exposed in returned agent metadata.
- The exact scope/key serialization and full participation list remain design work; this record is not migration approval or proof of deployed indexes, grants, or runtime wait graphs.
- GPT-PM exact-patch review (request `2c6efee4-dfb0-42d2-94ee-a64eea713a88`, patch SHA-256 `8D5742F4821B0447F6B0E48021FA91D647BEF776E1638AE791A4A2FB135935BB`): APPROVE for one local documentation commit; 0 BLOCKER, 0 MAJOR, 1 MINOR. Finding: phrase “dependent unique keys” overstated which cited structures are demonstrated as unique constraints; the scope-fence design now says dependent conflict/key domains “carry or reference” `change_id`. This revised patch awaits exact-hash GPT-PM review.
- No tests, checks, builds, CI, migrations, database writes, COM calls, or service actions were run for this documentation change.

## Ownership and next step

- Accountable owner: operator; executor: Codex.
- Next: specify canonical fence and per-key serialization plus timeout/refusal mapping, then reconcile all callers, helpers, triggers and conflict paths against it before additive SQL work. Keep recovery refused and lifecycle `NOT_READY` until reviewed and qualified.
