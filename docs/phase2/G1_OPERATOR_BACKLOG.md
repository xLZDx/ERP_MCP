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

The original blocker table is preserved as history. The later migrations, authored test scenarios and independent reviews supersede several implementation claims, but do not satisfy G1's formal exit criteria. `governance/GATE_MANIFEST.json` remains authoritative: G1 is NOT_PASSED, engineering IN_PROGRESS, external evidence OPEN, and production authorization NONE. **Scope distinction:** local engineering push is gated by focused local tests authored/executed by the functional-test-reviewer and e2e-runner, relevant specialist review, and fresh exact-head GPT approval under `D:\Repo\AGENTS.md`. G1 formal/release items below do not add separate production-database or deployed-identity prerequisites to that local push. They remain applicable to G1/release acceptance and production authorization.

Current local test status: the first focused run at committed HEAD `4b9f3b08b4e75359b549bda75d6f6ec3307f248e` reported 46 passed and 1 failed because the reader directly called internal `living.assert_scope`. Commit `69857fd` corrected the assertion to check RLS-visible rows before and after revocation and retained the fresh-context `living.set_scope` denial. The corrected distinct-cluster restore test passed for functional-test-reviewer (1 passed in 17.89s) and e2e-runner (1 passed in 15.27s; repeat with JUnit XML, 1 passed in 14.82s), as recorded in `CHANGE_RECORD_080.md`. At code/test HEAD `73e4253b571fa45382af6f954f773e1eae5f91be`, functional-test-reviewer reported raw 45 passed, 0 failed, 0 skipped in 57.13s; e2e-runner separately passed observed explicit-COMMIT (1 in 14.74s). Database-reviewer identified a MAJOR evidence flaw in the original MAJOR-02 test. Functional-test-reviewer fixed it in code commit `a6263e4bafe69aedd14372f394d67da7b6fb3366`; the corrected test observed exact API SQL, Lock wait, transactionid wait event and the revoke backend in `pg_blocking_pids` before revoke commit, and all 24 variants passed in 16.56s. Database-reviewer confirmed the finding resolved. Silent-failure-hunter found no B/M and confirmed the false-pass protection; it reviewed read-only and did not rerun tests, noting the wait-event subtype itself is not asserted. Static code-reviewer found no B/M or direct regression in 40 paths. PM approved exact reviewed HEAD `17900345c88237290c498d73b6f8849c265351d1`; the normal fast-forward range from remote HEAD `3aba6e37af8d3e5d1d98eb4f5f308e15aec1e3ac` was pushed and `origin/main` was confirmed at the approved HEAD. Selected runtime and specialist review are complete. Any later push needs fresh approval for its new exact HEAD. Formal G1 remains NOT_PASSED.

| Historical blocker | Current evidence/status | Remaining acceptance |
|---|---|---|
| G1-B01 — migration-authoring route | Superseded for local engineering: migrations 003–018 are tracked and later SQL work used the repository route. This does not authorize deployment. | No provider action for local authoring; keep all migrations test-only until gate evidence passes. |
| G1-B02 — disposable PostgreSQL target | Superseded for local test setup: prior PostgreSQL 16 disposable runs are recorded in `EVIDENCE_MATRIX.md` and the 2026-10-15 checkpoint. The focused G1 integration tests use a disposable local PostgreSQL fixture; Docker supplies crash/restore clusters. | The focused test-agent suite on disposable local infrastructure passed for the PM-approved range already pushed. A separate deployed/production database is not required for local push. |
| G1-B03 — SQL not applied/reviewed | Historical wording superseded: migrations have been applied by focused disposable test harnesses and reviewed at prototype scope. | Exact-head local test results and reviews were completed for the PM-approved range already pushed. G1 formal release acceptance remains separate; no production apply. |
| G1-B04 — tenant/source/company isolation | Partial: migration 003 adds source/company role scope, RLS, revocation, and scoped grants. Independent static review at HEAD `8935deda` found no cross-tenant bypass in migrations 016–018 under the documented ledger-owner/superuser trust boundary. | The selected local negative cases passed for the reviewed range. Formal G1 also retains its owner/deployment boundary criteria; these remain open separately. |
| G1-B05 — broad grants and unauthenticated evidence | Partial: migration 003 revokes PUBLIC access and grants scoped functions; 015–018 use narrow definer entrypoints. Local tests cover fixture-level grants/evidence behavior; external authenticated identity is a separate production concern. | Selected local privilege/approver tests and reviews passed for the reviewed push range. Formal G1 retains deployed effective-grant and identity acceptance separately. |
| G1-B06 — writer-controlled observation time | Superseded for the living registry: migration 001 assigns `recorded_at` from the database clock in a trigger; migration 003 preserves that server-authoritative insert path. | Retain this as an invariant; the selected local evidence is complete for the reviewed push range, while formal gate acceptance remains separate. |
| G1-B07 — lease/CAS/outbox and crash behavior | The selected focused G1 candidate cases, including the corrected observer-backed MAJOR-02 variants and explicit-COMMIT scenario, passed on the reviewed code/test tree; see `G1_EVIDENCE_PACKET_PLAN.md` and `CHANGE_RECORD_087.md`. This proves only the selected tested schedules, not every workload or failure schedule. | The selected B07 candidate cases in `G1_EVIDENCE_PACKET_PLAN.md` have passed for the reviewed local range and that range was pushed after exact-head PM approval. This does not establish all failure schedules or satisfy the separate formal G1 acceptance. |
| G1-B08 — backup/restore and security roles | The distinct-cluster restore scenario `test_pg_dump_restore_to_distinct_postgres_cluster` passed under both test-agent owners on the earlier test-only correction and was included in the exact code/test HEAD rerun at `a6263e4bafe69aedd14372f394d67da7b6fb3366`; the selected E2E pair passed 2/2. The exact-tree rerun is recorded in `CHANGE_RECORD_087.md`; source/target identities and cleanup for the initial paired restore are in `CHANGE_RECORD_080.md`. | This scenario is now runtime-proven for the tested fixture; full B08/G1 role and formal release evidence remain separate. |
| G1-B09 — exact-head review and release manifest | Partial: prototype ranges have independent reviews and GPT-PM approvals; the gate manifest has no evidence attachment. | Assemble the G1 evidence package and obtain gate-specific database/security review; do not infer PASS from prototype approvals. |

