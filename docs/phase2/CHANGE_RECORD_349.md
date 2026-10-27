# Change Record 349 — transport errors in evidence validation and migration harness results

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session.
- Covers `postgres_evidence_registrar.py` (finding F2 of Change Record 348) and the migration harness evidence.

## Change

In both validation `try` blocks, `OSError`, `asyncpg.PostgresError` and `asyncpg.InterfaceError` now raise `EVIDENCE_REGISTER_UNAVAILABLE`. Other unexpected errors still raise `EVIDENCE_REGISTER_VALIDATION_FAILED` and are logged.

## Verification state

- RUN by the functional-test-reviewer agent at f06fa2d: migration 020, 022, 023 and 026 harness scripts passed (023 and 026 only with `ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS=1`, a test defect in their `__main__`). Migration 027 was not applied; effective grants stay NOT_MEASURABLE.
- RUN: focused pytest selection after this change 273 passed, 8 skipped, 0 failed (S13, WP5, S14, writer, T16 selection).
- NOT_RUN: a dedicated regression test for the new mapping (no existing test constructs a `CallIdentity`), review.
- Also: `test_s13_migration023.py` and `test_s13_checkpoint_suffix_functional.py` now set the cluster gate variable in `__main__`, like their sibling scripts.
