# Change Record 241 — acquire T16 advisory keys before target rows

## What changed

- In candidate `operator_resolve_v1`, moved the bounded `targets ... FOR SHARE` loop and its post-lock target-set comparison to after namespace-4 target-key advisory acquisition.
- Kept the applicable fence ranks before all relation-row locks and retained target-parent-before-record-child ordering.
- Added an exact lock-trace acceptance requirement to `S13-OPERATOR-RESOLVE-01`.

## Why

Source inspection found that the candidate locked target parent rows before acquiring namespace 4. Another path following the accepted advisory-before-row order could hold namespace 4 while waiting for the same target row, producing a source-visible wait cycle. The candidate must acquire all applicable advisory ranks before any relation-row lock.

## Baseline and provenance

- `db/phase2/027_private_writer_admission_schema.sql` was already untracked in the dirty checkout before this edit. A pre-edit content hash was not captured; no baseline hash is asserted.
- Repository HEAD before and after this edit: `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`.
- Exact local patch artifact `docs/commits/.s13-lock-protocol-review.patch` was inspected read-only. Its current file hash is `805CC5CE3E2EF47F7FE850DD6CC841916D74FB771A2AEA0F2AF000CF8ADE0F21`, which differs from the attachment hash shown in the supplied screenshot (`2500FFD7A45A4A53390D8B73FFC3D297F662BC4AC43B0418639D2EF6E461D4C0`). The local patch is not claimed to be byte-identical to that attachment. Its namespace-5 scope-fence proposal is also superseded by the current design, which reserves namespace 5 for sweep locks, namespace 7 for the scope fence, and namespace 8 for the physical-base slot.
- Candidate migration SHA-256 after this edit: `9D66EF9DF75F0A2165263BAC84A00E2F3F50B02B520300D7A00801BE2511C175`.
- Qualification prerequisite SHA-256 after its lock-trace amendment: `E0F8DD093E11DC69DED04D8DC7BEF570F7BBD0B43278C4CC48BCDAE1C2049E2E`.

## Verification state

- Manual source inspection only: the namespace-4 loop now precedes the first target `FOR SHARE`; target rows remain before record rows, and the target snapshot is compared after acquiring the planned parent rows.
- No SQL parser, tests, checks, database operation, migration, COM call, stage, commit, or push ran. Candidate SQL remains unparsed, uninstalled and ungranted; effective grants and runtime lock behavior remain `NOT_VERIFIED` / `NOT_RUN`.
- The exact local patch content was manually reviewed, but attachment identity is unresolved because the hashes differ. The patch is not applied.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Technical owner for the remote writer boundary: Ivan stack. Next: continue source-wide FK/trigger/effect and lock-order closure; after coding closes, delegate the mapped disposable scenarios to the functional/E2E roles and request the relevant database review.
