# Change record: Safe Git-ref-only document registry generation

## Change

- Added the opt-in `--exclude-local-only` mode to `scripts/build_document_registry.mjs`.
- In this mode, the generator inventories committed Markdown from the captured local and remote Git refs but skips enumeration of untracked files in every attached worktree. The generated scope explicitly says local-only files were not inventoried.
- Preserved the registry's Cyrillic `\uXXXX` escaping for titles, paths, and ref names.
- Regenerated `governance/DOCUMENT_REGISTRY.md` in the new mode and recorded the WP3 policy and evidence in `docs/phase2/artifacts/WP4_WP10_DEPENDENCIES_2026-10-21.md`.

## Why

The default generator inventories untracked Markdown paths in attached worktrees. This worktree contains protected user documents that must not be published in the registry. The opt-in mode preserves the default contract, retains historical and current documents found through Git refs, and offers a tracked-refs-only snapshot without inspecting local untracked Markdown.

## Contracts and paths

- `scripts/build_document_registry.mjs`: accepted arguments are `--check` and `--exclude-local-only`; unsupported arguments fail explicitly. The default local-only inventory behavior is unchanged.
- `governance/DOCUMENT_REGISTRY.md`: generated point-in-time inventory with local-only worktree paths explicitly excluded.
- `docs/phase2/artifacts/WP4_WP10_DEPENDENCIES_2026-10-21.md`: WP3 decision and current evidence.

## Decisions

- Keep local-only path inventory as the default behavior for compatibility.
- Use `--exclude-local-only` for this generation; do not enumerate or publish protected untracked paths.
- Retain all Git-ref documents and their titles; this mode does not exclude historical Git refs.
- Preserve Cyrillic escaping in rendered titles, paths, and ref names.
- Do not treat registry generation as release evidence.

## Verification state

- Generator command: `node scripts/build_document_registry.mjs --exclude-local-only`; exit 0.
- Output recorded: 46 refs scanned; 422 distinct tracked Markdown paths; local-only count `NOT_ENUMERATED`. The generated scope states that local-only files in attached worktrees were not inventoried.
- Cyrillic output uses `\uXXXX` escapes, preserving the prior registry representation.
- Functional tests and `--check` were **NOT_RUN** under the current project no-tests/checks restriction. The new argument mode therefore has generation evidence but not independent functional acceptance.
- Manual review confirmed the protected untracked documents remain outside the generated inventory. They were not read or modified. The unrelated untracked zip was not read or modified.
- No database, service, source, business data, remote system, or external account was changed.

## Review

- `code-reviewer`, GPT-6 Luna, medium effort, reviewed the exact generator, registry, dependency artifact, and change record at base HEAD `33f76b7f4f49ae773b3f86876940c9c6234a636d`.
- Initial findings on Cyrillic output compatibility and supplementary escape formatting were fixed. The final review approved the implementation with no material findings; its remaining wording note was to name ref names in the escaping sentence, which is included in this revision.
- Final exact-file re-review confirmed the output summary uses `local-only NOT_ENUMERATED`, the scope and section agree, and all Cyrillic cells are escaped. No material findings remained.
- Review was documentation/code inspection only; no tests or checks were run by the reviewer.

## Lesson

Generated inventories should declare which inputs were intentionally excluded. An opt-in omission mode can protect local-only paths while preserving the broader default inventory contract.
