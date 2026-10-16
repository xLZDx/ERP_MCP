# Change record 075 — separate local push evidence from the formal G1 release gate

## What changed

- Reframed `G1_EVIDENCE_PACKET_PLAN.md` around focused local test-agent results, relevant specialist review, and fresh exact-head GPT approval as evidence for a local engineering push.
- Kept the formal G1/release requirements separate: exact-head scenario results, capacity disposition, deployed effective-role/grant and authenticated identity evidence, plus gate-specific review. These remain relevant to G1/release and production authorization, not additional production-environment prerequisites for a local push.
- Clarified the disposable PostgreSQL DSN is test infrastructure for the local integration/multiprocessing suite. Docker fixtures own the crash/restore clusters; host `psql` is optional.
- Reconciled `G1_OPERATOR_BACKLOG.md`, `docs/sdlc/STATE.md`, and the S14 closure packet so they distinguish local push readiness from formal G1/release status.
- Updated the workspace test policy so test and check execution is delegated to the actual test agents after coding is complete; removed the prior blanket restrictions.
- Created a dedicated PostgreSQL 16 Docker container bound only to loopback and installed project plus development dependencies into this repository's isolated `.venv`.
- Delegated B04–B07 functional cases to `functional-test-reviewer` and the explicit-COMMIT/separate-cluster restore cases to `e2e-runner`.
- Initial focused functional report at committed HEAD `4b9f3b08b4e75359b549bda75d6f6ec3307f248e`: 46 passed, 1 failed. The failed restore assertion directly called `living.assert_scope` as `living_reader`; PostgreSQL correctly denied execute on the internal helper before scope validation.
- The explicit-COMMIT E2E case passed: the observer saw COMMIT underway and the expected lock wait before termination. The separate-cluster restore case failed at the same invalid helper call.
- The functional test owner replaced the internal-helper call with a non-vacuous existing-context RLS visibility assertion before and after grant deletion, set the transaction to `READ COMMITTED`, and retained the separate fresh-context `living.set_scope` denial. An intermediate rerun caught stale result-shape assertions; those assertions were corrected. The final retry was stopped after the current workspace instructions prohibited the test command, so the current test diff has no completed rerun and is `NOT_RUN`.

## Why

The previous wording conflated test execution against local disposable fixtures with a separate deployed/production runtime evidence package, and described missing `psql` as an environment blocker even though the focused tests use `asyncpg` and container-local PostgreSQL utilities. The operator clarified that local test-agent results and GPT review are the evidence expected for the local code push. The formal release gate remains unchanged.

## Decisions and scope

- Local push acceptance: focused functional/E2E tests authored and executed by the designated agents, relevant specialist review, and fresh GPT approval of the exact final diff/results.
- Formal G1/release acceptance: remains `NOT_PASSED`; production authorization remains `NONE`; Release 2 remains `NO-GO` until its formal evidence is accepted.
- No production database, deployed account, or real identity evidence is required to support the local code-push claim.
- `D:\Repo\AGENTS.md` now assigns required tests/checks to the actual agents; the prior blanket check prohibition was removed at the operator's instruction.
- The original baseline run is a failure (46 passed, 1 failed); the corrected test diff is not runtime-proven. Do not infer a pass from the code change or from the prior run.
- PostgreSQL-backed test scenarios require an isolated disposable local DSN; a host-installed `psql` is not required.

## Review and verification state

- Read-only documentation review: `doc-updater` (GPT-6 Luna, medium effort) confirmed the distinction between local push gates and formal G1/release gates and identified the files reconciled here.
- Setup: a dedicated loopback PostgreSQL 16 container named `erp-r2-g1-ef2e3f349883` is ready on `127.0.0.1:47868`; the random credential is held only in the agent launch environment, not this record.
- Dependencies: `uv` created `.venv` and installed the project plus development requirements, including `asyncpg`, the async test plugin, and test runner.
- Test execution is delegated to the named agents; the primary session did not execute test commands.
- No database migrations or production operations were run.
- `governance/GATE_MANIFEST.json` was not changed.
- This documentation change does not authorize push; focused tests, relevant specialist findings, and fresh exact-head GPT approval remain outstanding.

## Contracts and paths

- `docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`
- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/sdlc/STATE.md`
- `core/DECISION_LOG.md`
