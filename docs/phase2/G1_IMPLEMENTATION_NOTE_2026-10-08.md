# G1 PostgreSQL Living Registry — implementation note

Date: 2026-10-08. Status: **IMPLEMENTED_UNVERIFIED / G1 NOT PASSED**.

## Files created
- `db/phase2/001_living_registry.sql`: isolated schema, scoped keys/FKs, observations, accepted head, immutable acceptance history, jobs, cursors, outbox, tenant RLS and effective/known-time read functions.
- `db/phase2/002_job_cursor_functions.sql`: bounded job claim, fencing token enforcement on completion, transactional cursor CAS + outbox with conflicting-digest detection.
- `tests/phase2/test_g1_migration_contract.py`: source-level migration presence/contract tests **not** PostgreSQL execution tests.

## Important implementation limitations
- The migration has **not been applied**. No real PostgreSQL negative tests, role/grant review, backup/restore or replica/fault tests were captured.
- Tenant RLS alone is not sufficient for full source/company membership and revocation enforcement. Dedicated R2 roles, authenticated session context and source/company security boundaries need security review before runtime integration.
- The `promote_head` SQL function checks presence of an evidence reference but **does not authenticate** the approver or attest evidence; only a privileged, independently-authorized control API may expose this operation.
- Native immutable SQL events are not cryptographically tamper-proof against owner/superuser.
- `living.tenants` and setup/provisioning privileges require an isolated reviewed owner/runtime-role split.
- No production credentials or old R1 role grants are set here.
- Tests were attempted through Remote Desktop Commander, but no trustworthy completed terminal result was available. Do not treat them as passing.
- A Docker inspection command was blocked by tool policy. It was not retried by an alternate route.

## G1 exit checklist (all currently not verified)
1. Explicitly identify disposable PostgreSQL instance and database; record identity, backup and network isolation.
2. Review migration SQL and execute in a transaction against that instance only.
3. Create least-privilege R2 roles independently of R1 and verify RLS across tenants AND sources.
4. Verify negative UPDATE/DELETE for immutable tables including app/admin roles.
5. Verify AS KNOWN AT / AS EFFECTIVE AT including late correction and unknown source-effective times.
6. Verify stale CAS cannot promote a model; authenticate approver and independently verify evidence.
7. Verify two workers cannot hold the same valid lease and stale fencing token cannot finish work.
8. Inject crash midway through page persistence and prove cursor/outbox atomicity and duplicate-digest conflicts.
9. Replay, backup/restore and fail-closed/revocation tests; record exact head, commands and outputs.
10. Complete independent DB/security review, then and only then mark G1 VERIFIED.

Production 1C/gateway/R1 remain outside the scope of this work.

## Follow-up verification

The isolated static migration-contract test command completed with **3 passed in 0.35s**, captured in `docs/phase2/g1_pytest_local.txt`. This verifies only SQL file presence and declared fragments. It does not change G1 status; PostgreSQL integration tests remain NOT_RUN. The earlier statement that no terminal result was available refers to the initial attempts before redirecting this targeted test output.

## Autonomous continuation evidence (2026-10-08)

- Full Phase 2 isolated Python tests: **125 passed in 3.07s**. Captured in `docs/phase2/g1_full_pytest_local.txt`.
- Ruff check of `src/business_ai_gateway/phase2` and `tests/phase2`: **All checks passed**; `docs/phase2/g1_ruff_local.txt`.
- Git status before this work: only previously created G1 files and docs untracked; no tracked changes reported.
- Attempted to prepare a third SQL hardening migration (source-scoped RLS, function privilege lockdown and server-controlled timestamps), but the Remote Desktop Commander security policy blocked the write. **No alternative route was used.** This remains a G1 blocker.

### Blocking security findings in the current draft

1. PostgreSQL functions normally grant EXECUTE to PUBLIC unless explicitly revoked. Current migrations do not provision dedicated least-privilege R2 roles or revoke PUBLIC function EXECUTE; exposure depends on schema USAGE. Must be verified and hardened before deployment.
2. Current RLS is tenant-scoped, not exact source/company-grant scoped, and relies on a trusted server-set session GUC. The GUC is not a substitute for source ACL or a secure role boundary.
3. The initial acceptance procedure accepts approver and evidence-reference strings as parameters; it does not authenticate signer or validate evidence. Treat `promote_head` as **unsafe for public/runtime use** until restricted behind separately authorized service and tested.
4. Observations permit explicitly supplied `recorded_at`; registry knowledge-time must be assigned by the database, not trusted to a connector.
5. Existing static contract tests only check SQL text fragments and are not DB integration or negative-access tests.

**Decision:** G1 remains BLOCKED / IMPLEMENTED_UNVERIFIED. Do not apply SQL to production or grant application privileges; no release/cutover. User authorization for routine Phase 2 engineering is not authorization to override a connector's safety refusal.

## Additional independent S3 lane

- Added `src/business_ai_gateway/phase2/backend_budget.py`: a thread-safe **single-process reference** budget keyed by trusted physical backend identity (not source aliases), with guaranteed slot release.
- Added `tests/phase2/test_backend_budget.py`: five offline checks, including concurrency, capacity, invalid identity, error cleanup.
- It is **not** a distributed/Redis-backed capacity implementation, has no fairness queue and is not wired to active connectors. `R2-US-019` remains `IMPLEMENTED_UNVERIFIED` at most.
- Full Phase 2 suite after this addition: **133 PASS**; Ruff **PASS**. Evidence: `g1_full_pytest_local.txt` and `g1_ruff_local.txt`.
