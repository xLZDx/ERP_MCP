# Change record: Add the S13 private writer coordinator contract

## Change

- Added the private-only `erp_mcp_private_writer` package with a typed call identity that includes the full tenant/company/organization tuple, durable admission-store protocol, fail-closed dispatch coordinator, authoritative lookup contract, and bounded quiescence-barrier orchestration.
- The coordinator invokes the injected `OneCWritePort` mutation only for a newly admitted call owned by the current service instance. `dispatch()` performs live writer prechecks before its durable-admission replay branch; callers can use the separate authoritative `lookup()` method without writer availability. Existing or uncertain calls are never physically dispatched again; writer exceptions and persistence uncertainty never trigger a retry.
- Updated the S13 design state to distinguish implemented coordinator code from the unimplemented PostgreSQL adapter/listener and unqualified S14 COM behavior.

## Why

The approved writer decision requires a private licensed-lane service with stable call-ID handling, stale-epoch admission, outcome lookup, and a quiescence barrier. This is the service-boundary code layer that can be written before database migration qualification and physical COM integration.

## Contracts and paths

- `src/erp_mcp_private_writer/__init__.py`
- `src/erp_mcp_private_writer/service.py`
- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md`
- `core/LESSONS_LOG.md`
- `docs/commits/2026-10-22-s13-private-coordinator.md` (this record)
- The public/read-only gateway does not import or register this package.
- `AdmissionStore` implementations must enforce the common mutation fence and epoch atomically, use a fresh top-level transaction per method, and verify terminal evidence before recording it. Those adapters do not exist in this change.
- No COM/OData/network implementation, HTTP listener, migration, readiness transition, or deployment is included.

## Decisions

- Persisted identity excludes the transient service process instance so an identical retry after restart resolves to its original durable record. The accepted record binds the winning instance separately; only that instance may mark invocation or persist the result.
- An existing call ID with a different immutable tuple must be refused by the durable adapter. A stale epoch must be rejected at atomic admission.
- The durable admission response supplies the database-bound dispatch CAS identifier; invocation and terminal evidence operations require that exact identifier rather than accepting a caller-provided CAS reference.
- The immutable call identity includes organization explicitly; it does not rely on an indirect permit-digest binding to detect cross-organization reuse. Barrier polling must preserve the exact original pre-barrier call set.
- A call remains unresolved if the process crashes or loses the response after invocation may have started. A timeout after confirmed barrier closure returns `CLOSED_WITH_HOLD`; timeout while establishing closure raises `BARRIER_OUTCOME_UNKNOWN` and does not establish closure or quiescence. Uncertainty never clears a hold.
- Keep lifecycle recovery refused and `NOT_READY` until the all-path fence, effective grants, recovery evidence, and independent qualification are established.

## Verification state

- Manually reviewed the new coordinator against the S13 service design and existing `ApplyTicket`, `DispatchPermit`, and `OneCWritePort` interfaces. A local code-reviewer found and this change fixed omitted organization identity, unbounded adapter waits, and barrier polling that could replace the initial call set.
- No tests, checks, builds, CI, migrations, database writes, COM calls, or service starts were run. The concrete store and writer adapters are not wired, so runtime behavior is **NOT_TESTED** and the service is not operational.
- GPT-PM approved the preceding exact patch for one local commit (request `2406125a-9d45-4dbb-905c-87a3fd7933f6`; 0 BLOCKER, 0 MAJOR, 3 MINOR). The three findings concerned replay-precheck wording, the distinction between a timeout establishing closure and a timeout after confirmed closure, and this record's incomplete path inventory. Those documentation statements are corrected here. The earlier approval does not cover this revised patch; a fresh exact-patch review is pending before local commit. No runtime or test readiness follows from either review.
