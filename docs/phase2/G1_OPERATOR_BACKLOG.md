# G1 blockers and operator handoff — 2026-10-08

## State
G1 is **BLOCKED / NOT VERIFIED**. R2 release is NO-GO.

## Required independent steps, in dependency order

| ID | Blocking issue | Resolution criterion | Operator action |
| --- | --- | --- | --- |
| G1-B01 | Remote tool policy rejected the third, privilege-hardening SQL migration write | Tool policy explicitly permits migration-authoring activity via supported route; no bypass | Resolve/approve tool policy with provider |
| G1-B02 | No verified isolated disposable PostgreSQL target | Record host identity, database name (not secret), isolation and backup proof | Authorize/create disposable R2 test DB, with separate credentials |
| G1-B03 | R2 migration SQL not applied or reviewed | SQL reviewed, migrated in disposable DB, never production | DB owner reviews under isolated scope |
| G1-B04 | RLS tenant-only, no source/company policy; session GUC not full ACL | Denial tests cross-tenant, cross-source, cross-company, revoked-scope | Independent security review and hardening |
| G1-B05 | Broad default function EXECUTE, unchecked approver/evidence strings | Least-privilege grants and separately authenticated attestation | Security/DB permission design review |
| G1-B06 | Observation recorded_at can be provided by writer | DB-generated registry time regardless of caller payload | Approved migration hardening |
| G1-B07 | No real Postgres lease/CAS/outbox testing | Concurrent workers, crashes, stale fencing, replay prove pass/fail | Disposable DB with test execution permitted |
| G1-B08 | No backup/restore/security role exercise | Restored ledger digests, FK, RLS and accepted heads verified | Test-only backup target and role privilege |
| G1-B09 | No exact-head independent review / release manifest | Explicit evidence + security/database review | Approvers review artifacts |

## Executed and NOT executed

- Executed: offline `pytest tests/phase2` → **128 passed in 2.05s**, result `g1_full_pytest_local.txt`.
- Previously executed: Ruff on Phase 2 → PASS, `g1_ruff_local.txt`; rerun after subsequent changes is required.
- NOT executed: SQL apply, PostgreSQL negative permission test, multi-worker concurrency test, crash/replay test, backup/restore, R1 regression suite.
- NOT performed: change to R1 worktree or production, merging, role/credential changes, deletions, force push.

## Security caveat

The two drafted SQL migrations must not be deployed until G1-B04/B05/B06 are resolved. Tests of literal SQL fragments cannot establish correct privilege behavior.
