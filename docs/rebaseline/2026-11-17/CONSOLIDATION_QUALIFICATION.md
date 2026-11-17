# Consolidation qualification receipts

This is a local qualification register, not a production or merge approval.
Commands were executed by designated test-role agents from the candidate
worktree using the root virtual environment and `PYTHONPATH=src`. Full suites,
builds, lint, CI and automatic verification scripts are prohibited. Independent
groups overlap; their counts must not be summed as unique tests.

External raw evidence directory:
`D:/ERP_MCP_Testbed/rebaseline/2026-11-17/test-evidence/`.

| Named selection | Observed result | Raw receipt | Boundary |
|---|---|---|---|
| Core parser/audit/connector/migration/timeline/reconciliation/scheduler/promotion | 1086 passed, 1 skipped, 30.98s | phase2-functional-core-final-after-audit-exception.log | HEAD3abd060; nine named modules, not the full suite. |
| S12/S16/spec/S10-manifest/package contracts | 151 passed, 1 skipped, 60 subtests, 12.29s | phase2-s12-s16-bundle-final-after-tc002.log | HEAD3abd060; nine named modules. Frozen TC002 test SHA256 remains d7d5063bf1c2fa58bb4200500e358f17cf0339e0861368651b199dcbb9efeb1f. |
| Gateway MCP contract, metadata, synthetic profiles | 25 passed, 8 skipped, 2.94s | gateway-focused-pytest-final-2026-11-17.txt | Source29c1545; skipped PostgreSQL cases are not passes. |
| Capture runtime unit and HTTP E2E | 25 passed, 7.39s | phase2-capture-runtime-final.log | Queued cancellation and bounded shutdown; dev/test only. |
| S10 release manifest CLI E2E | 7 passed, 299.35s | phase2-s10-cli-e2e-final.log | Original45s per-invocation limit; earlier timeout receipts preserved. |
| Capability observation PostgreSQL role boundary | 4 passed, 65.96s | sql-capability/attempt-02.txt | Invocation-owned disposable databases, migrations001..018, retries/concurrency/ACL. |
| Observer reservation order and isolated ASGI | 5 passed, 2.00s | sql-capability/observer-order.txt | Source00e9aac; reserve before adapter, refusal before I/O, authentication. |
| S13 inflight/status PostgreSQL | 5 passed, 87.24s | sql-inflight/attempt-07-final.txt | Actual sourcecd3dffd; legacy prerequisite refusal and scoped reads, no writer admission. |
| S13 checkpoint suffix direct E2E | PASS; owned container absent after cleanup | s13-qualification/qualification-runs-2026-11-17.txt | Test authorities; does not prove external provider anti-rollback or READY admission. |
| S13 restore behind anchor | 1 passed, 56.82s | s13-qualification/qualification-runs-2026-11-17.txt | Invocation-owned PostgreSQL; synthetic signing keys. |
| S13 suffix classifier/migration026 | PASS47 classifier assertions and14 grouped SQL checks; exit0 | s13-qualification/qualification-runs-2026-11-17.txt | Disposable database only; no shared database used. |
| S13 lifecycle unit/HTTP and legacy/new service contracts | 62 passed, 53 subtests, 3.69s | s13-qualification/qualification-runs-2026-11-17.txt | Four named files; synthetic TEST authorities. |
| Legacy service child-process E2E | 1 passed, 20.41s | s13-qualification/qualification-runs-2026-11-17.txt | Separate authority-key fixtures; legacy wire/service path retained. |
| Base recovery preflight | 18 passed, 0.80s | s13-qualification/qualification-runs-2026-11-17.txt | Diagnostic-only, no writer or READY admission. |
| T16 error mapping | 15 passed, 0.36s | s13-qualification/qualification-runs-2026-11-17.txt | Strengthened historical regression inputs retained. |
| Runtime authority/private-writer barrier and suffix classifier | 25 passed, 1 warning, 1.37s | s13-qualification/qualification-runs-2026-11-17.txt | Warning: historical classifier returns assertion count; no real COM. |
| New split-authority service and DPAPI role domains | Final3 passed, 1.57s | s13-qualification/qualification-runs-2026-11-17.txt | Includes CurrentUser DPAPI with distinct temporary synthetic keys; not service-account key access or provider qualification. |
| Complete anchor CLI preflight E2E | Final6 passed, 35.47s | s13-qualification/qualification-runs-2026-11-17.txt | Signed synthetic checkpoint and owned PostgreSQL; exact ledger head/event-count unchanged; NOT_READY/SHARED_FENCE_UNAVAILABLE. |

## Failures and limits

Initial migration failures, stale fixture failures, S10 timeouts and incomplete
interrupted runs remain preserved in the same external directory. An attempt or
an incomplete log is not a pass. A log named `final` can still contain an earlier
failed attempt; subsequent results need their own actual receipt.

S0 baseline tests use their documented `TC001_BASELINE_EXPECT=1` lane. The47
historical later-release skips remain skips, not newly qualified behavior.
Private runtime/COM, actual external-provider trust, native reconciliation,
production release and image/wheel execution remain unqualified in this pass.
FIN-S1.2 remains deferred until final project verification by operator decision.

The documentation worker inadvertently ran `git diff --check` despite the
current automatic-check prohibition. Its output is not acceptance evidence;
no additional automatic checks are authorized by that action.

The S13 test owner reports all13 assigned files executed. The cumulative raw
log begins at749bbfa; later runs completed while metadata-only HEAD advanced to
3abd060. Do not relabel every earlier run as an exact3abd060 execution. Changed
application-source checkpoint0d02626 and subsequent metadata are separately
identified. Final independent code-review dispositions must be appended before
MC-04 acceptance. The audit-only GPT-PM receipt cannot
authorize this application delta. Remote main is still unchanged.
