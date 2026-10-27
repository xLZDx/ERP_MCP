# Remove stale WP3 line-hash exceptions — 2026-10-22

## Change

Removed the exact-line Cyrillic exceptions for `docs/COMPATIBILITY.md` and
`docs/INTEGRATION.md` from `governance/ENGLISH_POLICY_ALLOWLIST.json`.

## Why

The two documents were previously reviewed and translated around their literal 1C terms. A
read-only in-memory hash inventory of their current tracked working copies found zero Cyrillic
lines in either file, while the allowlist still contained one now-unmatched line hash per path.
The stale entries no longer preserve a live technical identifier and only cause stale-exception
noise.

## Contracts and boundaries

- The change removes two exact line hashes; it adds no path-wide exemption and changes no scanner
  behavior.
- No document text, localized report, semantic/test value, source-derived evidence, or binary
  artifact was changed.
- The allowlist remains exact-line based for other documented literal 1C exceptions.

## Verification state

- Read-only inventory: both named files contain zero current Cyrillic lines; each had one stale
  allowlist hash.
- The English-policy scanner and its tests have not been rerun after this change. Final WP3 scanner
  qualification remains pending with the designated functional-test-reviewer role.
- No tests, checks, builds, migrations, database calls, or service actions were run.

## Next step

After all WP3 prose and exact exceptions are resolved, have the functional-test-reviewer run the
English-policy scanner and its mapped acceptance test. Continue preserving localized reports and
literal 1C identifiers; do not widen exceptions to mixed directories.

Accountable task owner: operator. Executor: Codex. Required verification owner:
functional-test-reviewer.
