# ERP_MCP — ADMIN BRANCH ONLY REMEDIATION MASTER PROMPT

## Mission

Fix only the Admin Control Center branch and bring it to the strongest safe merge-ready state possible.

Repository:
- https://github.com/xLZDx/ERP_MCP.git

Dedicated Admin worktree:
- D:\Repo\ERP_MCP-admin-control-center

Branch:
- feature/admin-control-center-implementation

Current verified Admin HEAD at prompt creation:
- dff4c81d18e645fed64aed50d148ab8df9109f66

Current integration reference HEAD at prompt creation:
- 98dabc3d05f47983c65d7e6220a19e2db71cf7de

main:
- 8481c0e7c794fc2474efb1b56044363043608698

This task is ADMIN-BRANCH ONLY.

Do not fix unrelated integration, OData, semantic-engine, sidecar, RSV, Ferma, DAD or production-release findings unless a minimal compatibility change is strictly required to make the Admin branch safe to merge.

Do not merge to main.

Do not delete branches.

Do not touch D:\Repo\ERP_MCP or its dirty phase/p6 worktree.

Use only D:\Repo\ERP_MCP-admin-control-center.

## First action — freeze actual state

Before editing:

1. git fetch --all --prune
2. git status --short --branch
3. git rev-parse HEAD
4. git rev-parse origin/feature/admin-control-center-implementation
5. git rev-parse origin/integration/1c-mvp-production-candidate
6. inspect current PR/CI state
7. record whether either branch moved since the SHAs above

If Admin has moved, review the delta first.

Never reset or discard valid local work.

## Non-negotiable current facts

Independent review reproduced a migration collision between integration and Admin.

Integration uses its own 008/009.

Admin currently has:
- 008_admin_platform_roles.sql
- 009_admin_mutation_control.sql
- 010_business_capability_policy.sql
- 011_company_scope_mappings.sql

Migration identity is integer-only.

This is BLOCKER B1 and must be solved before merge readiness.

The independent review also reproduced a cross-source mutation authorization bypass at older Admin SHA 68faa89.

Current dff4c81 appears to contain a fix through stored-target source checks, but the exact exploit has not yet been replayed on current HEAD.

Current Admin CI dff4c81 / run 37490816842 is green.

uv.lock is still absent.

## Scope of this remediation

Fix and verify only these Admin-owned items:

### A. B1 — migration lineage / numbering collision

Goal:
Admin must be safely integrable after current integration migrations without duplicate semantic version numbers.

Preferred end state after restacking onto the exact frozen integration HEAD:

- integration migrations stay unchanged
- Admin-specific migrations become the next monotonic versions, e.g.
  - 010_admin_platform_roles
  - 011_admin_mutation_control
  - 012_business_capability_policy
  - 013_company_scope_mappings
- SCHEMA_VERSION updated accordingly
- no duplicate integer versions
- schema_migrations records migration name + checksum, or an equivalently strong identity mechanism
- CI fails on duplicate versions or checksum mismatch
- upgrade from existing integration v9 is tested
- fresh database migration is tested
- already-created Admin development DBs have a documented, safe migration/remap strategy

Do not perform destructive production migration.

Do not silently rewrite an existing production schema history.

If restacking/renumbering requires history-sensitive treatment, create additive compatibility/remap logic and tests.

### B. B2 — exact cross-source mutation authorization

Replay the original exploit against current HEAD with real PostgreSQL:

Principal:
- ACCESS_ADMIN scoped to source-a
- AUDITOR scoped to source-b

Attempt mutation against an object in source-b.

Expected:
- HTTP 403
- object unchanged
- no successful mutation audit outcome
- no side effect

Test at minimum:
- grant revoke
- business role revoke
- capability override revoke
- semantic mapping create
- semantic profile validate
- semantic profile retire
- company-scope mapping create

Authorization must use the stored object's real source, not a caller-provided source.

Do not use list endpoints with limits as an authorization oracle.

Use direct primary-key target lookup.

