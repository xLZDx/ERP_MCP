# Change record: Preserve Cyrillic in current document-registry titles

## Summary

Update `scripts/build_document_registry.mjs` so Cyrillic is escaped only for heading variants
found exclusively on refs whose path includes an `archive`, `rescue`, or `snapshot` segment.
Current headings, file paths, and ref names remain readable. The generator tracks the refs for
each distinct heading variant and makes the escape decision per variant, rather than per path.

## Reason

The operator's WP3 instruction is to retain the Cyrillic escape only for historical headings.
Applying it to paths, ref names, or current headings obscures useful repository metadata; removing
it everywhere would lose the historical output policy. Variant-level provenance makes the rule
explicit when a title changes across refs.

## Affected contracts and paths

- `scripts/build_document_registry.mjs` — classify historical refs by path segment, retain each
  title variant's ref set, escape only historical-only Cyrillic title variants, and describe the
  partial escape policy in generated output.
- `governance/DOCUMENT_REGISTRY.md` — generated output must be regenerated after the script and
  intended ref snapshot are fixed; this file is not hand-edited.
- `core/LESSONS_LOG.md` — record that generated output depends on ref history and escape policy
  must be applied to title variants, not indiscriminately to paths or ref names.

## Decisions and boundaries

- A ref is historical when a path segment is exactly `archive`, `rescue`, or `snapshot`.
- A title variant is escaped only when every ref containing that exact variant is historical.
- If the same variant appears on any non-historical ref, keep it readable.
- Do not inventory local-only untracked Markdown; use the documented `--exclude-local-only`
  generation mode so unrelated untracked files such as `MCP-RSV-Data.zip` stay outside the
  generated snapshot.
- Do not hand-edit generated registry content or expose source/business values while reviewing
  broad historical documentation.

## Verification state

- A read-only `code-reviewer` pass examined the generator diff and reported no material finding
  about variant tracking or deterministic ordering.
- Ran `node scripts/build_document_registry.mjs --exclude-local-only` after the prompt bundle and
  S13 documentation commits. The generator exited with code 0 and reported 436 tracked paths,
  46 scanned refs, and `local-only NOT_ENUMERATED`; the recorded current branch ref was
  `dd932427fdab2eed625cd320ecbcf5ffdd203ee0`. The registry is a point-in-time snapshot of those
  committed refs, before this change's own commit.
- Tests, checks, builds, CI, and migrations are not run during the coding phase.
