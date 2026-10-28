# Change Record 386 - S15 verifier, oracle, negative controls, A-B comparison and ledger reconciliation (code)

## Ownership and scope

- Date: 2026-10-28. Accountable owner: operator; code by the implementation-engineer agent; committed by the coordinator.
- Adds the new package `src/erp_mcp_s15/` (`oracle.py`, `read_interface.py`, `verifier.py`, `negative_controls.py`, `ab_compare.py`,
  `reconcile.py`, `labels.py`). Implements the sprint plan `docs/phase2/S15_SPRINT_PLAN_2026-10-27.md` (CR-384, CR-385).

## Changes

- Oracle (E15-2): versioned typing table and total rule; imports neither the writer nor preview/normalization modules.
- Verifier (E15-1): CREATE_DRAFT one-line receipt only; other shapes are UNSUPPORTED_SHAPE; incomplete reads are INCONCLUSIVE.
- Negative controls (E15-5): 19 controls (8 plan, 11 from S14 facts), each with a note naming the observable value that would differ.
- A-B comparison (E15-3) and bidirectional ledger-1C check with three triggers and an apply gate that is inert while the writer is
  disabled (E15-4): pure logic over injected ports; fakes only because S12/S13 are not accepted.
- Package location is a new top-level package so the import graph of the oracle stays free of the writer package.

## Verification state

- Agent smoke only: ruff clean, import smoke, one `run_all()` call. Functional tests: NOT_RUN (written and run by test agents next).
  Specialist reviews and GPT-PM review: NOT_RUN. Nothing is wired into a gateway; the writer stays UNQUALIFIED and disabled.
- Receipt field paths and catalog names in the typing table are assumed logical names (UNKNOWN against the real binding).
