# S13 evidence and quiescence barrier lock-order correction

## Change

In additive candidate routines in `db/phase2/027_private_writer_admission_schema.sql`:

- Kept the accepted S13 order: namespace 8 when applicable, namespace 7, the early lifecycle-row exception, verifier-material identities, namespace 6, then remaining relation-row work.
- Reconciled `private_writer_register_evidence_v1`, `private_writer_register_barrier_ack_v1`, `private_writer_close_and_advance_v1`, and `private_writer_finish_barrier_v1` to that order.
- Retained `close_and_advance` base-fence snapshot revalidation after its complete call-ID plan is frozen.
- Updated the disposable qualification prerequisite to specify the new order and its revalidation requirements.

## Why

These routines' candidate ordering had diverged from the accepted S13 contract, which explicitly makes lifecycle the single early relation-row exception after namespace 7. Reconciliation keeps the common advisory order and puts remaining relation rows after the complete ranked identity set. Runtime behavior still requires the mapped disposable races.

## Scope and compatibility

- Changes are limited to additive migration-027 routines and S13 qualification documentation.
- Existing legacy routines, default adapter routing, grants, schema installation, production state, and physical COM behavior are unchanged.
- Candidate functions remain ungranted and the adapter flag remains off.

## Verification state

- Manual source inspection only; no SQL parse, tests, checks, build, CI, migration, database query/write, or COM call ran.
- Evidence/revocation and barrier ID/snapshot/finalization races remain `NOT_RUN`.
- Effective grants remain `NOT_VERIFIED`.

## Ownership and next gate

- Accountable task owner: operator; executor: Codex.
- Later lock/privilege review: `database-reviewer` role.
- Later scenario design/execution: `functional-test-reviewer` and `e2e-runner` after coding completes.
- Push/PR requires fresh GPT-PM approval correlated to the exact final code head.
