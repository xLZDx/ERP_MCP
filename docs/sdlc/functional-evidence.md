# Functional test evidence — S12 and S16 finisher slice

> Historical functional run record. These runs remain attached to their exact historical heads and are not current-head regression evidence. Current project acceptance and all remaining task criteria are summarized in the dated disposition below; the project plan and per-sprint evidence files remain authoritative.

## Current bounded-evidence disposition — 2026-11-23

The original 112-task project baseline has 107 tasks recorded as `ACCEPTED_BOUNDED`. The current registry has 119 task IDs: 115 project-document acceptances, one task superseded outside ERP_MCP scope, and 57 native-harness tasks in `done`. The remaining ERP_MCP product obligations are `FIN-S1.2` (deferred to final project verification), `S17-06` (fixed N=30 set and authenticated lane receipt absent), and `S19-03` (I1–I15 exact-head runtime evidence not run; coverage not adjudicated; G8 evidence false). `S16-04` is accepted bounded; `R2-US-047` is superseded because PDCC is outside this project's scope. Exact evidence, owners, and next actions are in [`PROJECT_PLAN.md`](../../PROJECT_PLAN.md) and the linked sprint evidence records.

FIN closeout was approved by GPT-PM under request `3b7f1905-5e0e-463b-920f-ee003ab035c0` for exact head `3f7fe83a94793bd97f0e3f5476d1e361668096a9`: nine of ten FIN stories are accepted within their bounded criteria; `FIN-S1.2` alone remains deferred to final project verification. Accordingly, current task status for `FIN-S2.1`–`FIN-S3.3` is `ACCEPTED_BOUNDED`, not `IN_REVIEW`. The 2026-11-17 run records below remain historical evidence and do not imply clean-tree or production qualification. The assigned S3.1 selection reported 1,048 passed, two warnings, and 56 subtests at dirty tree HEAD `240070b`; S3.2 includes the bounded read-only connector/recovery observation and a mocked installer test with routed review; S3.3 carries the exact-head bounded closeout decision. See the task rows and limitations in `PROJECT_PLAN.md` and the closeout record in `core/DECISION_LOG.md`.

The earlier S12/S16 run log below is intentionally retained as historical evidence. It does not claim a current-head full suite. Per project policy, full suites, CI, lint, typecheck and builds are not evidence for this status and were not run as part of this documentation update.

## Scope and provenance

Test scope: S12 producer contracts and S16 rev. 2 decision core, services, tool serialization and
replay fixtures. Requirements map: REQ-002/003, REQ-007–013; backlog stories S1.2, S2.1–S2.3,
S3.1. Source plan: `docs/sdlc/test-plan.md`, `docs/phase2/S12_CONTRACT_AMENDMENT_2026-10-28.md`,
and `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md` §§5.1–5.4, 6, 8–9.

The current source head verified for this S2.1 regression selection is
`7d978829222442aad9af4cb352cb018188239e81`. Initial workspace state also contained unrelated
uncommitted edits to `testlane/onec_extension/scripts/ct14_measure.py` and untracked
`docs/sdlc/AF_STATE.md`, `docs/sdlc/state.json`; these were not edited by this test work. The
functional test run below uncovered a source contract mismatch; source-fix status and final-head
reruns must be appended before acceptance is reported.

Environment: Windows PowerShell, repository `.venv\Scripts\python.exe`, `PYTHONPATH=src`.
All S12 producer tests use the repository's pure Python contracts and a deterministic fake reader;
S16 tests use the real parser, transition model, service/core and serialized tool registration over
in-memory ports. No database, network listener, real 1C, COM, writer or production endpoint is used.

## Story and gate matrix

