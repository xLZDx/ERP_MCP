# G1 blockers and operator handoff — 2026-10-08

> **Historical snapshot (2026-10-08).** The blocker table below describes commit 9b4fc0c; it is not a current inventory. See “Current reconciliation (2026-10-15)” at the end and `S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`. G1 remains NOT_PASSED.


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

## Current reconciliation (2026-10-16)

The original blocker table is preserved as history. The later migrations, authored test scenarios and independent reviews supersede several implementation claims, but do not satisfy G1's formal exit criteria. `governance/GATE_MANIFEST.json` remains authoritative: G1 is NOT_PASSED, engineering IN_PROGRESS, external evidence OPEN, and production authorization NONE. The engineering status reflects implementation of focused COMMIT/restore acceptance scenarios and their static review; it does not mean runtime evidence or gate acceptance exists.

| Historical blocker | Current evidence/status | Remaining acceptance |
|---|---|---|
| G1-B01 — migration-authoring route | Superseded for local engineering: migrations 003–018 are tracked and later SQL work used the repository route. This does not authorize deployment. | No provider action for local authoring; keep all migrations test-only until gate evidence passes. |
| G1-B02 — disposable PostgreSQL target | Superseded for synthetic tests: PostgreSQL 16 disposable runs are recorded in `EVIDENCE_MATRIX.md` and the 2026-10-15 checkpoint. | A named, isolated target and exact-head evidence are still required for G1 acceptance. |
| G1-B03 — SQL not applied/reviewed | Historical wording superseded: migrations have been applied by focused disposable test harnesses and reviewed at prototype scope. | Complete the G1 contract review and exact-head runtime evidence; no production apply. |
| G1-B04 — tenant/source/company isolation | Partial: migration 003 adds source/company role scope, RLS, revocation, and scoped grants. Independent static review at HEAD `8935deda` found no cross-tenant bypass in migrations 016–018 under the documented ledger-owner/superuser trust boundary. | Current-head negative tests for tenant, source, company, revoked scope, and runtime-role denials; prove owner and deployment separation. |
| G1-B05 — broad grants and unauthenticated evidence | Partial: migration 003 revokes PUBLIC access and grants scoped functions; 015–018 use narrow definer entrypoints. Some evidence/approver authority remains an independently authenticated control-plane responsibility. | Prove effective grants for the actual runtime role and authenticate approver/evidence and checkpoint identity outside the database-admin boundary. |
| G1-B06 — writer-controlled observation time | Superseded for the living registry: migration 001 assigns `recorded_at` from the database clock in a trigger; migration 003 preserves that server-authoritative insert path. | Retain this as an invariant in current-head negative evidence. |
| G1-B07 — lease/CAS/outbox and crash behavior | Partially evidenced in historical focused PostgreSQL runs and S13 prototype suites. These are not a current G1 exit run. The focused candidate map includes separate concurrent head-promotion CAS, conflicting cursor-page commit and identical-page replay scenarios (`G1_EVIDENCE_PACKET_PLAN.md`; `CHANGE_RECORD_071.md`). | Re-run required scenarios at one exact head, including those three concurrency/replay cases and the G1-required kill inside COMMIT. Results remain `NOT_RUN` under the pytest prohibition; the test plan is not gate evidence. |
| G1-B08 — backup/restore and security roles | Partial: a populated database was restored to a second throwaway database with a behavior battery (`EVIDENCE_MATRIX.md`). | G1 requires restore into another cluster plus role/RLS/digest/head equivalence at the exact accepted head. |
| G1-B09 — exact-head review and release manifest | Partial: prototype ranges have independent reviews and GPT-PM approvals; the gate manifest has no evidence attachment. | Assemble the G1 evidence package and obtain gate-specific database/security review; do not infer PASS from prototype approvals. |

G1 exit gaps confirmed by the database and security reviewers at HEAD `8935deda`: no recorded kill timed inside COMMIT; no restore into another PostgreSQL cluster; the capacity drill is a developer-host measurement, not the G1 decision; and the G1 evidence package is absent. These require disposable-database/runtime evidence and a gate review. G1 remains NOT_PASSED.

### Focused runtime acceptance for the two remaining crash/restore cases

A read-only functional-test review at HEAD `8e923ce` confirmed that the existing integration coverage does not satisfy either boundary: the crash tests terminate a backend after API work but before explicit `tx.commit()`, and the restore tests target another database in the same cluster. The shared G1 harness is single-container. Do not count those scenarios as substitutes for the G1 criteria.

