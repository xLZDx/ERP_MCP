# Phase 2 Finisher E2E and Runtime Evidence Plan

Sprint: `beea27520b33`

## Purpose and execution gate

This document plans evidence collection for REQ-005 and REQ-014–REQ-016 in
`docs/sdlc/requirements.md` and stories S3.1–S3.3 in `docs/sdlc/backlog.md`.
It does not record test, probe, or runtime results. Coding is a prerequisite:
do not start any test/check or live verification until all in-scope code is
complete and the candidate final `HEAD` is fixed. The test agents own test
authoring and execution; Codex coordinates exact-head provenance and evidence
reconciliation. Do not change assertions to make a failing run pass.

The evidence record must distinguish implementation, manual review,
runtime-proven behavior, and `NOT_RUN`. A result from another revision or an
earlier run is historical context, not proof for the candidate head.

## Required test journeys

| ID / meaning | Scope and acceptance evidence | Owner | State before execution |
|---|---|---|---|
| S3.1a — SQL parity | At candidate final `HEAD`, apply the additive SQL migration in the approved isolated test database and compare the SQL refusal registry to the canonical 39-code Python registry. Exercise exhausted grant with positive requested amount (`GRANT_EXHAUSTED`), preserve other `BUDGET_EXCEEDED` cases, and capture the migration/parity output. Record SQL-inexpressible Python cases in the associated change record. | `functional-test-reviewer` authors/runs mapped functional coverage; `e2e-runner` runs the required SQL/E2E set; Codex reconciles evidence. | PLANNED; implementation/runtime evidence not asserted here. |
| S3.1b — S12/S13 real-data and ledger journeys | At candidate final `HEAD`, exercise authenticated period observation and fail-closed cases (closed, missing, contradictory, stale, unauthenticated), exhausted-budget evidence from real source data, and in-flight list/status derived from ledger/service state. Use isolated deterministic records and prove refusal paths do not call a writer. Keep any live 1C POST/UNPOST out of scope. | Same test-agent ownership; Codex checks coverage against REQ-002–REQ-004. | PLANNED; live/source availability may make individual evidence `NOT_RUN`. |
| S3.1c — Required slow E2E and S15 suites | Run the repository's designated slow SQL/E2E sets and the S15 suite at the same candidate final `HEAD`; include all S15 cases required by `docs/phase2/S15_SPRINT_PLAN_2026-10-27.md`. Record exact invocation(s), selected tests/markers, database/runtime prerequisites, skips, and limitations. Do not infer S15 acceptance from fakes or historical reports. | `e2e-runner` executes required E2E coverage; `functional-test-reviewer` authors/runs required functional coverage; Codex verifies story/gate mapping. | PLANNED; exact commands and suite selection are to be recorded by the test agents after inspecting the repository test configuration. |
| S3.1d — S16 approval and replay journey over fakes | Cover the full single-test journey: propose → service-issued canonical preview/digest and nonce → isolated test approver session/decision → apply-time revalidation and claim-once → verify. Include nonce/digest/version/expiry replay or tampering refusal, spoofed approval chat text no-op, deterministic replay for ChatGPT-shaped and Claude-shaped recorded request fixtures, exact five-tool surface, `approve` direct-call refusal, POST/UNPOST `UNSUPPORTED_SHAPE` without `VERIFIED`, and rollback mapping (`rollback_propose` creates separately approved UNPOST for verified POST; CREATE_DRAFT/UNPOST return `ROLLBACK_REFUSED`). Verify refusal occurs before apply port invocation where specified. Label fixture provenance as observed client capture or hand-authored request shape. | `functional-test-reviewer` and `e2e-runner` author/run their mapped suites; Codex checks coverage. | PLANNED; fake-level only. This proves neither real client behavior nor real IdP/connector behavior. |
| S3.1e — Private listener boundary | Cover positive authentication per request and fail-closed cases for missing/invalid credentials, loopback without identity, foreign Origin/Referer on approval POST, forwarding headers, mismatched Host, public target, redirect/proxy path, and DNS rebinding representation. Assert apply port is not called on rejected requests. Use controlled fakes; do not expose or deploy a listener as part of the test. | Test agents, mapped to REQ-009 and the S16 E16-4 contract. | PLANNED; test-only boundary, no deployment claim. |

### Exact-head evidence record

For every test group above, record: repository path, commit hash, clean/dirty
state relevant to the run, exact command, selected test files/markers, runtime
and database dependencies, start/end timestamps, result and test counts,
skips, artifact paths (logs/traces/screenshots/request identifiers where
available), and limitations. Include the exact revision in agent handoffs and
ensure all coding is complete before the first test run. The test agents choose
commands from the existing repository configuration; this plan does not add a
test framework or prescribe unverified commands.

For each red result, classify the cause as product bug, test defect, flake, or
environment and cite the trace/log/response evidence. A flake classification
requires repeated runs on the same commit establishing that it passes and
fails. Fix a defect at its cause; never weaken/delete an assertion. Report
quarantine separately with a linked issue, owner, and expiry; do not silently
quarantine coverage.

## External ERP_MCP evidence

### ERP_MCP_REAL1 connector reachability (REQ-014)

