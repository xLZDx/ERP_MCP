# Rebaseline and main consolidation closeout

Published baseline snapshot: local/main and origin/main
`3667b0e90eb91301a3260b748c857d635cbb6bd8`, after PR59 merged at
2026-11-17T18:32:12Z. This is the actual published integration baseline, not a
self-referential claim about a later documentation commit.

## Acceptance and corrected task count

Original104 task positions,12 historical sprint-level outcome records and S11's
zero-story milestone remain distinct. The initial audit preserved48 bounded
task acceptances. Restored R2US002_BOUNDED_ACCEPTANCE.yaml supplies one more
explicit whole-story acceptance: current49/104 bounded. Evidence SHA256
81dcbc02cc2c6cfcfab4f8bd8c99bbe188f2cc490d03a9b448f4138d469ba64c and receipt
28695ca2247bb5c3b2d3d73548a93c85b33ce1673eef152531bfc7a2732ed09e match its
original YAML. Request9550946b-a01e-4148-86c0-79db24d9e591 accepts TC004..006 and
the bounded story at c624b701. Canonical product cases remain NOT_RUN; private
test-only reuse does not authorize redistribution or production inclusion.

MC-01..04 engineering consolidation is separately accepted. Source inventories,
dispositions, architecture review and named qualification receipts retain their
dated coverage limits. Overlapping test counts are never summed. The review was
risk-focused, not an assertion that every line of every file was verified.

## Approval and integration

Full application/test review request6f806abc-03da-40a9-9aa4-7627458839ae returned
APPROVE for561256d73341838e86edf4e5ce512a4fd66f0747, reply
12abd506-4a27-5bbd-93f6-918e3d78a5c0. The official ledger rejected EXACT HEAD
wording; a real format-only confirmation f4b5b96e-11ab-4305-b1e0-c265c64bc9c9,
reply8c045fe0-e0d2-5b26-8f96-e7ca4e712a12, supplied HEAD and was accepted. No
guard was disabled and no approval was synthesized. The push guard passed.

PR59 head matched561256d. Merge used match-head-commit; the next GitHub read
returned MERGED and autoMergeRequest=null. Main fast-forwarded normally to3667b0e
and had empty working status and0/0 upstream divergence before this closeout.
No reset-hard, clean-force, force-push, production deployment or 1C write occurred.

## Preservation and cleanup

External backups under D:/ERP_MCP_Testbed/rebaseline/2026-11-17 retain all-ref
bundles, binary index/worktree patches, original untracked inputs and linked dirty
source. Additional root-before-main-561256d/working-inputs.zip preserved2196 files,
SHA25661ac7104ff7c38e30c43711d8d8a0635b36f807b31b490e58082dc3ec8b23617.
The original root input stash is private local recovery only, never pushed or
included in a later all-ref publication. It also contains local environment
caches: future private untracked backups must stay outside Git. No credential
value was printed or published.

The approved shared live ledger was restored byte-for-byte around removal of its
formerly tracked path; SHA256
02d15e3ff602e701c2a251cb20fd9284d4fea791d53081bdcd2940b1f33004dc matched.
The committed seed omits active approval and never overwrites existing live data.

Removed merged scratch copies:

- D:/tmp/scratch_worktrees/erp-main-consolidation-20261117 and its local branch
  codex/main-consolidation-20261117, with normal branch -d.
- D:/tmp/scratch_worktrees/erp-mcp-fin-s31-e30e2ec: its sole dirty conformance
  file matched merged main after LF normalization, was separately preserved,
  and its local delta was cleared before removal.

Both heads were ancestors of origin/main; no unignored changes remained and no
reparse points were found. Accessible process inspection found no target cwd;
command-line matches were only the inspection's own root processes.199 denied
system processes were not claimed inspected. Windows removal succeeded rather
than bypassing a busy-folder error. Authorized forced worktree removal discarded
only ignored scratch outputs after those checks. The unmerged PR58 scratch and
other unique/dirty worktrees remain retained. CLEANUP_MANIFEST.json is a dated
preparation inventory, not permission to force-delete unmerged history.

GitHub deleteBranchOnMerge=true was observed; PR59's remote branch is absent
without an agent remote-delete command. Future merged PR branches are deleted
remotely by GitHub; local cleanup follows preservation, merge, process and link
checks. No periodic automation was added.

## Remaining original program

Engineering integration does not accept production release, READY/shared writer
admission, external-provider trust, service-account custody, full startup recovery
or native1C/COM. FIN remains in final review and S13 partial; later planned work
does not restart accepted stories. The next pass reconciles remaining FIN evidence
against merged code, then follows original S0/S13 dependencies.

FIN-S1.2 stays deferred until final project verification. Live ERP MCP starts and
credential investigation are deferred by the latest operator instruction. No
prohibited suite/build/lint/CI supplies acceptance evidence.
