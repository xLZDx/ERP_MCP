# Live task state and reviewed recovery seed

The live task authority remains `.harness/ledger.json`, edited through
`.harness-tools/ledger.py`. The tool resolves the main checkout through the Git
common directory, so linked worktrees share one live ledger. A stale physical
copy in a scratch checkout is not a separate authority.

## Why live state is not tracked

The old tracked ledger changed on every task/commit/approval event. It kept the
main checkout dirty and made exact-head approval self-referential if a receipt
had to be committed into the head it approved. Untracking preserves the file,
its history and current data; it does not reset task status or remove approvals
from the live store. Local harness installation, environments, dependency caches
and report-QA scratch output are ignored as local state, not deleted.

`LEDGER_BASELINE.json` is a committed recovery seed captured from the shared
live ledger. The copy clears only its top-level active approval; historical
receipts/events, task identities, evidence and reconciliation dimensions remain.
It is a dated snapshot, never a current merge authorization. The original104
product-task positions and separate audit/consolidation tasks are preserved.

## Fresh checkout or recovery

Before creating tasks, inspect the main checkout's live ledger. If it exists,
use it; do not overwrite it with the seed or initialize an empty project. If it
is absent, create `.harness` and copy the seed to `.harness/ledger.json` with
overwrite disabled. This restores state; subsequent task edits use the official
ledger CLI. Confirm project identity/task IDs before proceeding. A malformed
existing ledger needs recovery from a preserved copy, not silent replacement.

Run this only from the main checkout, never separately for each worktree:

```powershell
$ledgerSeed = Join-Path $PWD 'docs/rebaseline/LEDGER_BASELINE.json'
$ledgerDestination = Join-Path $PWD '.harness/ledger.json'
if (Test-Path -LiteralPath $ledgerDestination) { throw 'Live ledger already exists; keep it.' }
[IO.Directory]::CreateDirectory((Split-Path $ledgerDestination)) | Out-Null
[IO.File]::Copy($ledgerSeed, $ledgerDestination, $false)
```

## Snapshot and clean-main procedure

At a review/sprint boundary, preserve the live bytes outside Git first. Derive
the seed from those bytes without modifying the live file, and clear the seed's
active approval. Record its source revision/as-of boundary separately; do not
claim a self-referential commit hash. Regenerate the global report from live
state and real Git evidence. New source commits still invalidate exact-head
approval, which the pre-push hook checks against the real PM reply.

When checking out a main revision that removes the old tracked ledger, back up
the live file before Git updates the checkout and restore those exact bytes
afterward. Do this only after test/review workers have stopped changing task
state. Never replace it with a scratch checkout's stale copy. Preserve original
dirty source via reviewed integration manifests and external backups before
any checkout cleanup; do not use reset-hard, clean-force or history rewrite.
