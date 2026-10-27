# S13 candidate: preflight global IDs before relation rows

## Change

In additive migration 027, moved the caller-allocated `dispatch_receipt_id` collision check in `record_dispatch_receipt_v1` and `verification_id` collision check in `verify_dispatch_payload_v1` to immediately after their sorted namespace-6 ID fences and before acquiring the `records` row lock. The refusal codes remain `RECEIPT_ID_CONFLICT` and `DISPATCH_VERIFICATION_ID_CONFLICT` (`P0001`).

## Why

The S13 global-ID contract requires every caller-supplied or adapter-preallocated globally unique ID to be fenced and checked before relation-row locks or DML. Manual source inspection found both checks below the parent record lock, leaving a source-order inconsistency with that candidate contract.

## Scope and compatibility

- Only the additive, explicitly ungranted migration-027 candidate functions changed.
- The legacy implementations, existing default adapter routes, public MCP/API surface, grants, COM path and data were not changed.
- The candidate schema remains disabled/uninstalled until full lock-map, ACL and disposable qualification gates pass.

## Verification state

- Manual source order inspection only; no SQL parse, test, check, build, CI, migration, database query/write, COM call, stage, commit or push was run.
- Cross-scope ID collision and exact replay qualification remain `NOT_RUN`.
- Effective grants remain `NOT_VERIFIED`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. `database-reviewer` owns later effective-grant and lock-order review; `functional-test-reviewer` and `e2e-runner` own their mapped scenarios after coding completes. Push/PR requires fresh GPT-PM approval for the exact final code head.
