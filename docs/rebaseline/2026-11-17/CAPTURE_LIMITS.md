# Evidence capture and acceptance limits

The completed inventory run 2c1e6f82-04e8-475b-b0ac-7f1fc2b87e32 freezes Git object IDs against main 7c1f69cf51b16d3849772fdb1e32015b17cb1aa7. Both run manifests are COMPLETE and bind output file hashes. It enumerates 2,150 current files, 104 refs, 3,461 document path/blob versions and 2,770 code/config/test path/blob versions. Detailed comparisons cover 103 branch refs and 47 worktrees; 19 worktrees have tracked or untracked changes.

Working-tree reads are sequential, not an atomic filesystem snapshot. COMPLETE means collection finished for the pinned Git baseline; it does not assert that files stayed unchanged during capture. Later bookkeeping commits and report regeneration do not retroactively change this dated snapshot. Recheck exact candidate bytes and branch tips before integration or removal.

The static audit inventories historical versions; it does not claim semantic line-by-line review of every historical version. Subsystem audit files identify inspected implementations, concrete findings and remaining qualification. Historical acceptance is preserved with its revision and scope; source presence, bounded acceptance, merge reachability and live qualification remain distinct.

The original program denominator is 104 tasks. Its 48 bounded acceptances are separate from three new audit tasks and the S11 sprint-level milestone. Native harness receipts are retained rather than invented from historical prose. The frozen ledger snapshot is an evidence source, not a promise of byte equality with the evolving live ledger.

No full ERP test suite, CI, build, lint, migration or runtime qualification was executed. The isolated eight-test contract suite covers audit tooling only. Dirty application work remains preserved and unmerged. FIN-S1.2 is deferred until final project verification and is not a dependency of this audit.

Evidence readers must coordinate through the same permanent OS-backed guard. Raw JSON inspection is a dated snapshot inspection, not proof that another run is absent. See AUDIT_RUN_RECOVERY.md.

A new published attempt begins at atomic replacement of its IN_PROGRESS manifest. Termination before that publication can retain the previous valid COMPLETE snapshot; it is still the prior run ID, not evidence that the new invocation succeeded. This contract accepts dated snapshots and does not promise acquisition-time invalidation before atomic publication.
