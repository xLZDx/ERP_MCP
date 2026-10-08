# Phase 2 — convergence hardening and adversarial review (2026-10-09)

> **Later security continuation:** This document records the first 940-PASS code batch. See `CONVERGENCE_FINAL_SECURITY_REVIEW_2026-10-09.md` for the three additional failure-code leakage regressions, later 943-PASS evidence and current release NO-GO.

**Branch:** `hardening/phase2-convergence-reviewed-20261009`. **Base:** `d1f87bc` plus the already-reviewed backend-budget, comparison trust and observed-metadata changes from the prior safety worktree (committed parent `c54be14`). This branch is isolated; active R2 and R1 worktrees are not modified.

## Remediations reviewed

- **P-M1 attestation preflight:** require a real `AttestationView`, true UUIDs and a matching revision and evidence reference before any write port invocation. Decision must be a built-in `str` exactly `APPROVE`, stored digest a built-in string, trusted reviewer must return literal `True`. A forged equality object or truthy string cannot promote. Preserve the updated `d1f87bc` post-commit ambiguity handling, CAS and SQL safety rather than replacing with old service implementation.
- **DR-01 observed versus accepted:** first complete capture is only a candidate (not an automatically established accepted head). Subsequent distinct hashes remain candidates, preserving accepted head. The parallel branch's existing `candidate_hash` API is retained.
- **Scheduler numerical policy:** reject bool, nonfinite, fractional policy values and enormous ints which cannot convert safely to finite, bounded timers. Preserve the concurrent branch's advanced state/lease/fence/retry and cancelled-work controls.
- **SCH-02 residual exception leak:** the `d1f87bc` scheduler removed raw error messages but still persisted `type(exc).__name__`. A dynamically named exception class with `CANARY_SECRET_12345` demonstrated a persisted `WORK_EXCEPTION:Authorization_Bearer_CANARY_SECRET_12345`. This has been replaced with the fixed code `WORK_EXCEPTION` and positive retry/poison expectations were updated.

## Review by perspectives

- **Security:** a read-only/misrouted attestation cannot forge trust with custom equality objects; external exceptions cannot echo arbitrary class-name content into job metadata; the SQL database remains the ultimate authority.
- **Functional:** intentional successful promotion, rollback, replays, stale-fence recovery, poison and cancellation continue to be tested by the common Phase 2 suite. The new security guards must stop before `promote_head`.
- **Reliability/performance:** numeric upper bounds prevent nonfinite lease/retry timings. Offline tests do not prove load/throughput, distributed lease fairness, restart durability or production capacity.
- **Database:** existing PostgreSQL tests from older exact SHAs cannot be transplanted into an approval of this new code HEAD. No database migration was added in this patch.
- **Adversarial counterargument:** compromised DB service, arbitrary Python mutation of internal in-memory objects, bad external adapters and unsourced native reports remain outside these local proofs. An offline match/approval is not an accountant acceptance or a release approval.

## Actual local checks

- First convergence worktree's uncommitted snapshot, Phase 2 offline: **939 PASS / 217 SKIP**, Ruff PASS.
- Independent reviewed copy after fixed `WORK_EXCEPTION` and canary regression: **940 PASS / 217 SKIP** in 15.58 seconds, Ruff PASS, compileall PASS. Evidence logs held locally in the isolated reviewed worktree.
- No exact-head SQL/G1 restore/crash/guard mutation, live Phase 2 source-wide capture, accountant attestation, Drive OAuth/UAT/canary or GitHub CI was performed for this patch yet. **All G0–G7 are still unapproved; Release 2 NO-GO.**

## Next gates

Perform exact-head PostgreSQL contract tests on a permitted isolated disposable DB, full Release 1 baseline compatibility with governed checkpoint plan, plus independent security/architecture review. Merge/push only through the Phase 2 project's exact-head review process, not by claiming the local offline PASS is terminal.
