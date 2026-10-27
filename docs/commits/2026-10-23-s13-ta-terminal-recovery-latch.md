# S13-TA terminal recovery and fatal-latch remediation

Date: 2026-10-23. Repository: ERP_MCP (`https://github.com/xLZDx/ERP_MCP.git`).

## Finding and scope

This record addresses the exact-source review request `7a63c4d8-2026-1023-a001-9f02b7c4e1a7`, which returned `REVISE` with two MAJOR findings and one MINOR finding:

- `S13-TA-M01`: after awaited evidence resolution, recovery could persist a receipt or terminal transition without rechecking the fatal `restart_required` latch and exact startup inventory. An unchanged database serving epoch alone does not prove that this Python process remains safe.
- `S13-TA-M02`: the qualification contract described a live no-entry call as `ACCEPTED_NOT_INVOKED` even though the live writer call follows committed `mark_invoking`; it also omitted stale-takeover coverage for `record_recovered_terminal`.
- `S13-TA-m01`: cancellation during the public recovered-no-entry store call escaped without a structured unknown-outcome result.

## Changes

- Added a process-local async terminal-mutation lock in `src/erp_mcp_private_writer/service.py`. Fatal latch changes and terminal/recovery database calls serialize through it. Each store call rechecks active service instance/epoch and, for startup recovery, exact inventory membership while holding the lock through the adapter's bounded call. A latch-first ordering refuses the store call; a store-call-first ordering reaches its return/cleanup boundary before the latch becomes visible. An indeterminate commit remains unknown and requires authoritative lookup. Latch completion is shielded from cancellation.
- Routed live success, recovered success, recovered receipt attachment, recovered no-entry, and entered-conflict terminalization through the serialized authorization helper.
- Mapped cancellation during public recovered-no-entry persistence to `RECOVERY_TERMINALIZATION_UNKNOWN` with `outcome_unknown=true`.
- Updated `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` to model reachable states and cover all three terminal paths, fatal-latch races, and hold/slot preservation.
- Updated the S13 writer design and operator backlog with the review disposition and the explicit in-process versus SQL fencing boundary.

## Verification state

Source and contract changes only. No tests, checks, builds, migration, database write, COM call, service restart, staging, commit or push was performed for this change. The exact-snapshot independent re-review is pending. The candidate SQL routines and S13 runtime grants remain absent from the inspected disposable database; runtime qualification remains `NOT_RUN`.

## Ownership and next step

Operator: accountable task owner. Codex: executor. `functional-test-reviewer` and `e2e-runner`: test design/execution after all in-scope coding is complete. Next: complete the remaining S13 source scope, then run mapped tests and the focused independent review against the resulting exact snapshot.