### C. Security mutation suite — old 8/8 survivors must now die

Re-run exactly:

1. remove revoked binding filter
2. remove expires_at binding filter
3. bypass missing-binding 403
4. accept token verifier None instead of 401
5. bypass can_admin_source
6. remove row_version conflict guard
7. break idempotency replay protection
8. break request-fingerprint mismatch protection

Target:
- 8/8 KILLED

For each mutant record:
- mutation
- expected failing test
- actual failing test
- KILLED/SURVIVED

Do not accept incidental kills by unrelated git/artifact tests.

### D. Admin OAuth scope hardening

Current code appears to reject empty/whitespace/multiple scopes.

Prove with tests:

- "" -> startup/config rejection
- "   " -> rejection
- "scope1 scope2" -> rejection
- admin scope == onec:read -> rejection
- distinct single admin scope -> accepted

Also ensure auth.py cannot truthiness-fallback a deliberately supplied invalid value.

### E. Platform role NULL/global semantics

Make the policy explicit for all five roles:

- PLATFORM_ADMIN
- SOURCE_ADMIN
- ACCESS_ADMIN
- PROFILE_ADMIN
- AUDITOR

Decide and document which roles may have source_id=NULL.

Recommended safe policy unless accepted architecture says otherwise:

- PLATFORM_ADMIN: MUST be global / source_id NULL
- SOURCE_ADMIN: MUST be source-scoped
- ACCESS_ADMIN: MUST be source-scoped unless a separately explicit global-access-admin role/policy exists
- PROFILE_ADMIN: MUST be source-scoped unless explicitly approved global semantics exist
- AUDITOR: global may be allowed only if explicitly intentional and tested

Enforce the chosen contract in:
- service validation
- DB CHECK constraints / migration
- tests
- docs

Do not rely on UI convention.

### F. expires_at

Current web mutation path has _expiry() parsing.

Verify:
- valid timezone-aware ISO accepted
- malformed value -> stable INVALID_REQUEST
- naive timestamp -> rejected
- null/empty -> no expiry
- expired binding not effective

Verify CLI separately.

Do not return asyncpg DataError/500 for user input.

### G. Reproducible dependency lock

Admin branch currently has no uv.lock.

Bring dependency installation onto a reproducible contract compatible with repository policy.

Preferred:
- restack onto integration lock if restack makes it naturally available
- otherwise generate/update uv.lock from the Admin tree using the repository's supported tooling

Then verify:
- uv sync --locked or repository-equivalent works
- CI uses the lock
- no hidden dependency drift

### H. Admin route authorization must not depend on bounded lists

Independent red-team concern:
old objects could become non-actionable if authorization relies on list results capped at 500/1000.

Ensure all mutation authorization is primary-key/direct lookup based.

List pagination limits may affect UI display but never authorization.

Add regression coverage for an object outside normal list-page range.

### I. Admin audit attribution

For mutation success/deny/conflict/error verify:
- actor subject
- client
- request_id
- action
- exact target
- source_id where known
- company_id where known
- reason
- idempotency key
- outcome
- detail code

Specifically verify revoke/validate/retire paths do not lose source_id.

No secret/token/raw accounting payload.

### J. Admin UI correctness gaps

Only fix Admin UI issues supported by current backend.

Verify/fix:
- 409 conflict has explicit UI state
- double-click/retry does not create duplicate grants
- visible mutation-disabled/enforcement-disabled states
- grants show expiry and scope clearly
- global vs source-scoped role clearly differentiated
- no-role user receives a correct forbidden state, not misleading login
- accessible dialogs
- keyboard focus
- distinct navigation icons/labels
- 200% zoom
- narrow/mobile layout

Do not invent backend capabilities just to fill prototype screens.

### K. CSP

Review current Admin UI CSP.

Remove script-src 'unsafe-inline' if safely possible using packaged external/static JS or nonce/hash strategy.

If not closed in this branch, document exact reason and risk.

### L. Admin CI parity

Current Admin CI exists and is green.

