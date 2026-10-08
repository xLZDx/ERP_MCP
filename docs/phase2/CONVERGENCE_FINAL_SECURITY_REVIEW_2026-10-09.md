# ERP_MCP Phase 2 — convergence security closure, 2026-10-09

**Branch:** `hardening/phase2-convergence-reviewed-20261009`. **Production decision: NO-GO.** This record documents the isolated engineering patch only; it does not confer approval for rollout, merge, or real 1C writes.

## What changed

Base `d1f87bc` (Phase 2 S1–S4 replay, scheduler, SQL contract review changes), plus bounded backend limits and immutable OBSERVED/EVALUATION trust labels from the prior safety lane. The code patch committed first as `3cfd9ba` enforces:
- Promotion preflight: a genuine `AttestationView` and matching UUID/evidence identity; built-in APPROVE string, exact evidence digest string, literal trusted-reviewer True before calling write-port.
- Drift: a first observed schema is a **candidate**, not an automatically accepted semantic profile. Existing `candidate_hash` API stays compatible with the parallel review branch.
- Scheduler: finite built-in numeric bounds prevent bool/inf/oversized-int configuration errors; callback exception class names no longer reach job results and persisted errors.

Second adversarial pass against `PromotionService` uncovered three more RED scenarios:
1. Untrusted exception class name from a possibly committed `promote_head` call escaped as a client-facing code.
2. Untrusted exception class name during the prewrite/read portion escaped via `_failed`.
3. Unknown `PortError.code` was returned verbatim, including a synthetic canary string.

Remedy: after write-port exceptions return **INDETERMINATE / PROMOTION_INDETERMINATE** (never falsely claim rollback); before-write unknown errors return **FAILED_CLOSED / PROMOTION_FAILED**; unknown typed port codes return **FAILED_CLOSED / PORT_ERROR**. Known stable `_PORT_CODES` remain unchanged. No raw exception text/class or unknown raw port codes appear in responses.

## Verification and independent review perspectives

- Tests for all above unauthorized echoes failed prior to the second change and pass afterward. Offline `pytest -q tests/phase2` on the updated worktree: **943 passed, 217 skipped** in 15.27 seconds, no failures; Ruff PASS. Integration marker `pytest --collect-only -m integration` enumerated precisely **217** DB/integration cases, and these are **NOT_RUN** on the patch HEAD.
- **Security:** no forged approval/trust, arbitrary backend budget, or exception metadata is accepted through the tested public service boundaries.
- **Functional:** approved requests, idempotent replay/rollback and state-machine tests continue to pass in the offline suite; the uncertain postcommit outcome stays uncertain.
- **DB/reliability:** real postgres RLS, crash/restore, job fencing and replay tests must be rerun on this exact candidate; historic 280 selected PostgreSQL PASS on `edc8d9d` cannot be copied as exact-head signoff.
- **Devil's advocate:** the result is still a reference service with fake/in-memory port tests; the Phase 2 source registry authority, independent accountant attestation, Drive OAuth consent, admin UAT, canary/rollback and all G0–G7 acceptances remain open. One source-inspection operation was blocked by workstation policy; it was not bypassed. Potential unknown-code leakage in other connector audit paths remains a distinct follow-up requiring authorized review.

## Release gate: explicit NO-GO

G0 owner/security/architecture/license decision OPEN; G1 exact-head PostgreSQL, capacity and independent DB approval OPEN; G2 real source-bound metadata capture OPEN; G3 native 1C 521.1 proof with accountant independent signoff OPEN; G4 narrow ERP-owned Drive OAuth OPEN; G5 actual user/admin workbench UAT OPEN; G6 secret rotation, load, chaos, rollback and canary approval OPEN; G7 exact bundle and release-owner approval OPEN.

**No release, merge, push, write to 1C or rollout authorization follows from a green offline test run.** The original Phase 2 worktree is preserved with its unrelated uncommitted changes.
