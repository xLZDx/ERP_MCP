# Change record 141 — design an interim cap for S13 lifecycle activation

## Goal and scope

Turn CR130's three reliability MAJORs into a bounded, fail-closed local implementation scope without pretending the repository has a complete startup/restore coordinator or physical writer fence.

## Changes and affected paths

- Added an interim-hardening design section to `S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md`.
- Chosen design: make `lifecycle_begin_recovery` unavailable to application roles and unconditionally refusing, bound lifecycle trigger lock waits to five seconds while preserving shorter caller settings, and leave all persisted state untouched.
- Explicitly retained physical writer overlap as an open acceptance item. Migration 023 will not mark calls finished, clear an existing `RECOVERING` state, add an unverified in-flight counter, or return READY.
- Recorded additive migration and rollback boundaries: do not edit migration 022 or reset existing lifecycle rows.
- Regenerated `governance/DOCUMENT_REGISTRY.md` with `node scripts/build_document_registry.mjs`; it scanned four refs and reported 208 tracked paths and one local-only Markdown path at generation time.

## Verification and limitations

- This is a design/document update based on CR130 and the existing migration 022 functions/triggers. No source SQL has been changed yet. The generator completed with exit code 0.
- No tests, builds, database operations, migrations, or runtime checks were performed.
- This design is local preparatory work and does not close formal S13, G1–G8, or Release 2. Existing `RECOVERING` rows would remain fail-closed and require a separately reviewed recovery procedure.

## Ownership and next action

- The operator remains accountable for delegated closure; GPT/Codex executes local implementation.
- Next: implement the additive migration 023 exactly within this safety cap. After all local code is complete, `functional-test-reviewer` and `e2e-runner` own disposable database tests; database/reliability/security reviewers review the exact tested migration and trigger behavior.
- No shared/live migration activation is authorized. Fresh exact-head GPT-PM approval remains the push gate.