Keep it green and strengthen it to cover Admin-specific gates:
- migrations
- upgrade-from-integration-v9
- DB privileges
- auth/RBAC
- mutation tests
- Admin UI asset/browser checks
- lockfile/reproducible install

Do not copy unrelated Windows/RSV/release jobs unless they are required by the Admin code.

## Explicitly out of scope

Do NOT fix these in this task:

- integration metadata-error fingerprint behavior
- runtime business_ai_app source_capabilities privilege model, except if directly needed by Admin DB compatibility
- generic onec_read allowlist/expand/truncation
- sidecar breaker/logging
- RSV process limits
- DAD rule engine
- Ferma testbed
- real 1C native reconciliation
- registry image signing / attestation / SLSA
- production pilot
- production GO

If an out-of-scope issue blocks Admin verification, document it; do not expand scope.

## Local reviewer protocol

Use local reviewer roles only:

- Admin security
- DB/migrations
- backend correctness
- UI/accessibility
- test/mutation
- architecture

Independent first pass, then consensus.

No external AI reviewers without operator authorization.

For every claimed closure require code + regression test; for B1/B2 require real PostgreSQL reproduction.

## Test floor

Before every milestone:

- compileall
- full pytest
- ruff
- bandit
- pip-audit
- PostgreSQL migrations
- PostgreSQL privilege tests
- Admin mutation integration tests
- Admin auth/session/CSRF tests
- browser/UI contract tests
- migration duplicate/checksum tests
- upgrade-from-integration-v9 test

Record exact counts and skipped reasons.

No "should pass"; observe actual results.

## CI

After push:
1. obtain exact SHA
2. inspect exact GitHub Actions run
3. wait for completion
4. fix failures
5. push again
6. repeat until exact final SHA is green or a genuine external blocker exists

## Documentation

Update Admin-owned documentation only, plus minimal shared docs required to prevent false claims.

At minimum:
- docs/admin-control-center/*
- reports/ADMIN_CONTROL_CENTER_STATUS.md
- SECURITY.md if Admin role/scope contract changes
- DATA_MODEL / architecture only where required by Admin migration/role contract

Do not rewrite unrelated integration status/history.

## Git discipline

Work only on feature/admin-control-center-implementation unless a temporary local test branch/worktree is required.

Do not:
- merge main
- merge to main
- delete branches
- force-push main
- reset valid work
- clean unrelated worktrees
- perform destructive DB operations

Commit coherent slices and push only the Admin branch.

## Required closure evidence

Final report must include:

BRANCH
WORKTREE
BASE/FROZEN INTEGRATION SHA
FINAL ADMIN HEAD
COMMITS

B1 MIGRATION
- exact migration sequence
- fresh DB result
- upgrade-from-v9 result
- checksum/duplicate guard

B2 AUTHORIZATION
- exact exploit replay
- result for all affected mutation routes

MUTATION TESTING
- all 8 old mutants
- killed/survived
- exact tests

AUTH
- empty/whitespace/multiple/data-plane admin scope cases

PLATFORM ROLE SCOPE
- final NULL/global semantics
- DB constraints
- service tests

EXPIRES_AT
- API
- CLI
- expired-binding behavior

DEPENDENCY LOCK
- uv.lock state
- locked install result

UI
- conflict/idempotency/accessibility states

TESTS
- exact pass/fail/skip counts

CI
- exact run ID
- exact SHA
- conclusion

OPEN EXTERNAL GATES

MERGE READINESS
- READY / NOT READY

## Terminal condition

Admin branch is ready only when:

- B1 migration collision is eliminated
- exact B2 exploit replay is denied
- all old 8 Admin security mutants are killed
- global/source role semantics are explicit and enforced
- expires_at is safe
- locked dependency install exists
- Admin tests + PostgreSQL + browser tests are green
- exact final Admin CI is green
- no Admin BLOCKER/MAJOR remains
- Production GO is still not falsely claimed
- no merge to main has occurred

Continue autonomously until this terminal condition or a genuine external/owner-approval blocker.
