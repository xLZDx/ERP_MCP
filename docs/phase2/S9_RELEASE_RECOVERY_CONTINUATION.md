# S9 release compatibility and recovery continuation

Baseline: dd1e41d8da54c3a905b1ac9e4090d797b99f5426. Scope: the remaining two bounded stories from SPRINT_S9_PLAN.md. Preserve the recorded acceptances for R2-US-043 and R2-US-044; historical PR #49 merged on the integration branch, as recorded by GitHub.

| Task order | Bounded criterion | Named evidence |
| --- | --- | --- |
| R2-US-045 | TC133: additive typed planning, compatible shadow comparison and refusal of stale or changed applied-file checksums | test_release_migration.py, test_release_sql_guard.py |
| R2-US-045 | TC134 and TC135: destructive or incompatible rollback refused; current revoked grants, credentials and attestations stay ineffective | test_release_rollback.py |
| R2-US-046 | TC136: incomplete, corrupted, orphaned, stale or foreign restore manifests fail closed | test_restore_verify.py |
| R2-US-046 | TC137: scoped export, per-column masking, formula neutralization and secret refusal | test_export_safety.py |
| R2-US-046 | TC138: retention and legal hold prevent a deletion plan where disallowed; allowed output is a plan only | test_retention_hold.py |

Current source already implements these paths as in-memory decisions. First map the tests to the current retained code and identify any uncovered behavior. Change only proven defects or missing evidence within the accepted scope. Runnable proofs are named offline tests after the sprint code is present. The SQL test scans the named files as text and executes no SQL. Keep each run bound to its revision and result.

Concurrency: decisions use their existing scope and current-state inputs; they do not acquire permission to execute. Retry: recorded migration versions require matching checksums and a revocation must remain effective. Crash between planning and any future execution: no planned action has an execution path in these modules. Qualification of an execution service must separately revalidate current authority and state.

Live migration, transport and restore drills, operational alert delivery, external storage and legal-hold enforcement remain product qualification. Keep G6-pre outside this bounded scope. No real deployment, restore, export of customer data or deletion.