Formal G1 exit gaps confirmed by the database and security reviewers at HEAD `8935deda`: no recorded kill timed inside COMMIT; no restore into another PostgreSQL cluster at the accepted revision; the capacity drill is a developer-host measurement, not a production-class capacity decision; and the formal G1 evidence package is absent. The focused COMMIT and restore tests are local engineering evidence and are required for local code push, but they do not by themselves pass formal G1 or authorize production. G1 remains NOT_PASSED.

The focused local test report is the execution evidence for the local engineering push. It must use the exact code revision and disposable local fixtures; it does not require a deployed database or production identity/capacity evidence. Formal G1/release acceptance separately retains effective deployed grants, authenticated approver/evidence identity, capacity disposition and gate review. The complete selected functional/multiprocessing and E2E set passed on the reviewed exact code/test tree (45/45 and 2/2), with database-reviewer finding no database BLOCKER/MAJOR. PM approved exact HEAD `17900345c88237290c498d73b6f8849c265351d1` and the range was pushed. This local evidence does not satisfy the formal G1 criteria.

### Focused runtime acceptance for the two remaining crash/restore cases

A read-only functional-test review at HEAD `8e923ce` confirmed that the existing integration coverage does not satisfy either boundary: the crash tests terminate a backend after API work but before explicit `tx.commit()`, and the restore tests target another database in the same cluster. The shared G1 harness is single-container. Do not count those scenarios as substitutes for the G1 criteria.

| Scenario | Required falsifiable evidence | Boundary and safe fallback |
|---|---|---|
| Backend termination while SQL `COMMIT` is executing | On a disposable PostgreSQL instance, create uncommitted work and a test-only deferred constraint trigger that waits during explicit COMMIT. From a separate observer connection, record the target PID executing COMMIT and waiting inside that trigger before terminating it. After recovery, assert the committed baseline, the actual all-or-nothing recovered state, and safe same-input replay with no duplicated cursor/outbox effect. | A lock wait inside an API function, or a backend killed before `tx.commit()`, is not evidence. This proves termination during COMMIT processing; it does not prove the narrower post-WAL-commit/pre-acknowledgement ambiguity window. If the observer cannot establish COMMIT execution before termination, report NOT_RUN for this criterion. |
| Restore into a separate PostgreSQL cluster | Populate and dump the source cluster; restore into a separately provisioned disposable PostgreSQL cluster. Before data setup, record both container identities and `pg_control_system().system_identifier` and prove they differ. Compare schema, data digests, sequences, foreign keys, RLS, effective grants, accepted heads and behavior; then prove the restored target can continue the permitted ledger operation. | Two databases on one server/cluster do not qualify. Require explicit fixture ownership and cleanup guards for each disposable cluster. If the second cluster cannot be safely provisioned, report NOT_RUN with that exact dependency; do not substitute the existing single-container harness. |

These are test-authoring and local execution tasks for the functional-test-reviewer/e2e-runner after in-scope coding is complete. The functional reviewer has since corrected the scope-revocation assertion; the initial disposable-PostgreSQL run and its failure are recorded in `CHANGE_RECORD_075.md`. The corrected test diff has no completed runtime result under the current workspace instruction. These scenarios provide focused local evidence for the code push when a permitted exact-head run is available. Capacity, effective-role/approver production evidence and complete G1 gate review remain separate formal release items.

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