After coding completion, use the available **ERP_MCP_REAL1 connector tool** for
one authorized read-only reachability operation. Capture the operation/tool
name, observed endpoint identity if returned, timestamp, response/error, and
correlated request identifier when available. Do not expose credentials,
tokens, authorization headers, or secret configuration. A result from the DC
connector or an HTTP 429 from that connector is unrelated and must not be used
to infer ERP_MCP connector status. If the ERP_MCP connector is unavailable,
record `NOT_RUN` with its exact tool error; do not manufacture a result from
local service state or old records.

Owner: Codex. No call has been made as part of this planning document.

### One-component local lane watchdog restart (REQ-015)

Only after the coding and test phases, and only on the named local
`ERP_MCP_Lane_Autostart` lane from the finisher attachment, select exactly one
non-stateful component that the configured autostart script itself manages.
Prefer the tunnel-client process if and only if the script confirms it is a
managed lane component; otherwise select the least disruptive managed,
non-stateful component and record the reason before acting. Do not stop a
database, Redis, 1C, or any component outside this lane. Do not restart a
production service.

Before the single stop, capture the selected component identity, PID/process
start time or service/container identity, listener state if applicable, and
the relevant autostart configuration/task identity. Stop that one component
once through its normal control surface. Observe the configured autostart
mechanism, then capture the same identity and listener evidence after restart,
plus the new PID/start time where the process model replaces PIDs. The evidence
must establish that the same component returned because of the configured
autostart mechanism, not because it was manually launched. Do not use a fixed
sleep as proof; wait for an observable process/listener condition within a
bounded window and report timeout as failure/`NOT_RUN` with exact evidence.

If the component cannot be proven to be managed by the named autostart script,
or stopping it would risk a stateful service or out-of-scope system, do not
stop it; record `NOT_RUN` and the concrete dependency. Owner: Codex.

## Clone-write boundary and prohibited evidence

Prefer no new clone mutation run. This plan does not authorize one. Any
scenario that would write to 1C is `NOT_RUN` unless separately authorized and
all safeguards are satisfied: disposable clone `818HA_p2diff` only, writes
through `ct14_common.guard`, transaction rolled back, least-privilege
`CT14_NARROW`, and a verifier registered before mutation whenever a principal
or catalog could persistently change, with before/after snapshots. Do not
modify `testlane/onec_extension/scripts/ct14_measure.py`. Real POST/UNPOST,
production binding, deployment, production actions, and real-money actions
remain prohibited. The private writer stays `UNQUALIFIED` and disabled; the
production binding set stays empty.

S16 replay fixtures and complete approval journey are fake-backed evidence.
Real client observations, production IdP authentication, UAT, deployment,
real 1C POST/UNPOST, and A/B reconciliation remain `NOT_RUN` or deferred as
specified by the S16 and S15 plans; never upgrade fake replay into a real
connector/client claim.

## Acceptance handoff

At final reconciliation, map each result to REQ-005, REQ-014–REQ-016 and
backlog S3.1–S3.3. The test agents supply exact-head test artifacts; Codex
verifies that every acceptance criterion is covered and labels runtime
limitations. Promote S12/S13/S15 status only against current gate-manifest and
change-record evidence plus required current-head results. If evidence is
missing, preserve unaccepted/unknown status and name the exact missing item.

| Deliverable | State | Evidence/completed work | Remaining acceptance | Dependency/blocker | Next action and owner |
|---|---|---|---|---|---|
| S3.1 exact-head SQL/E2E/S15 and S16 fake journeys | PLANNED; not run | This plan maps required journeys to REQ/backlog and S15/S16 contracts. | Complete coding, then mapped runs with exact hash, commands, results, skips, and artifacts. | Coding not complete; exact suite commands must be derived from repository configuration. | Test agents author/execute after code completion; Codex reconciles. |
| REQ-014 ERP_MCP_REAL1 reachability | PLANNED; no probe performed | Named ERP_MCP_REAL1 connector operation and safe evidence fields are specified. | One read-only connector result, or exact `NOT_RUN` error. | Connector tool/runtime availability. | Codex uses ERP_MCP_REAL1 connector after coding; no DC result substitution. |
| REQ-015 local watchdog | PLANNED; no stop/restart performed | Single-component procedure scoped to named local autostart lane. | Before/after evidence proving same managed component restarted, or precise `NOT_RUN`. | Confirm the selected non-stateful component is managed by the named task/script. | Codex select and execute one bounded lane-only restart after coding/tests. |
| REQ-016 safety boundary | ACTIVE constraint | Plan preserves no production/real-write/deployment and no writer enablement. | Maintain throughout execution and report any prohibited scenario as `NOT_RUN`. | No authorization to cross prohibited boundary. | Codex and test agents retain the boundary; no mutation run planned. |

## Ordered next steps

1. Codex completes all in-scope coding before any test or runtime evidence work.
2. The test agents inspect existing test configuration, select and record exact
   commands, then author and execute the mapped tests at the fixed candidate
   final `HEAD`.
3. Codex performs the ERP_MCP_REAL1 read-only connector check and, separately,
   the single eligible local watchdog restart; report exact outcomes or
   `NOT_RUN` reasons.
4. Codex reconciles test and runtime evidence against the gate manifest,
   requirements, and change records; retain `UNKNOWN`/unaccepted claims where
   proof is missing.