| Scenario | Required falsifiable evidence | Boundary and safe fallback |
|---|---|---|
| Backend termination while SQL `COMMIT` is executing | On a disposable PostgreSQL instance, create uncommitted work and a test-only deferred constraint trigger that waits during explicit COMMIT. From a separate observer connection, record the target PID executing COMMIT and waiting inside that trigger before terminating it. After recovery, assert the committed baseline, the actual all-or-nothing recovered state, and safe same-input replay with no duplicated cursor/outbox effect. | A lock wait inside an API function, or a backend killed before `tx.commit()`, is not evidence. This proves termination during COMMIT processing; it does not prove the narrower post-WAL-commit/pre-acknowledgement ambiguity window. If the observer cannot establish COMMIT execution before termination, report NOT_RUN for this criterion. |
| Restore into a separate PostgreSQL cluster | Populate and dump the source cluster; restore into a separately provisioned disposable PostgreSQL cluster. Before data setup, record both container identities and `pg_control_system().system_identifier` and prove they differ. Compare schema, data digests, sequences, foreign keys, RLS, effective grants, accepted heads and behavior; then prove the restored target can continue the permitted ledger operation. | Two databases on one server/cluster do not qualify. Require explicit fixture ownership and cleanup guards for each disposable cluster. If the second cluster cannot be safely provisioned, report NOT_RUN with that exact dependency; do not substitute the existing single-container harness. |

These are test-authoring and runtime tasks for the functional-test-reviewer/e2e-runner after in-scope coding is complete. No test code, container, database, or runtime evidence was changed by the earlier documentation update. They close only these two synthetic evidence gaps; capacity, effective-role/approver evidence and the complete G1 gate review remain separate acceptance items.

### Authored focused acceptance tests (2026-10-15)

The `e2e-runner` has authored the two focused acceptance scenarios in
`tests/phase2/test_g1_crash.py` and `tests/phase2/test_g1_restore.py`, with invocation-owned
cluster helpers in `tests/phase2/_pg_harness.py`. A read-only functional-test review found no
remaining BLOCKER or MAJOR in the final reviewed changes. This is source review only; it does not
prove runtime behavior.

- The COMMIT scenario uses a deferred constraint trigger and a separate observer. It records the
  backend PID, active query, state, wait event and advisory-lock status before terminating the
  backend. If the observer cannot establish the boundary, the criterion reports `NOT_RUN`. After
  termination it checks rollback, committed baseline survival and same-input page replay.
- The restore scenario uses separately provisioned clusters and records their Docker IDs and
  PostgreSQL system identifiers. It compares schema, data digests, sequences, constraints,
  policies, effective grants, accepted heads and behavior, including tenant/source/company scope,
  GUC spoofing and a genuinely deleted reader grant. In each cluster, it checks that an already
  scoped session is rejected and a fresh session cannot reacquire the deleted scope; it then
  performs a permitted operation on the restored target.
- All crash and restore tests in these files now provision uniquely named `r2-s13-dump-*`
  containers, verify their invocation-specific ownership label before container operations, and
  remove only verified containers and their anonymous PostgreSQL volumes. They do not attach to
  the former shared `erp-phase2-test-pg` target.

Runtime evidence is `NOT_RUN`: `D:\Repo\AGENTS.md` explicitly prohibits running `pytest`, including
these focused files. No PostgreSQL container or database was started or changed. G1 remains
`NOT_PASSED`; the authored scenarios do not satisfy runtime acceptance until an allowed focused
run produces exact-head evidence. Capacity, effective-role/approver evidence and the complete G1
gate review remain outstanding as separate acceptance items.

### GPT-PM focused static re-review (2026-10-16)

GPT-PM reviewed the complete attached patch for `origin/main..17b6de78743f2e40f6ae0f6bca322b4e87ba7d96`
under request `8bcc1579-b818-4aef-98a6-eab6a2d470fb`. Verdict: `APPROVE — STATIC REVIEW`, 0
BLOCKER and 0 MAJOR. The review confirmed the exact `living_reader` A/s1 grant deletion, denial for
the existing scoped connection and a fresh connection in both clusters, and no direct regressions
in the 12 changed paths. It closed G1-M01 at source level only. Runtime remains `NOT_RUN`, G1
remains `NOT_PASSED`, and this review does not authorize push; exact-head runtime evidence and
remaining capacity, effective-role/approver, and gate-specific acceptance are still required.

The ordered evidence assembly plan and per-item status are in
`docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`. It classifies the existing capacity drill as prototype
context and separates runtime permission evidence from static SQL/review evidence.