| ID and plain meaning | State | Evidence completed | Remaining acceptance | Dependency/blocker | Recommended next action and owner |
|---|---|---|---|---|---|
| REQ-002 / S1.2 AC-1–2 — accounting period evidence is fresh, authenticated, scope/version bound, and fail closed | PARTIAL; fake-reader runtime proven, real-source NOT_RUN | `test_s12_period_producer.py`: open/closed distinction, mismatched binding/period/version, absent/malformed/stale/future observation, caller-flag clearing, one bound read, provider error secrecy. Passed in both focused runs. | A qualified authenticated 1C period reader and its runtime integration are absent per S12 amendment; no real-data period producer claim. | Missing concrete qualified reader; real 1C evidence unavailable in this scope. | Codex preserves `NOT_RUN`; product owner schedules reader qualification only under authorized scope. |
| REQ-003 / S1.2 AC-3 — exhausted positive grant maps distinctly from ordinary budget refusal | PARTIAL; Python policy runtime proven, producer qualification NOT_RUN | `test_s12_budget_producer.py`: exact empty-grant boundaries across reserved/consumed, insufficient nonempty remainder, zero amount, currency/window refusals, and S12 claim-guard code distinction. The first run exposed invalid test fixtures; corrected cases are included in the latest run listed below. | A real budget-observation producer is absent per S12 amendment; the Python test does not establish a real source read. SQL parity/exhausted-grant behavior is assigned to E2E owner. | No qualified real budget reader; SQL migration/behavior is separate. | Codex keeps real producer NOT_RUN; e2e-runner closes SQL path and records its exact dependency/outcome. |
| REQ-007/008 / S2.1 AC-1–4 — S16 core owns approval decisions, revalidation, single-use claims and canonical preview provenance | ACCEPTED_BOUNDED; fake-backed contract only | Focused fake-backed functional selections and current bounded closeout are recorded in `PROJECT_PLAN.md`; the exact GPT-PM closure is in `core/DECISION_LOG.md`. Historical rows below retain individual commands and results. | Process-local claim/issuance anchors do not prove durable SQL claims; live IdP/browser and production qualification remain separate. | None for the bounded task; production/runtime gates remain open. | Preserve the bounded label and keep live/durable qualification in the project backlog. |
| REQ-010–013 / S2.3 AC-1–5 — exact five tools, safe errors, S15 verification boundary and no approval alias | ACCEPTED_BOUNDED; synthetic service boundary | `test_s16_tools.py` and replay fixtures are part of the recorded S16 evidence; final bounded status is in `PROJECT_PLAN.md`. | Real chat clients, live listener and production writer remain `NOT_RUN`. | None for bounded task acceptance. | Do not equate fake-backed tool behavior with deployed client or production behavior. |
| REQ-005 / S3.1 AC-1–3 — required selected S15 suites run and map to acceptance | ACCEPTED_BOUNDED; dirty-tree result is explicitly limited | Assigned functional-test-reviewer reported the 21-module selection at dirty tree HEAD `240070b`: 1,048 passed, two warnings, 56 subtests, no failures or skips. Exact command and limits are recorded in `docs/sdlc/verify-evidence.md` and `PROJECT_PLAN.md`. | A clean exact-head run is not established by this historical dirty-tree evidence; product/runtime gates remain separate. | None for bounded closeout; no production qualification. | Preserve the exact dirty-tree limitation; do not repeat the accepted S17 tasks or promote runtime gates. |
| REQ-014/015/016/017 / S3.2–3.3 — connector/watchdog, safety bindings and future scope reconciliation | ACCEPTED_BOUNDED for the documented test/recovery and scope criteria | S3.2 bounded connector/recovery observations, mocked installer test and routed review are recorded in `PROJECT_PLAN.md`; S3.3's exact-head bounded approval is in `core/DECISION_LOG.md`. | No production binding or writer action was invoked; this does not qualify production, G8 or live 1C mutation. | None for bounded FIN closure; product qualification remains separate. | Keep the bounded acceptance and production/runtime gates distinct. |

## Execution record

### Run 1 — fixture defects found

