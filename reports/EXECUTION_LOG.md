# Autonomous engineering execution log

## Step 21 — source-specific register capability rule

**Status:** implemented and verified locally; hosted CI pending.  
**Date:** 2026-10-05

- Added migration 005 to persist register capability evidence per source.
- The Python adapter and OData sidecar require confirmation for the exact source, register entity
  set, and method. The sidecar rechecks its short-lived live-metadata profile before each operation.
- Configuration-sensitive operations, including `DrCrTurnovers`, return
  `CAPABILITY_UNSUPPORTED` when evidence is absent or stale. No alternate names are guessed and no
  speculative OData data request is issued. Positive and negative evidence is returned in the
  source capability profile.
- Added the internal ERP_MCP ↔ pinned OData sidecar contract, capability endpoint/response tests,
  migration/persistence coverage, and confirmed-positive/unsupported-negative DrCr fixtures.
- Reuse remains pinned to `hacker-cb/1c-odata` SHA
  `cf5f0d1cfb28cc24d0c9d374ad4a17d83dfe24c5`; upstream source is unchanged. No new OData protocol
  implementation, COM bridge, or GPL-derived core code was added.
- Verification: Python `67 passed, 5 skipped`; sidecar `11/11`; pinned upstream client
  `428 passed, 1 skipped`; metadata `53 passed`; PostgreSQL integration `4 passed`; Ruff,
  compileall, Bandit, and `git diff --check` pass. The rebuilt image returned `/healthz` 200 as UID
  10001 with no published ports.
- Next: publish this batch and wait for hosted CI; then continue with semantic profile/preset
  lifecycle and deterministic tests. Real-source semantic validation still requires a real 1C base.
