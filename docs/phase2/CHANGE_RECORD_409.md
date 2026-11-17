# Change Record 409 - Preserve the apply-time epoch refusal

Sprint: beea27520b33

## Trigger and behavior

The functional-test-reviewer reported a failing acceptance test after proposal and
valid approval: advancing the requester's registry epoch caused apply to return
`NOT_ENTITLED`. The generic requester-liveness helper checked epoch before the
dedicated ordered apply-time epoch guard could return `EPOCH_CHANGED`.

`src/erp_mcp_s16/core.py` now defers epoch equality only during apply's initial
identity/role/expiry check. Its later epoch guard compares the current registry
epoch to both the authenticated requester token epoch and the proposal epoch,
plus existing dependency checks. Other operations keep the strict default helper.
No stale token is admitted to the apply port; refusal classification follows the
S16 contract and the existing kill/fingerprint/epoch guard ordering.

## Verification and provenance

The primary agent applied this source fix after the test agent reported the
failure; the test assertion is preserved. The reported run before the fix was
31 passed and 2 failed, including one fixture enum error. That is inherited agent
evidence, not a green result or primary-run test. Post-fix execution belongs to the
functional-test-reviewer; no primary-session tests were run.

Only this source path and the dedicated logs/record are included in this fix.
Pre-existing changes, uncommitted test work and concurrent E2E artifacts are
preserved. No approval, push, deployment or production operation is performed.
