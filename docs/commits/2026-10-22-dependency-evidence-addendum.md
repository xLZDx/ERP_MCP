# Change record: Reconcile current dependency evidence

## Change

- Added a dated 2026-10-22 addendum to `docs/phase2/artifacts/WP4_WP10_DEPENDENCIES_2026-10-21.md` to supersede its stale WP3 registry count and base revision while preserving the prior dated record.
- Updated the current backlog to link to that addendum.
- Regenerated `governance/DOCUMENT_REGISTRY.md` from committed Git refs with `--exclude-local-only` so the snapshot includes committed navigation sources while leaving untracked local-only files unenumerated.

## Why

The dependency artifact still said 422 tracked paths at an older base revision. A later snapshot recorded 423 paths at `d82cfa4`, and the current generated snapshot records 424 paths at `3b439f2`, alongside SSH, database-binding, and connector observations from 2026-10-22. The addendum makes this evidence timeline explicit without rewriting historical package status.

## Contracts and paths

- WP4–WP10 acceptance dependencies, authorization state, and release gates are unchanged.
- The registry remains a Git-ref navigation aid and explicitly excludes local-only files in this mode.
- No source, database schema, authorization, production, or business-data contract changed.

## Decisions

- Preserve the original dated 2026-10-21 report and append a clearly dated superseding addendum.
- Record live observations as point-in-time only; do not infer remote access or database/business-read success.
- Keep functional acceptance `NOT_RUN`; registry generation is not a test or release gate.

## Verification state

- Registry generation command: `node scripts/build_document_registry.mjs --exclude-local-only`; exit 0, 46 refs, 424 tracked Markdown paths, local-only `NOT_ENUMERATED`, at base HEAD `3b439f2a59c1cb1b8a961b269eae190dceec6083`.
- No tests, generator `--check`, build, CI, migration, business read, or remote command was run for this documentation update.
- Exact diff received read-only GPT-6 Luna `code-reviewer` review at medium effort before commit. The reviewer caught and rechecked a stale 423-versus-424 count in this record; final exact diff was approved with no remaining material findings. No tests/checks were run.

## Lesson

Keep historical dependency records intact and append concise dated addenda when new evidence changes operational observations or counts.