- Code HEAD: `bbf2d9fd5ae28ebb2f756d9c6b856d6ef207223a`.
- Command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest -q tests\phase2\test_s12_period_producer.py tests\phase2\test_s12_budget_producer.py tests\phase2\test_s16_approval_core.py tests\phase2\test_s16_conformance.py tests\phase2\test_s16_tools.py tests\phase2\test_s16_replay.py`
- Result: FAIL, 18 passed / 15 failed.
- Cause: budget tests represented only reserved amount as total spent; S16 target fixture did not declare its business key free, so real S12 validation correctly returned `DUPLICATE_SUSPECTED`. The test inputs were corrected; no source defect was established from these failures.

### Run 2 — source behavior mismatch retained

- Code HEAD: `bbf2d9fd5ae28ebb2f756d9c6b856d6ef207223a`.
- Command: same six-module focused command above.
- Result: FAIL, 31 passed / 2 failed.
- Fixture issue: test used nonexistent `KillMode.HALT_ALL`; corrected to `KillMode.STOP_ADMIT` in test source after the run.
- Product finding: `test_apply_rechecks_approval_dependencies_and_target_before_apply[requester_epoch-EPOCH_CHANGED]` observed `NOT_ENTITLED`, while S16 plan §5.2 and backlog S2.1 AC-2 require `EPOCH_CHANGED` for an apply-time requester epoch change. This is a source defect for the implementation owner; assertion was not weakened.

### Run 3 — corrected S16 core plus selected S15 modules

- Code HEAD: `514d0ab401cd0a1f18c0de0851a84ad888a5d89a`.
- Command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest -q tests\phase2\test_s12_period_producer.py tests\phase2\test_s12_budget_producer.py tests\phase2\test_s16_approval_core.py tests\phase2\test_s16_conformance.py tests\phase2\test_s16_tools.py tests\phase2\test_s16_replay.py tests\phase2\test_s15_oracle.py tests\phase2\test_s15_verifier.py tests\phase2\test_s15_negative_controls.py tests\phase2\test_s15_ab_compare.py tests\phase2\test_s15_reconcile.py tests\phase2\test_s15_import_graph.py`
- Result: PASS, 947 passed in 6.48s.
- This command covered the six functional-owned modules and all six selected S15 modules. The result is exact only for the recorded HEAD; parent subsequently began a separate S16 ingress source correction, so it is not final-head evidence.
- Final-head rerun: `NOT_RUN` at current frozen head `499baa96a55cbd8b0df518372ddf6ca58966148a`, pending parent release after E2E focused execution. The E2E-owned SQL, page, ingress and slow integration results are recorded by their owner and must be reconciled here before closure.

### Run 4 — S2.1 and related functional regression selection

- Code HEAD: `7d978829222442aad9af4cb352cb018188239e81`.
- Command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s12_period_producer.py tests/phase2/test_s12_budget_producer.py tests/phase2/test_s16_approval_core.py tests/phase2/test_s16_tools.py tests/phase2/test_s16_conformance.py tests/phase2/test_s16_replay.py tests/phase2/test_s16_proposal_boundary.py`.
- Result: PASS, 70 passed in 1.26s.
- Coverage added for CODE1 proposal reconstruction against malicious scope/person/principal/time/change-id/digest values; CODE2 self-consistent store tampering and restart anchor absence; SEC1 T6 period/state/writer-lock/ownership guards and fail-closed missing reader; plus rollback parent conformance.
- An earlier attempt on the same HEAD failed 51 cases because the shared test helper passed an unsupported keyword to `FakeProposalPort.__init__`; this was a test-fixture defect, corrected by using the repository API. A subsequent rollback-only run passed 2/2 before this full selected pass.
- No S15 or SQL rerun was performed: accepted baseline evidence above remains unchanged; this run targeted only S2.1 and its directly affected functional contracts.

### Run 5 — pre-T6 claim release and retry regression

- Base code HEAD: `7d978829222442aad9af4cb352cb018188239e81`.
- Source files under test had an uncommitted delta in `src/erp_mcp_s16/contracts.py`, `src/erp_mcp_s16/core.py`, and `src/erp_mcp_s16/fakes.py`; `git diff --binary` SHA-256 for those three files: `0cc1d9d40df029cf83b131df2c31bd79cb84613f66bce43477ef1fbf8f43f7ac`.
- Command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s12_period_producer.py tests/phase2/test_s12_budget_producer.py tests/phase2/test_s16_approval_core.py tests/phase2/test_s16_tools.py tests/phase2/test_s16_conformance.py tests/phase2/test_s16_replay.py tests/phase2/test_s16_proposal_boundary.py`.
- Result: PASS, 75 passed in 1.98s.
- New cases prove missing/throwing evidence reader, closed-period and writer-lock refusals call no apply port and leave no active claim; released S12 state restores approved authorization, supersedes the token, releases reservation, and permits explicit retry at generation 2. Storage exception, false acknowledgement, and lying acknowledgement fail closed; retry first reconciles the same pending release and only then makes a fresh claim with a different token. Unknown apply remains latched at T6 (`APPLYING`/`CLAIMED`), and a repeat call does not invoke the apply port again.
- The initial focused run before finalizing the test assertions had one test error: it expected the S12 execution field to become `APPLY_UNKNOWN`; observed source behavior persists the T6 `APPLYING` record before the uncertain apply call. The regression now asserts that durable T6 latch and no-retry behavior; the full selected suite passes. No assertion was relaxed to turn a refusal into success.
- No SQL, S15, lint, build, or full-suite rerun was performed. Existing unrelated runtime evidence remains the previously recorded baseline.

