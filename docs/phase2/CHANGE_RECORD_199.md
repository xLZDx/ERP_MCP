# Change Record 199 — bounded-batch document registry generation

## What changed

- Replaced one `git cat-file blob` child process per unique tracked Markdown object with bounded `--batch-check` metadata reads and byte-limited `git cat-file --batch` content reads.
- Preserved exact object ID/type validation, whole-blob first-heading extraction, UTF-8 decoding, and failure on incomplete or malformed output. Registry replacement still occurs only after inventory completes.

## Why

The existing registry generator had to scan every local and remote branch and launch a child process for every distinct Markdown blob. On this repository that made required documentation regeneration take an impractical amount of time. A byte ceiling, rather than only a document-count limit, keeps aggregate child output bounded while reducing process startup overhead.

## Evidence and verification state

- `scripts/build_document_registry.mjs` SHA-256: `217B372F8B9323977864E4C5D095BE818E6463A29BA8A97CBF4F80F5370B5DA2`.
- The generator completed with exit code 0 and reported 46 scanned refs, 459 tracked Markdown paths, and 110 local-only Markdown paths. The exact ref names and commit IDs are in the generated registry's “Scanned refs” section.
- The latest registry generation has SHA-256 `AC39AD4454D77CD460A846CE4F24611E1D8127D09A5A127398D0A0392A70F815` and includes the current local-only Markdown inventory.
- Tests, checks, build, CI, migrations, staging, commit, and push were not run.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: resume WP5/S13 source coding. No test or qualification result is claimed.
