# Change record 117 — record reliability follow-up and refresh the document registry

## What changed

- Recorded the reliability review's nonblocking S13 nonce/record lock-order concern in the S13 design backlog.
- Regenerated the document registry after the R-03 consumer, ACL, and S13 runtime evidence records were committed.
- Reconciled CR111/CR114 registry status with the final generated inventory.

## Why

The review found no correctness blocker: a deadlock aborts one transaction and cannot commit an OFF transition. Recording the lock-order follow-up preserves the improvement opportunity without delaying closure. The registry refresh makes the committed local evidence discoverable.

## Verification state

- `node scripts/build_document_registry.mjs`: exit 0; scanned 4 refs and wrote 179 tracked paths, with no local-only paths.
- No tests, database commands, or migrations are part of this documentation change.
- Reliability review at HEAD `10f89ba` was read-only and classified the nonce/record lock-order inversion as MINOR/INFO.
- DB review at HEAD `bc402f2` confirmed the R-03 legacy-consumer and ACL coverage gap is closed by the focused tests; it ran no tests or database commands.

## Affected paths

- `docs/phase2/S13_KILL_SWITCH_RECOVERY_DESIGN.md`
- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/CHANGE_RECORD_111.md`
- `docs/phase2/CHANGE_RECORD_114.md`
- `docs/phase2/CHANGE_RECORD_117.md`
