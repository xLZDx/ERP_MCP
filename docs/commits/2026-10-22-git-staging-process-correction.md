# Change record: distinguish Git staging from deployment staging

Date: 2026-10-22  
Scope: clarify active workflow documentation after the operator's correction.

## What changed

- Updated `docs/phase2/AUTONOMOUS_EXECUTION_PLAN_2026-10-21.md` to identify forbidden staging as
  a staging-environment deployment and state that explicit-path Git staging and local commits
  are authorized.
- Updated `docs/commits/2026-10-22-wp3-english-prose-pass.md` so its active next-step guidance
  defers tests during coding but permits Git staging/local commits with exact-patch GPT-PM
  review.

## Why

The operator clarified on 2026-10-22 that the prohibition concerns a pre-production staging
deployment, not Git's index. The plan already had a current-state notice, but a later hard-rule
line and a WP3 decision still said “no staging” or “do not stage or commit,” which could be read
as blocking authorized local development.

## Boundaries

- Staging-environment deployment remains forbidden.
- Git staging must use explicit paths; every local commit needs its own detailed change record
  and lesson entry, and exact-patch GPT-PM review.
- Push and PR remain gated on approval of the exact final head after required tests and reviews.
- No tests, checks, builds, CI, migrations, service action, push, or PR were performed for this
  documentation correction.
