# Change Record 414 - split S1.2/S1.3 scoped reads into migration 029

## Scope and provenance

This change separates the scoped read routines from migration 028. Migration 028 remains the S1.1 refusal-registry and budget-precheck parity delta. The new numbered migration 029 supplies the previously described S1.2 budget snapshot and S1.3 operator/auditor list/status routines, using the definitions already present in the local implementation sidecar.

## Rationale

The selected disposable PostgreSQL acceptance run applied the numbered chain through 028 and then failed because `list_inflight`, `operator_status`, and `budget_snapshot` were absent. The source-side change record described those routines as implemented, but they were not in the tracked migration chain. Treating this only as a test-scope issue would leave S1.2/S1.3 unavailable on a clean installation.

## Changes

- Added `db/phase2/029_scoped_operator_reads.sql` with the three scoped, read-only SECURITY DEFINER functions, explicit `ledger_owner` ownership, PUBLIC revocation, and operator/auditor execute grants.
- Left migrations 027 and 028 untouched. Migration 029 is additive and transaction-wrapped; routine replacement is idempotent.
- Preserved the existing scope checks, operator/auditor membership check, bounded pagination, minimized status projection, and advisory-only budget snapshot behavior.

## Safety and acceptance limits

This is a migration source change only. It has not been applied to a shared database, production, or a real 1C source. Disposable migration application, role-grant checks, tenant/company isolation, and the focused S1.2/S1.3 SQL journeys remain pending the assigned e2e-runner's exact output. Real accounting-period source qualification remains separate and unqualified.

## Decision

Use a separately numbered additive migration instead of extending migration 028 or dropping the existing assertions. This preserves the existing S1.1 migration boundary and ensures a clean numbered migration chain installs the routines that the approved S1.2/S1.3 contracts and implementation record already describe.

## Review follow-up

database-reviewer flagged a possible fail-open condition if caller_role() returned NULL in the in-function role checks. Both list_inflight and operator_status now reject who IS NULL before evaluating role membership. The reviewer confirmed that this clears the sole finding. The new migration still requires its disposable PostgreSQL functional acceptance; review did not execute SQL.

## Disposable SQL acceptance follow-up

The assigned e2e-runner reports the S1.1 parity/idempotence and S1.2/S1.3 scoped list/status tests passing after migration 029 was added: 2 passed in 27.37s and 2 passed in 13.40s respectively. The scoped suffix script also passed on disposable PostgreSQL 16.14 with no writer/dispatch/READY path. These are current working-copy results; repeat at the committed candidate head before recording final S3.1 acceptance.