### S2.1 approval-page and private-ingress regression

- Code HEAD: `7d978829222442aad9af4cb352cb018188239e81`.
- Command: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest -q tests\phase2\test_s16_approval_page.py tests\phase2\test_s16_private_ingress.py`.
- Result: PASS, 6 passed, one `httpx2` raw-content deprecation warning, in 0.40s.
- Evidence: approval HTML uses service-sourced lifecycle/authorization/version/created-at/current-approver metadata despite forged query values; decision reference is bounded to the decision forms; XSS is escaped; valid decision succeeds once, replay is denied, and a decided change has no decision form. Private ASGI ingress permits current authenticated requester/approver identities and rejects missing, wrong, expired, forwarded, foreign-host/origin, proxy, redirect, and unresolved-route cases before downstream dispatch.
- Initial run had three test-side failures: a post-decision page reopen was expected to return 200 although the service correctly denies it (expectation defect), and positive ingress fixtures used identities expired relative to runtime (fixture defect). Assertions/fixture clocks were corrected without source or coverage relaxation; this focused rerun passed.
- No listener, live ERP connector, or writer was exercised. SQL and S15 were not rerun because their accepted evidence is unaffected by this S2.1 interface selection.

## Coverage limits

The preceding current-status section supersedes status phrases inside the older run narratives below and in the matrix history: in particular, “final review pending” and “final-head rerun pending” describe the 2026-11-17 snapshot only. They are not current FIN statuses after the exact-head GPT-PM closeout.

- The pure S12 period boundary and Python reserve policy are not qualified concrete real-data producers; real period and budget reads are `NOT_RUN`.
- No SQL parity or disposable PostgreSQL outcome is claimed here. The S12 amendment explicitly records SQL `GRANT_EXHAUSTED` parity as not implemented; E2E owner holds that scenario.
- In-memory parallel claim proves only this process-local service/fake boundary, not S13 SQL locking.
- Replay cases are hand-authored client-shaped fixtures, not actual ChatGPT or Claude runs.
- The verified POST rollback fixture constructs a valid S12 `VERIFY_OK` row, inserts it through the fake store's public interface, and registers it through `S16Core.anchor_issuance`; this demonstrates the fake-backed trusted seed path only, not a production ledger import or durable trust mechanism.
- Run 5 tested the S2.1 implementation as an uncommitted working-tree delta over the exact base HEAD above; it is not committed-head evidence.
- No real IdP, approval UAT, listener, deployment, COM writer, real POST/UNPOST, or production operation was run.
