# Change record 097 — clarify registry snapshot counts

## What changed

- Clarified in `CHANGE_RECORD_096.md` that its 158 tracked / 0 local-only counts describe the generator output at the recorded generation time.
- Documented separately that the current checked-in registry snapshot reports 158 tracked paths and 1 local-only path, the self-referential `CHANGE_RECORD_096.md` entry.

## Why

The historical generator result and the later checked-in registry snapshot are distinct states. Clarifying that distinction prevents the historical zero-local-only count from being read as the current registry count.

## Decisions and scope

- Did not regenerate `governance/DOCUMENT_REGISTRY.md`: the registry is navigation, and adding this clarification as a registry entry would create a self-referential update chain without improving navigation.
- Documentation-only change; no source code, tests, database state, formal gate, release authorization, or production state changed.
- Preserved the unrelated untracked `.claude/` directory.

## Review and verification state

- Confirmed before editing that local `HEAD` and `origin/main` both pointed to `2c1fa83ecf3712811c0a6affdc8a4b66d467ca52`.
- Manually reconciled the two count statements against `CHANGE_RECORD_096.md` and the checked-in `governance/DOCUMENT_REGISTRY.md` snapshot.
- No tests, builds, lint, CI, migrations, database operations, or push were run.

## Contracts and paths

- `docs/phase2/CHANGE_RECORD_096.md`
- `docs/phase2/CHANGE_RECORD_097.md`
- `governance/DOCUMENT_REGISTRY.md` (read-only reference)

## Acceptance

- Historical generation counts and current checked-in snapshot counts are explicitly distinguished.
- The current registry is not described as having 0 local-only paths.
- No registry regeneration or push is performed.
