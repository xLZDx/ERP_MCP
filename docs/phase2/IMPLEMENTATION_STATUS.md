# Phase 2 Implementation Status — 2026-10-08

Release 2: **NO-GO**. Product acceptance: **NOT_RUN**. No gate G0–G7 has passed.

## Verified scope (single source of truth for this file)

- Repository: `D:\Repo\ERP_MCP-phase2`, branch `phase2/living-model-connectors-reconciliation`.
- Base HEAD: `9b4fc0cc365f0066cb120531025ced0cf9240516` (local; ahead of origin by 1 commit, push not performed). The remediation described below is a working-tree change on top of this HEAD until committed; the committing SHA is recorded in `DECISION_LOG.md`.
- Release 1 checkout, production gateway, 1C, PostgreSQL and OAuth were not modified.
- Execution evidence (local, offline): `pytest -q tests\phase2` → **310 passed, 20 skipped**, exit 0; `ruff check src\business_ai_gateway\phase2 tests\phase2` → exit 0; `compileall` → exit 0. Without a DSN the 20 PostgreSQL integration tests are skipped (`NOT_RUN`). **They were run on a disposable PostgreSQL 16 (docker container `erp-phase2-test-pg`, 127.0.0.1:55712, no volumes, random password, isolated from the R1 containers): `ERP_PHASE2_REQUIRE_PG=1 pytest -m integration` → 20 passed** (first run 16 passed / 4 failed; all four were wrong test expectations, not security defects: FK checked before the TRUNCATE guard, role-granted tenant visible under GUC spoof, helper returned the wrong id, head created in a rolled-back transaction; tests fixed, no SQL change). Migrations 001-003 apply cleanly in order. Not yet covered: backup/restore, crash-kill mid-page, load/capacity, mutation check that each test fails when its guard is removed. R1 regression suite: **NOT_RUN**.
- Earlier figures in other documents (23/74/122/125/128/133 tests, HEAD `68e4f97`) are historical and superseded by this section.

## Independent review round 1 (2026-10-08, read-only, local Sonnet agents)

Six reviewers (database, security, Python, test adequacy, reliability, architecture) on `9b4fc0c` found, among others: tenant isolation bound to a client-settable GUC; unauthenticated `promote_head` bypassable by direct DML; client-controlled `recorded_at`; `commit_cursor_page` advancing the cursor on NULL events and not fenced by the job lease; no roles / PUBLIC EXECUTE open; TRUNCATE not guarded; GAP events masking OBSERVED heads; Drive removals and unknown changes silently dropped; EDMX structural hash ignoring unnamed content; truthy ACL result and no audit before connector calls; backend-id aliases bypassing the budget; static SQL text tests counted as evidence.

Remediation rewrote `db/phase2/001`/`002`, added `003_security_hardening.sql`, fixed the Python modules above and replaced decorative tests with behavioral ones. A verification round (fixes plus regressions) found further issues (SQL N-1..N-11, Python F1..F9, test gaps), all fixed in the same commit except those listed as open in `DECISION_LOG.md` D-001. **All SQL remains unexecuted; the fixes of the verification round have not had an independent re-review.**

## Gate status

| Gate | Status | Evidence gap / unblocker |
| --- | --- | --- |
| G0 | BLOCKED | Scope rebaseline / explicit authority (OB-01), donor inventory and licenses (OB-15) |
| G1 | BLOCKED (IMPLEMENTED_UNVERIFIED) | SQL drafted and statically reviewed only; needs authorized disposable PostgreSQL (OB-03) for roles/RLS/immutability/CAS/fencing/outbox/backup tests |
| G2 | NOT_STARTED | Authenticated source-wide 1C observation and bounded worker (OB-10) |
| G3 | BLOCKED | Authentic native report and independent accountant attestation (OB-11) |
| G4 | BLOCKED | ERP_MCP-owned narrow Drive OAuth (OB-12) |
| G5 | NOT_STARTED | Admin workbench and real user/admin acceptance |
| G6 | BLOCKED | Production permission, canary, capacity, chaos, recovery (OB-14) |
| G7 | BLOCKED | All gates, exact-head manifest, release-owner approval (OB-21) |

## What the code is and is not

- Python modules in `src/business_ai_gateway/phase2/` are isolated, unwired reference implementations (no R1 imports them). `temporal.py` is an in-memory ledger; `backend_budget.py` is single-process; `drive_*` and `onec_discovery.py` take injected callbacks; reconciliation modules are EVALUATION_ONLY comparators.
- SQL under `db/phase2/` is **not deployable** until executed and reviewed on a disposable PostgreSQL. Static SQL contract tests are preflight lint, not G1 evidence.
- Operator-only blockers: `OPERATOR_BACKLOG.md` and `G1_OPERATOR_BACKLOG.md`.

## Next engineering actions (without operator input)

1. Close the verification review findings; commit with a detail file.
2. Slices without PostgreSQL: persistence ports and fakes, connector SDK envelope, scheduler/failure-vs-drift logic, promotion service on a port.
3. After OB-02/OB-03: GPT-PM sweep, PostgreSQL integration run with `ERP_PHASE2_REQUIRE_PG=1`, restore/role/RLS evidence.

No R2 production GO. No accounting PASS from numeric comparisons alone.
