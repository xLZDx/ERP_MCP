# ERP_MCP full rebaseline — 2026-11-17

Status: IN_PROGRESS. This is the operator-authorized replacement of the former
FIN-only execution scope, not a declaration that earlier work is unfinished.

## Evidence rules

Reconstruct task states from product source, task criteria, recorded decisions,
test/review evidence and all available Git refs. The previous harness ledger is
an input and its evidence history must be preserved. Source presence establishes
implementation only; acceptance and deployment require their own evidence.
Conflicting records stay explicit until a cited disposition resolves them.

FIN-S1.2 is deferred through final project verification. It is not an immediate
dependency of this rebaseline; no further period-source discovery is scheduled.

## Preservation

The external folder `D:/ERP_MCP_Testbed/rebaseline/2026-11-17` holds:

- `all-refs.bundle`: all Git refs before integration, 41,630,577 bytes;
- `staged.patch`: original index changes;
- `unstaged.patch`: original worktree changes;
- `status.txt`: original untracked/modified path inventory;
- `untracked-project-files.zip`: 1,764 selected untracked project files,
  excluding dependency/worktree directories; 21,702,220 bytes.

These backups may contain private project material and remain outside Git.
They do not capture every ignored file, dependency cache or external runtime.
Existing worktrees are not disposable merely because their age exceeds a day.

`FILE_INVENTORY.json` records hashes/paths for 2,104 source, test, SQL,
documentation and report files and 104 refs, including exclusions. The inventory
is evidence coverage, not a claim that every line has received human review.

## Audit responsibilities

- Architecture reviewer: `ARCHITECTURE_AUDIT.md`, actual entrypoints and boundaries.
- Reporting analyst: `TASK_EVIDENCE_AUDIT.md` and `TASK_EVIDENCE.json`.
- Git explorer: `BRANCH_INTEGRATION_AUDIT.md` and `BRANCH_INVENTORY.json`.
- Coordinator: merge evidence into program plan, preserve old ledger snapshot,
  apply supported statuses through ledger tooling and regenerate the global report.

## Integration and cleanup policy

Remote `main` is the integration baseline; local `main` is stale. Never merge
every branch indiscriminately or replace main with the dirty root checkout.
First classify unique commits and overlapping patch sets, then integrate in
dependency order on a scratch branch based on the fetched remote main.
Resolve conflicts with source-aware review and preserve all commit history.

Every integration candidate requires the normal evidence and GPT-PM approval
for its exact head before push/PR/merge. This rebaseline request authorizes
preparing integration and cleanup; an inventory is not approval of unknown code.

GitHub `delete_branch_on_merge` was changed from false to true and read back as
true. It applies to eligible PR head branches after merging; protected/default
branches are retained. It does not clean old branches or local worktrees.

Local post-merge already invokes `.harness-tools/worktree_gc.py`; that script
only considers merged clean scratch worktrees. Before enabling broader cleanup,
prove remote-main containment, no unique uncommitted work, no running users and
no outward junctions. Always retain main/master; never force-delete unmerged work.

## Ordered delivery

1. Finish architecture, task-evidence and branch audits, recording coverage limits.
2. Produce the reconciled per-task/per-sprint plan and replacement ledger snapshot.
3. Rebuild the global Russian live report from reconciled evidence.
4. Prepare reviewed integration batches and explicit old-branch dispositions.
5. Integrate approved batches into main, then clean only proven merged copies.

Tests/build/lint/CI were not run during inventory. Historical results retain
their original revision and environment limits.


## Independent review and extended coverage

The first independent review found two MAJOR coverage gaps: source blobs were
not enumerated per ref and patch comparison excluded remote-only branches.
Both tools were extended and rerun. CODE_VERSIONS.json now enumerates 2,768
code/config/test path/blob versions; DOCUMENT_VERSIONS.json has 1,846 document
versions across 104 refs (the empty prepared integration branch was subsequently removed).
Patch comparison covers all 103 current local/remote branch refs. Comparison failures
are unavailable/null, never zero unique patches. Full semantic SQL and Python
gateway reviews are still running; RB-01 remains open until their findings are
recorded. No claim of full line-by-line source acceptance is made.


## Snapshot semantics after local audit commit

The baseline package was committed locally as 4318857. ledger.rebaseline.json
and TASK_EVIDENCE.ledger_sha256 describe the source-ledger snapshot at generation;
the active .harness/ledger.json subsequently records audit commits and task-state
bookkeeping. A later active-ledger hash change does not rewrite that historical
snapshot or invalidate its captured source evidence. Before any final status
promotion, generate a new explicitly dated snapshot rather than claim an old
snapshot is permanently byte-identical to the live ledger.
