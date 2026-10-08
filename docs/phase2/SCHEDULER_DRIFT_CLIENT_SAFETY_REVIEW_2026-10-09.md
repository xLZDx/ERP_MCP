# Phase 2 scheduler and drift safety review — 2026-10-09

Branch: `hardening/phase2-client-safety-combined-20261009`. Production/Release 2 stays **NO-GO**; no runtime or 1C resources were modified.

## SCH-01 — invalid lease/backoff/poison configuration accepted (FIXED)

**Initial RED:** 12 new negative cases (10 RED / 2 already green) showed that Python numeric comparisons let bool, fractional retry limits and `Infinity` pass into `SchedulerConfig` or `backoff_delay`. Six further overflow/extreme-number cases all RED: very large integers could cause an unchecked `OverflowError`, or an immense backoff cap could exceed `timedelta` bounds.

**Fix:** config lease/poison/quarantine fields now demand built-in integers; margin/backoff/jitter demand concrete numeric types that can be converted to a finite float within the safe `timedelta` range; backoff and margin are checked against their normal range and poison limits are positive. Invalid data returns stable `ValueError` rather than accepting an unbounded policy or failing later while a job is active. Positive retry, jitter, lease renewal, stale-fence and source quarantine behaviors remain unchanged.

**Post-change evidence:** `pytest -q tests/phase2` **778 passed / 180 skipped / 0 failed** in 10.64 s. `ruff check src/business_ai_gateway/phase2 tests/phase2` PASS, `compileall` PASS. The skipped tests remain NOT_RUN on this HEAD.

**Reviews:** Security — config cannot disable a time bound via nonfinite or masquerading numeric values. Functional — normal schedules and concurrency regressions green. Reliability — catastrophic `timedelta` overflow rejected on setup; still no multi-worker/distributed fairness or tested production throughput. Tests — all new negative scenarios RED before mitigation and GREEN afterwards. No removal of test coverage.

## DR-01 — ambiguous accepted model hash in drift classifier (OPEN DESIGN/RISK)

`drift.classify(CaptureOutcome(OK_COMPLETE, observed_hash_B), previously_accepted_hash_A)` emits `STRUCTURAL_DRIFT` **and returns** `accepted_hash=B`; existing test `test_complete_capture_with_different_hash_is_drift_and_advances_baseline` asserts this. The `DriftDecision` dataclass comment calls the property the accepted baseline after the outcome. This is potentially incompatible with the accepted-head CAS/independent attestation policy and can suppress repeated drift detection if used directly to update an accepted model. The module is offline/unwired, and this observation is NOT proof of a real promotion bypass.

**Required owner decision before wiring:** distinguish independently attested accepted-head hash from last-observed candidate hash, specify first-snapshot handling and whether structural drift is quarantined pending approval. Tests should ensure observing B after accepting A does **not** silently promote B or mark all affected tools safe. Treat this as a blocking contract ambiguity, not a confirmed deployed exploit. It was not silently changed because existing acceptance tests intentionally assert the current behavior.

## External release gates (unchanged)

G0 model/source registry authority; G1 database exact-head verification and acceptance; G2 live 1C; G3 accountant-attested native reports; G4 OAuth/Drive consent; G5 user/admin UAT; G6 canary/chaos/recovery/load; G7 accountable release approval. No hosted CI, production DB/1C writes, or customer signoff authorized by this review.
