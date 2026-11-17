# Change record 407 — focused S12/S16 functional acceptance tests

## What changed

- Added focused tests for authenticated period evidence and Python budget boundary behavior.
- Added S16 deterministic service fixtures plus core, conformance, tool-boundary and replay tests.
- Added `docs/sdlc/functional-evidence.md` to map each result to the accepted requirement/story and
  gate, preserve exact execution commands, and state fake-backed and unavailable evidence limits.

## Why

The S12 amendment and S16 rev. 2 plan require falsifiable post-code tests for producer evidence,
decision ownership, apply-time revalidation, claim-once behavior, S12 transition fidelity, tool
serialization and safe errors. The S12 real-data producers and S13 database claim are not qualified;
tests and evidence keep those boundaries explicit.

## Affected contracts and paths

- REQ-002/003, REQ-007–013; backlog S1.2, S2.1–S2.3, S3.1.
- `tests/phase2/test_s12_period_producer.py`
- `tests/phase2/test_s12_budget_producer.py`
- `tests/phase2/s16_helpers.py`
- `tests/phase2/test_s16_approval_core.py`
- `tests/phase2/test_s16_conformance.py`
- `tests/phase2/test_s16_tools.py`
- `tests/phase2/test_s16_replay.py`
- `docs/sdlc/functional-evidence.md`

## Decisions and findings

- Tests invoke the real S12 parser/transitions and S16 core/services/tool registration over
  deterministic in-memory ports; no custom test-only authorization decisions stand in for core
  policy.
- Period snapshot tests prove only the existing pure boundary. Real period and budget producers
  remain `NOT_RUN`, matching `S12_CONTRACT_AMENDMENT_2026-10-28.md`.
- First focused run at `bbf2d9fd5ae28ebb2f756d9c6b856d6ef207223a`: 18 passed / 15 failed due to
  invalid test fixtures, corrected in test code.
- Second focused run at the same HEAD: 31 passed / 2 failed. It exposed an S16 behavior mismatch:
  apply after requester epoch change returned `NOT_ENTITLED`; S16 plan §5.2 requires
  `EPOCH_CHANGED`. The strict assertion remains. A test enum typo was also corrected.
- The implementation owner corrected apply-time epoch error handling in commit `514d0ab`.
- The combined focused/S15 command at `514d0ab401cd0a1f18c0de0851a84ad888a5d89a` passed 947
  tests in 6.48s. This includes the six owned functional modules and six selected S15 modules.
- A later, separate ingress source correction was underway; final exact-head rerun and E2E-owned
  SQL/page/ingress results remain pending. Full evidence is in `docs/sdlc/functional-evidence.md`.
- Parent reports the source frozen at `499baa96a55cbd8b0df518372ddf6ca58966148a`; the single
  consolidated final-head run is awaiting completion of the E2E-owned focused execution.
- No product source code is modified by this test change record.

## Verification state

Functional verification: **PASS at `514d0ab`; current-head rerun pending** at frozen
`499baa96a55cbd8b0df518372ddf6ca58966148a` per the coordinated single-run gate.
Full repository tests, build, lint, migrations, SQL integration and production activity were not
run by this work.
