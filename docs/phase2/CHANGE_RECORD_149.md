# Change record 149 — inventory S13 mutation paths and correct suffix rule references

## Goal and scope

Complete the repository-side Gate 2 source inventory and reconcile an ambiguous shorthand used for the inherited S12 checkpoint-tail rule. The inventory is limited to source files in the repository; it cannot establish deployed services, effective grants, or operational writer coverage.

## Changes and affected paths

- Added `docs/phase2/S13_MUTATION_AND_WRITER_PATH_INVENTORY_2026-10-17.md` from a read-only `code-explorer` audit of migrations 004–024 and the Python ledger/lifecycle package.
- Updated `docs/phase2/S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md`, `docs/phase2/S13_ACCEPTANCE_MAP_AND_MIGRATION_INVENTORY.md`, and the current S14 row to cite the inherited rule precisely: `S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md` revision 6 §6 (R-04/S12-M01), read with S12 Contract Freeze v2.0 §§3, 5–6.
- The older shorthand “S12 §9” is not used as the normative reference in current acceptance text. The dated CR126 and pre-CR149 S14 snapshots remain historical records.

## Inventory result

- Repository source paths are inventoried by group: core ledger/event chain, registry/evidence/budget/approval, recovery/verification/holds/kill switch, dispatch/receipt/completion, lifecycle migrations, Python adapter, lifecycle coordinator, and synthetic writer.
- `SqlChangeLedger` opens one transaction per SQL API call; the lifecycle writer-epoch check is a separate transaction from any subsequent external call.
- `OneCWritePort` is a protocol; `NonOperationalWritePort` raises `NotWired`; the located writer/coordinator operate on a synthetic test clone. No operational production writer or composition root was found in the reviewed package.
- Therefore the repository-source inventory is complete for the reviewed paths, while deployed writer/service coverage remains `UNKNOWN / NOT_RUN`. This inventory does not close formal S13 or authorize any external action.

## Limits and next action

- No source, tests, migration, database, or gate manifest changed. No tests or database commands were run for this documentation pass.
- The lifecycle fence currently covers selected event/permit/epoch paths and does not span a physical call. A successful `FOR SHARE` lock lasts through the surrounding transaction, and a bounded service transaction lifetime is not demonstrated. This remains a MAJOR pre-activation acceptance dependency.
- Next local engineering step: implement and review a read-only ordered suffix reader/classifier against the exact cited inherited checkpoint rule. The real writer/service boundary, shared fence, bounded transaction lifetime, and external checkpoint/signer qualification remain separate open dependencies.
- Formal S13 remains `NOT_STARTED / NOT_APPROVED`; G1–G8 remain `NOT_PASSED`; R-01/R-03 remain OPEN; Release 2 remains `NO-GO`; production authorization remains `NONE`.

## Ownership

- The operator remains accountable for delegated project closure; GPT/Codex executes local repository work.
- `code-explorer` performed the read-only source inventory. No ownership for an actual deployed writer/service is established in canonical records. Test agents will own future executable scenarios; DB/reliability/security reviewers will review their respective risk surfaces.
