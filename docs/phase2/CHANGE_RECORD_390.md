# Change Record 390 - S15 source fixes from the GPT-PM gate review (M-01, M-02, residual minors)

## Ownership and scope

- Date: 2026-10-28. Source fixed by the implementation-engineer agent; committed by the coordinator. Follows CR-389.
- GPT-PM verdict on head 6af54a3: REJECT with 0 BLOCKER, 2 MAJOR, 3 MINOR, 1 NIT. This record closes them in source; tests follow in CR-391.

## Changes (src/erp_mcp_s15/)

- M-01 (reconcile): the 1C listing now declares its population (`population_scope`, `enumerates_unmarked`); reconcile requires the scope the
  caller asks for and returns INCONCLUSIVE `POPULATION_NOT_ESTABLISHED` otherwise, so a marker-index-only reader can never yield CLEAN.
- M-02 (ab_compare): lanes need distinct canonical source identities; equal names or identities give INCONCLUSIVE `SAME_LANE`; the baseline
  is bound to its identity pair (`LaneBaseline`) and a mismatch gives `BASELINE_PROVENANCE_MISMATCH`.
- Residuals: a CLEAN discarded by the restore epoch check is reported as INCONCLUSIVE `STALE_EPOCH`; CLEAN age is measured from the time
  before the reads started; `ApplyGate.record` requires an epoch; negative-control coverage compares exact canonical controls, not id prefixes.

## Verification state

- Agent: ruff clean and import smoke only; tests using the old signatures fail until adapted (CR-391). Re-verification by GPT-PM: NOT_RUN.
  Writer stays UNQUALIFIED and disabled; nothing wired.
