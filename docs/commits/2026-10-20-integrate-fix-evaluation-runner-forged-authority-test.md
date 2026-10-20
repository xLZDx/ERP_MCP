# Fix forged-authority test after combining phase2 with BASE hardening (2026-10-20)

## Why
BASE's reconciliation dataclasses (Comparison, PurchaseComparison, ObservedMetadata, ObservedDiff, backend_budget) validate in __post_init__ that authority is EVALUATION_ONLY. The phase2 branch's test tests/phase2/test_evaluation_runner.py::test_compare_returning_wrong_type_or_foreign_authority_is_rejected built `Comparison(..., authority="PROMOTED")` directly, which now raises ValueError(RECONCILIATION_AUTHORITY_FORBIDDEN) before the runner is reached.

## What
Kept BASE's hardening. The test now (1) asserts the constructor rejects the forged authority and (2) builds the forged value with object.__setattr__ so the runner's own rejection of a foreign authority (COMPUTE_FAILED) is still exercised. No assertion was removed or weakened; one was added.

## Verification
tests/phase2/test_evaluation_runner.py: 114 passed.
