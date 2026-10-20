# Change record 116 — close R-03 ACL coverage follow-up

## What changed

- Extended `tests/phase2/test_r03_migration019.py` to verify that each tested action wrapper denies `EXECUTE` to every runtime role other than its intended role.
- Added explicit checks that the raw internal mutators `complete`, `resolve_unknown`, `verify`, and `witness_cosign` are not executable by PUBLIC or any of the seven runtime roles.

## Why

The fresh database review of commit `835ba9b` confirmed the legacy-consumer coverage and identified this remaining least-privilege ACL assertion gap. The update is test-only and leaves SQL unchanged.

## Verification state

- Command: `.venv\\Scripts\\python.exe tests\\phase2\\test_r03_migration019.py` — exit 0.
- Result: `CR101-A..F and R-03-021-consumers` passed with migrations 001–021 applied. Container `r2-s13-dump-c757aa63b653-a` used PostgreSQL image digest `sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea`; exact-name post-run inspection found no container.
- The test agent ran `git diff --check`; it reported clean apart from the repository's CRLF normalization warning. No source SQL was changed.

## Review linkage and limits

- This closes the specific database-review follow-up from HEAD `835ba9b`; a fresh read-only confirmation is requested.
- Evidence remains local and synthetic. Formal R-03, G1–G8, S13, Release 2, and production authorization states are unchanged.

## Affected paths

- `tests/phase2/test_r03_migration019.py`
- `docs/phase2/CHANGE_RECORD_116.md`
