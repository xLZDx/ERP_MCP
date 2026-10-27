# Change Record 242 — align T16 qualification with checkpoint continuation

## What changed

- Clarified that `operator_resolve_v1` leaves the call-ownership hold open and creates stop-effects anchor holds in its database transaction.
- Specified that a separate post-commit exact checkpoint write/read-back precedes hold release and physical-effect admission.
- Corrected retry expectations: exact terminal replay returns the stored result lookup-only with no row/event delta; a changed evidence tuple refuses with no delta.

## Why

The candidate deliberately separates SQL terminalization from external checkpoint I/O. The earlier qualification shorthand implied that the database call closed the hold before checkpoint proof and that any terminal retry must refuse, contradicting the source's fail-closed continuation and exact replay contract. The qualification must verify the real two-transaction boundary.

## Evidence and provenance

- Candidate source: `db/phase2/027_private_writer_admission_schema.sql`, `operator_resolve_v1` exact event replay and `CALL_OWNERSHIP`/`ANCHOR_GAP` behavior.
- Existing design: `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`, “T16 post-commit checkpoint boundary”; the source candidate remains uninstalled and ungranted.
- Qualification prerequisite SHA-256 after clarification: `F25C85A64C566EFE59CF57F4BFD3FAFDCBFC58B5C9CEDE953808E9F4A716C0D1`.
- Candidate migration SHA-256: `9D66EF9DF75F0A2165263BAC84A00E2F3F50B02B520300D7A00801BE2511C175`.
- Repository HEAD: `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`.

## Verification state

- Manual source/contract comparison only. No test, check, SQL parser, migration, database operation, COM call, stage, commit, or push ran.
- `S13-OPERATOR-RESOLVE-01` remains `NOT_RUN`; installed grants and runtime behavior remain `NOT_VERIFIED`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue coding and source-wide lock/FK/trigger/effect closure. After code completion, functional/E2E roles qualify the exact split between terminalization, checkpoint read-back, hold release, and exact retry.
