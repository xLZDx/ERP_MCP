# Change Record 213 — freeze complete target rows in S13 hold plans

## What changed

- `private_writer_open_hold_v1` now captures and rechecks each complete `targets` row for the requested base, instead of comparing only `base_fingerprint`.
- `check_anchor_v1` now captures and rechecks complete target rows across the bounded scope before applying hold updates or inserts.
- The open-hold helper now validates `p_base IS NOT NULL` before scope checks, ranked locks, or table access, matching the stable input-refusal contract.
- Updated the disposable qualification contract to mutate target status/epoch while a candidate waits for ranked locks and require `LOCK_PLAN_STALE` before DML.

## Why

The previous candidate plan could see the same base identifiers before and after the lock wait even if a target row's status, class, organization or epoch changed. Full-row comparison makes every planned target mutation visible as a stale plan and keeps the candidate decision tied to the exact registry snapshot it inspected. Validating the null-base refusal before `assert_scope` also ensures this malformed-input path does not perform a scope table read first.

## Evidence and verification state

- Code: candidate-only `db/phase2/027_private_writer_admission_schema.sql`, `private_writer_open_hold_v1` and `check_anchor_v1`.
- Qualification contract: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, `S13-OPEN-HOLD-RANK-01` and `S13-ANCHOR-CHECK-RANK-01`.
- Candidate migration SHA-256 after this change: `04985D4708F5B5ADF81D0C4A88EECA6F6515145CEF96F2272AFFBB9F58A3FFD7`.
- Source inspection only. No SQL parse, test/check/build, migration, database operation, staging, commit or push was run. Candidate remains uninstalled/ungranted; qualification is `NOT_RUN`, effective grants are `NOT_VERIFIED`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue the S13 source/ACL closure; once coding is complete, have the database reviewer inspect row effects, lock ordering and unique-conflict behavior, then have functional/E2E roles qualify target-row changes and stale-plan no-write behavior in the approved disposable database.
