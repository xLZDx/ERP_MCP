# S20 — Bounded observability completion

Date: 2026-11-20
Status: IN_REVIEW / PM round-1 MAJOR and two post-commit MINOR findings corrected; focused fault verification and all routed reviews accepted at source HEAD `dafd42a186a7919b17048a53d55d687a8429050c`; GPT-PM round 2 pending  
Trace: `docs/MASTER_PLAN.md` §P8, `docs/DEFINITION_OF_DONE.md` D12, `docs/OBSERVABILITY_SRE.md` §§2–5
Base: main at `7cea4dea18193d12a7514081aca5954f4fb19e0d`

## Sprint goal

Wire operation-duration telemetry into the registered read-only MCP tool execution path. Keep the existing audit append path as the single owner of tool/outcome counters; measure duration at dispatch without increasing the data exposed by logs or metric labels.

This is a scope-preserving P8/D12 completion slice. It does not add business features, metric labels containing tenant/source identity, or new telemetry sinks. It does not qualify production observability, alert delivery, live source health, load objectives, G8, pilot, or production readiness. S17-06 and S19-03 remain partial, and FIN-S1.2 remains deferred to final project verification.

## Priority and readiness

Priority rule: close an already specified P8/D12 instrumentation gap before broader operational evidence work; preserve the frozen privacy boundary; keep environment-specific readiness evidence separate from code behavior.

The gap is directly evidenced in the current source: `OperationalMetrics` has a fixed tool allowlist and operation counters; `Audit._monitored_append` already records tool outcomes after the audit insert. HTTP request instrumentation records transport outcomes and latency, not the MCP tool name or operation duration. The allowlist also omits the registered `purchase_documents_filtered` tool. The accepted SRE contract requires requests by tool/outcome and bounded telemetry. Reconcile the allowlist with registered tools and add duration only at dispatch; do not add another tool/outcome counter.

Definition of Ready:

- D12 and `OBSERVABILITY_SRE.md` are the normative contracts.
- The fixed tool/outcome allowlists and request correlation helpers already exist.
- The changed boundary is the MCP server tool invocation path; no runtime route or authorization policy is changed.
- Named functional cases are `tests/test_observability.py` plus focused server contract cases identified by the functional-test role after implementation.

## Story S20-01 — MCP operation duration

**Goal:** record exactly one bounded operation-duration sample for every registered MCP tool invocation, including normal return, refusal/error, and cancellation, using existing privacy-safe metric conventions. Tool/outcome counters remain owned by the audit append path.

### Acceptance criteria

1. Given any registered tool invocation that returns normally, when it completes, then exactly one duration sample is added to a bounded aggregate under its registered fixed tool name; the allowlist covers all registered tools, including `purchase_documents_filtered`.
2. Given an invocation that returns an MCP error/refusal or raises, when it completes, then exactly one duration sample is recorded and the original result/error behavior is preserved.
3. Given cancellation while a tool is running, when cancellation propagates, then exactly one duration sample is recorded and cancellation is not swallowed.
4. Given an unknown/free-text tool label, when metrics are rendered, then it maps to `other`; label cardinality remains bounded by the fixed allowlist.
5. Given many invocations, when aggregates are retained, then storage is bounded by fixed tool keys and stores only finite capped count/sum values, never an unbounded per-call sample list.
6. Given any invocation, when metrics/logs are emitted, then no caller-supplied query, URL, source/company ID, principal, credential, or business result is added to labels or event fields by this change.
7. Given an audit append success/failure, when its counters are emitted, then the audit layer remains the sole owner of tool/outcome counters, preserves post-insert accounting, and duration instrumentation does not increment a second outcome.
8. Focused functional tests falsify duplicate/missing duration samples, cancellation swallowing, and unsafe labels while checking existing outcome ownership. Tests are written and run only by the designated functional-test role after implementation is complete.

### Implementation constraints

- Instrument the framework's actual tool-call middleware/dispatch boundary; do not edit every tool handler independently if a shared boundary exists.
- Use the existing metrics object and reconcile its fixed allowlist against registered tools. Do not create a second metrics registry or persistent store. Add a fixed-key count/sum duration aggregate; do not record tool/outcome counters from the dispatch boundary or retain individual samples.
- Preserve request correlation and existing audit-before/after semantics.
- Keep labels to fixed tool and outcome values. No exception messages are emitted; if diagnostics need exception context, use the exception type only under the existing safe-event contract.
- No migration, deployment, external service call, or production data access is needed.

## Verification and sprint DoD

- Only the named focused functional cases run, after code assembly, by `functional-test-reviewer`; no full suite, lint, typecheck, build, verify script, or CI evidence.
- Python reviewer and code reviewer review the changed files and this story's acceptance criteria; every actionable finding is fixed.
- GPT-PM review is requested once for the sprint at final task, bound to the exact final HEAD. No push/PR before APPROVE.
- The decision log records the implementation choice and explicitly preserves residual production limitations; the lessons log records the outcome.
- The live program report is regenerated using `.harness-tools/report.py` at sprint close.
- S20 may close only as bounded engineering acceptance. D12 production evidence, alert receiver delivery, runtime workload metrics, G6-pre, G6, G7, G8, and production authorization remain independent gates.

## Ordered work

1. Inspect the pinned MCP tool middleware support and select the shared dispatch hook that exposes the registered tool name and result/error without changing transport behavior.
2. Implement S20-01 with minimal source changes and focused tests authored by the designated test role after code is complete.
3. Run only the named tests under the project sequence, then routed code review and GPT-PM exact-head review.
4. Update decision/lesson records and the live report, close S20 if bounded acceptance is approved, and merge only after all required exact-head evidence is green.

## Bounded closeout — 2026-11-20

S20-01 is `ACCEPTED_BOUNDED`, and S20 is `CLOSED_BOUNDED_SPRINT`. GPT-PM approval is bound to source HEAD `282454abcfd0df49687a135bfe28b2086680efd7`; PR #72 merged at `7916d16ed8da13ee0060fbe4072e173ea5d2bf35`. The ledger records the sprint closed and the task verification/review accepted.

Evidence remains limited to the named results in `reports/evidence/sprints/S20_S01_FOCUSED_TESTS.txt`: six final fault-injection selectors passed at `dafd42a186a7919b17048a53d55d687a8429050c` (`0.51s`); at `e0da20d59629e2de179217174dc9796fb68df91c`, the allowlist contract passed (`1 passed in 0.31s`) and focused middleware selectors passed (`12 passed, 27 deselected in 0.61s`). The final source-head code, Python, and silent-failure reviews reported zero findings. The same 14 broad-file failure node IDs reproduced on base and candidate; this comparison does not establish broader attribution. Full suites, checks, and CI were `NOT_RUN`.

This closeout accepts only the bounded observability engineering slice. It does not establish production or runtime readiness, live 1C behavior, alert delivery, workload objectives, G8, pilot, or release authorization. Those remain separate gates.
