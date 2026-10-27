# S13 versioned worker verification cutover

## Change

Documented that global verification-evidence replay belongs to the existing ledger `worker_role`,
not the private COM-writer login or evidence-ingest login. Specified an additive versioned
`verify_inconclusive_v1` contract and the qualification/grant sequence before routing the worker
adapter or revoking the old function grant.

## Why

The current `SqlChangeLedger` maps `verify_inconclusive` to caller class `worker`; migration 007
grants the legacy signature to `worker_role`. Migration 027's `verification_worker` is a signer
identity label, while its private writer and evidence-ingest roles have different capabilities.
The current global evidence-ID contract already exists in design but has no additive candidate API
or worker-call mapping. The owner and boundary must be explicit before implementing that cutover.

## Affected contracts and paths

- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`: existing worker API/spec.
- `db/phase2/007_change_hardening_a.sql`: current worker grant.
- `db/phase2/027_private_writer_admission_schema.sql`: candidate role separation; no new function
  was added in this documentation change.
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`: worker-specific v1 contract.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`:
  worker-only grant and qualification requirements.

## Decisions and verification state

The v1 routine must take the exclusive namespace-7 scope fence, then the namespace-6 global
verification-attempt evidence-ID lock before relation locks; exact replay is read-only and a
conflicting ID raises `VERIFY_EVIDENCE_ID_CONFLICT` (`P0001`) before counter/log/event changes. New
calls remain serialized with `recover_sweep` on the shared VERIFY counter. Namespace 2 is not added
unless the accepted worker policy explicitly requires verification to follow the writer switch.
The `SqlChangeLedger.verify_inconclusive` adapter now selects the worker-class v1 function only
when `private_writer_schema_enabled=True`; the default continues to call the legacy function. The
enabled path has no fallback, so it fails closed until the additive SQL function and worker grant
are present. No SQL function, role grant or migration was implemented here. This adapter routing
change is source-only and not verified; tests, checks, database operations and migrations are
`NOT_RUN`.

The focused read-only database review cites `sql_ledger.py:77,403-404`, migration 007 `:997`,
migration 027 `:17-25,139-140,3927-3960`, and existing design/qualification entries. No tests,
database session, or files outside `ERP_MCP` were used.

## Current-turn route implementation

Added `verify_inconclusive_s13` to the opt-in adapter specification with the exact candidate
signature `verify_inconclusive_v1(text,text,uuid,uuid) RETURNS jsonb` and caller class `worker`.
The existing method switches to it under the S13 schema flag and otherwise preserves the legacy
route. Since `invoke` calls only the selected specification, enabling the flag before the routine
and ACL exist fails closed. This focused code delta has not received the required code review or
functional/E2E qualification; no tests, checks, SQL, migration, database write, stage, commit or
push ran.

## Third-attempt exhaustion dependency

While tracing the current source helper, identified a further candidate write-set requirement:
`verify_attempt_internal` creates an own `FAILED_VERIFY_HALT` using a generated UUID in its
exhaustion branch after row/counter locks (`db/phase2/006_change_sweeps.sql:199-231`). The v1
routine must not call that helper unchanged. The source design and disposable scenario now require
an explicit hold UUID allocated before ranked locks and its namespace-6 key acquired with the
observation ID before row locks, then preserve current record/counter/optional-hold/event behavior
using that exact ID. This addition is a design update only; the SQL function remains unimplemented
and qualification remains `NOT_RUN`. A narrow database-reviewer pass is pending.

The actual `code-reviewer` agent follow-up found no material adapter-routing issue: flag-off selects the legacy spec; flag-on selects the worker v1 signature, role, UUID arguments and JSONB result; missing v1 fails through the selected function path without fallback; existing SQL error and JSONB decoding remain in use. This review did not cover SQL implementation or runtime. The agent's resolved model/effort were not exposed in its result. No tests/imports/DB actions were performed.

Final narrow read-only DB review of the verification-worker candidate found no remaining gap in the reviewed design/qualification slice: early lifecycle lock, preallocated hold/global IDs before rows, exact closed-counter no-change branch, and exact below-threshold/third-attempt event/result shapes are now explicit and match 012 source. Reviewer model/effort were not exposed. This does not accept the full S13 lock map, implement the v1 SQL function/ACL, or establish runtime qualification; all remain open.

## Candidate SQL implementation

Implemented `verify_inconclusive_v1(text,text,uuid,uuid) RETURNS jsonb` in candidate migration 027 with a worker-only grant. The implementation follows the current design for scope/lifecycle fences, change/evidence/preallocated-hold namespace-6 IDs, global log replay/conflict handling, and the exact counter/event branches. It is source-only and has not been SQL-parsed, installed, or run. Focused code and database reviews are pending; no tests or migration were run. This addition does not qualify the route or close the full S13 graph.

## Review findings and source-only remediation

Subsequent read-only code/lock-map review found that exact replay returned before locking and
rechecking the scoped record, a NULL observation changed legacy error precedence, and the common
transaction precondition did not reject an advisory lock held before entry. The candidate now
performs global foreign-owner conflict detection before business-row locks, locks/rechecks the
same-owner replay record before evidence validation and return, and preserves the legacy
`EVIDENCE_UNSIGNED` path for NULL observation after record/state validation. The common helper
inspects current-backend `pg_locks` before any ranked acquisition; it rejects all existing advisory
locks and all `change_ledger` relation modes except `AccessShareLock`, preventing a caller-held
namespace-6-to-7 inversion. Qualification includes these exact refusal/replay/precedence cases.

The recovery-race assertion is corrected: legacy `recover_sweep` does not take namespace 7, but
both paths lock the same record before the shared VERIFY counter, so that row is their serialization
point. This source correction remains unparsed and uninstalled. No tests, database operation,
migration, staging, commit or push ran; full lock-map review, measured ACLs and disposable
qualification remain `NOT_RUN`.

A subsequent focused code review found one remaining replay refinement: after the same-owner record
is locked and scope-rechecked, the logged generation must equal the locked record's current
`claim_generation`. The candidate now refuses a stale-generation replay as
`VERIFY_EVIDENCE_ID_CONFLICT/P0001` before evidence/counter lookup. The qualification plan includes
advancing the record generation and replaying the old observation; this is still `NOT_RUN`.

The focused code-reviewer and lock-map follow-ups confirmed the latest helper, lock order, NULL
precedence and stale-generation refusal with no remaining finding in that narrow source slice.
These reviews do not establish SQL syntax validity, installed/effective privileges, full lock-map
consensus or runtime behavior; those remain `NOT_RUN`. Reviewer model/effort were not exposed.
