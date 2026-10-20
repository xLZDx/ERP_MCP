# Change record 115 — extend R-03 post-cutover consumer coverage

## What changed

- Extended `tests/phase2/test_r03_migration019.py` to seed genuine pre-cutover legacy records for the remaining evidence-consuming action wrappers.
- Added no-mutation assertions for `complete_lock_busy`, `verify_signed`, `retry_verify`, `verify_inconclusive`, and `witness_cosign_signed`.
- Added ACL assertions that internal helpers are not directly executable by PUBLIC or application runtime roles and that the wrappers retain their intended grants.

## Why

The first focused R-03 tests exercised the primary completion, unknown-resolution, operator recovery, and permit tenant-isolation paths. The independent database review asked for direct coverage of every remaining wrapper that shares `evidence_ref`, plus explicit helper and wrapper ACL assertions. This follow-up closes that coverage gap without changing production SQL.

## Verification state

- Command: `.venv\\Scripts\\python.exe tests\\phase2\\test_r03_migration019.py` — exit 0.
- Result: `CR101-A..F and R-03-021-consumers` passed with migrations 001–021 applied. Legacy rows were seeded before 015; the added wrappers rejected them with `EVIDENCE_UNSIGNED` and preserved record state, event counts, verification counters/holds, and cosign counts/state.
- Ed25519/legacy write controls, permit tenant isolation, historical audit read, and application adapter path remained green in the same run.
- Worktree code base: `10f89ba97af830d898f9804b96b15f588db30b29` plus this test-only change. Disposable PostgreSQL image digest: `sha256:721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea`; the exact owned container was absent after cleanup.
- The test agent also ran `git diff --check`; it reported clean aside from the repository's CRLF normalization warning. No source SQL changed.

## Review linkage and limits

- Follow-up responds to the database-review coverage note at HEAD `10f89ba`; fresh source review found no BLOCKER/MAJOR.
- Runtime evidence is local and synthetic. This does not establish deployed key custody, formal R-03 closure, gate passage, or production authorization.

## Affected paths

- `tests/phase2/test_r03_migration019.py`
- `docs/phase2/CHANGE_RECORD_115.md`
