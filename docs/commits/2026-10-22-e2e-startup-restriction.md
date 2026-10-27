# Change record: Record E2E startup restriction

## Change

- Added a note to `docs/phase2/OPERATOR_BACKLOG.md` that the disposable E2E Compose project requires generated secret variables and its documented startup command performs migrations and database seeding before starting host processes.
- Recorded that the command was not run and no services were started in this continuation.

## Why

The autonomous task includes environment startup, but the current project instructions prohibit migrations and test-lane execution. `compose.e2e.yml` requires generated passwords; the documented startup lifecycle creates them and then combines database startup with migrations, seeding and process startup. The reviewed instructions expose no supported database-only path, so invoking Compose directly would bypass the documented lifecycle.

## Contracts and paths

- Documentation only; no service, database, gate, manifest, or authorization state changed.
- Sources: `compose.e2e.yml`; `scripts/e2e/up.ps1`; `docs/E2E_ENVIRONMENT.md`, section "Commands", and the adjacent process/seed descriptions.

## Decisions

- Do not invoke `scripts/e2e/up.ps1` while it performs migrations and seeding under the active restriction.
- Existing PostgreSQL/Redis health statements remain inherited from the WP0 artifact; they are not claimed as started or rechecked in this continuation.

## Verification state

- Manually reviewed the documented command description in `docs/E2E_ENVIRONMENT.md`.
- No tests, checks, builds, CI, migrations, runtime probes, service startups, staging, or commits were run for this documentation update.