Historical snapshot before the test-agent run: the focused files had not been executed and no
PostgreSQL container was started during that documentation pass. That snapshot is superseded by
the runtime results recorded in `CHANGE_RECORD_080.md` and `CHANGE_RECORD_081.md` below. Formal
G1 remains `NOT_PASSED`; capacity, effective-role/approver production evidence and complete G1
gate review remain separate release acceptance items, not prerequisites for local code push.

### GPT-PM focused static re-review (2026-10-16)

GPT-PM reviewed the complete attached patch for `origin/main..17b6de78743f2e40f6ae0f6bca322b4e87ba7d96`
under request `8bcc1579-b818-4aef-98a6-eab6a2d470fb`. Verdict: `APPROVE — STATIC REVIEW`, 0
BLOCKER and 0 MAJOR. The review confirmed the exact `living_reader` A/s1 grant deletion, denial for
the existing scoped connection and a fresh connection in both clusters, and no direct regressions
in the 12 changed paths. It closed G1-M01 at source level only. Focused local tests remain
`NOT_RUN`; G1 remains `NOT_PASSED`. This older review is not approval for the current push. Local
push still requires focused test-agent results, relevant specialist review and fresh GPT approval
for the exact final diff. Capacity, deployed effective-role/approver evidence and gate-specific
acceptance remain formal G1/release items.

### Earlier PM Bridge decision for local push (2026-10-16)

PM Bridge request `f4cd1c27-2b3c-4094-80f3-1fd88dbfd1e6` reviewed code HEAD
`315e83149b48fcef1d3ded7c5e2325d7c3fe7cd4`. Exact reported outcome: `STATIC APPROVE`, no
confirmed BLOCKER/MAJOR, and `PUSH NO-GO` pending exact-head runtime evidence. The corrected
distinct-cluster restore scenario has since passed on code-identical documentation HEAD
`5588c06851340751fa574e182da0e9c9b03111e9`, with evidence detailed in `CHANGE_RECORD_080.md`.
This single-case pass does not establish the full selected test set or formal G1. The earlier PM
verdict is not a new push approval; obtain an updated PM push decision after the required test
evidence is complete. G1 remains `NOT_PASSED` and production authorization remains `NONE`.
### Later PM decision and completed push (2026-10-16)

After the complete selected functional/E2E runs and specialist reviews, PM approved exact reviewed HEAD `17900345c88237290c498d73b6f8849c265351d1`. A normal fast-forward from the preflight `origin/main` HEAD `3aba6e37af8d3e5d1d98eb4f5f308e15aec1e3ac` succeeded; post-push lookup confirmed `origin/main` at the approved HEAD. Follow-up documentation commits are later local HEADs and are not covered by that decision. Formal G1 remains `NOT_PASSED`; production authorization remains `NONE`; Release 2 remains `NO-GO`.

### Post-runtime database review and MAJOR-02 correction (2026-10-16)

The raw functional run at code/test HEAD `73e4253b571fa45382af6f954f773e1eae5f91be` reported
45 passed, 0 failed, 0 skipped in 57.13s; its 22 selected node IDs include a MAJOR-02
parameterized node expanded to 24 cases. Database-reviewer identified a gap because sleep plus
task state did not prove the API reached the source-row-lock wait before revoke. Functional-test-reviewer
fixed this in code commit `a6263e4bafe69aedd14372f394d67da7b6fb3366` (linked record
`CHANGE_RECORD_082.md`) and reran all 24 variants: 24 passed, 0 failed, 0 skipped in 16.56s.
Each case observed the exact API SQL, a `Lock` wait on `transactionid`, and `pg_blocking_pids`
containing the revoke backend before the revoke transaction committed. Timeout cancels the
blocked query, rolls back and reports `NOT_RUN`. Database-reviewer confirmed the original finding
resolved. Silent-failure-hunter found no BLOCKER/MAJOR and confirmed the observer prevents a
false PASS; the review was read-only and did not rerun tests, and it noted the wait-event subtype
is not asserted. Static code-reviewer inspected 40 changed paths and found no BLOCKER/MAJOR or
direct regression. The separate explicit-COMMIT case passed under e2e-runner (1 passed in 14.74s);
restore passes remain in record 080. The full selected local evidence set is complete; a fresh
PM approved the exact reviewed HEAD `17900345c88237290c498d73b6f8849c265351d1`, and the reviewed range was pushed. This later documentation HEAD is not covered by that approval; no push of it is authorized here.

The ordered evidence assembly plan and per-item status are in
`docs/phase2/G1_EVIDENCE_PACKET_PLAN.md`. It separates local test-agent/GPT evidence for code push
from formal G1/release evidence; a host `psql` executable is not required for the focused suite.
