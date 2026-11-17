# Main candidate source reconciliation

Source checkpoint: `0d02626b7b0e620b3443ad3357bee10701c5fba9` on
`codex/main-consolidation-20261117`. This is a local candidate snapshot, not a
published baseline, runtime qualification or merge approval.

## Preservation and coverage

- The candidate starts from remote main `7c1f69c` and normally merges preserved
  root history `c8f986b`; no history rewrite or blanket ours merge was used.
- `CANDIDATE_INPUTS.json` enumerates 110 imported dirty paths and their hashes.
  The original checkout and other dirty worktrees remain intact. Generated
  evidence/local SQL outside promotion is explicitly listed, not discarded.
- `CANDIDATE_REF_RECONCILIATION.json` records the dated 103-ref comparison.
  `UNIQUE_COMMIT_DISPOSITIONS.json` inventories 180 unique non-merge commits:
  77 source candidates, 70 historical documentation/evidence records and 33
  test alternatives. Classification alone is not acceptance.
- The first 28 source candidates were reviewed by feature during assembly;
  the remaining 49 have individual dispositions in
  `REMAINING_SOURCE_COMMIT_REVIEW_FINAL.json`. It combines the preliminary A
  record with the corresponding later B rows, which take precedence.
- Residual source dispositions: 43 ported, two ported with adaptation, one
  present, three superseded. Each retains its evidence and verification tail.
  Historical renderer/lint alternatives are not instructions to run checks.

The per-commit dispositions are feature-level reconciliation, not proof of every
historical predicate. Subsequent named tests found missing S10 ownership,
queued-call cancellation and lifecycle branches in initially ported features.
Their source repairs are retained in commits through the checkpoint above;
original failed runs remain in the external evidence archive. No disposition
alone upgrades a task to accepted or establishes behavioral equivalence.

## Cumulative source changes

The candidate retains current source-version and credential checks while
restoring additive MCP signatures, metadata-only schema detail, explicit test
profile provenance, S12 proposal/effect evidence, S13 diagnostic anchor and
database identity/recovery interfaces, and general capture/audit/reconciliation
safeguards. The design contract explains boundaries and acceptance cases.

Published phase2 migration027 is restored from pinned main. Cumulative function
changes and historical version collisions are ported as030..039; current028/029
remain canonical. A budget snapshot already in029 is not duplicated, and its
richer operator status projection is retained. No migration was applied during
source assembly. Capability reservation ordering is a separate forward gateway
migration018, preserving016/017 and separating observer/acceptor authority.

The default gateway package/image source inventory includes gateway and S15,
excluding the private writer and S16 package roots. That is source/configuration
evidence; no wheel/image was built. The newer anchor server has a distinct
`dev_anchor_service_s13` package so it cannot shadow the legacy module.

Source reading and independent design review caught concrete defects before
qualification: mutable probe start ordering, invalid source field use, premature
authorization audit, missing authority signer roles, lost fixed error redaction,
dependency-pin mismatch and reset preflight omission. Their repairs are recorded
in the decision/lesson logs. This is not a claim that no further defect exists.

## Qualification and promotion remain separate

MC-04 has begun named functional and disposable SQL qualification on the
assembled source. Test-role results, failure classification and source fixes
must be recorded independently of historical receipts. Full suites, lint,
automatic checks, CI and builds remain prohibited. Real 1C/native/COM and
production acceptance are not inferred from offline or disposable passes.

Disposable qualification exposed two concrete migration defects: unregistered
legacy028/029 patches were incorrectly treated as registered dependencies, and
030 attempted to recreate existing027 function signatures. The new chain now
requires the actual registered predecessors and legacy schema predicates, uses
CREATE OR REPLACE for the existing signatures, and refuses atomically if legacy
prerequisites are absent. This changed030..039 only; published028/029 stay intact.

Current receipts are collected in `CONSOLIDATION_QUALIFICATION.md`; overlapping
test groups are not added into a fabricated unique-test total. Missing runtime
or provider qualification remains explicit. The source-only package exclusion
test does not substitute for a prohibited wheel/image build.

After tests and applicable independent review, a full-candidate GPT-PM APPROVE
bound to the exact final HEAD is required before push/PR/merge. The earlier
audit-tools approval cannot authorize this application delta. Main is unchanged
until the approved candidate is merged. Cleanup only follows verified merge
and preservation checks; unmerged alternatives retain their history. FIN-S1.2
remains deferred until final project verification, not a current dependency.
