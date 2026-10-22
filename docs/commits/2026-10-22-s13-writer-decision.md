# Change record: record the S13 private-writer decision

Date: 2026-10-22  
Scope: S13 writer-boundary design and ownership; documentation only.

## What changed

- Updated `docs/phase2/S13_WRITER_BOUNDARY_CLAIM_AND_RECOVERY_CONTRACT_2026-10-17.md` to record the operator's selected implementation: a private COM write service on Ivan's licensed lane, first against the `818HA_p2diff` clone, bound to loopback/Tailscale and excluded from the public tunnel.
- Replaced the stale statement that no technical owner/channel had been identified. The operator is the accountable task owner; the Ivan stack, including scheduled task `ERP_MCP_Ivan_Stack`, owns the host/connection boundary; Codex is the implementation executor.
- Kept the acceptance gate explicit: the selected boundary is not yet qualified. Clone evidence must establish single-use call-ID consumption, idempotency, stale-epoch rejection, authoritative outcome lookup, and a quiescence barrier before admission can be enabled or S13 can pass.
- Preserved the existing recovery fail-closed rules, the migration lock-order review requirement, and the prohibition on changing migrations 022–024 in place.

## Why

The operator's 2026-10-22 decision supersedes the older 2026-10-17 ownership/selection gap. Leaving the old text uncorrected could make later work ask for a decision already made. The decision selects a local implementation path; it does not prove runtime behavior or authorize a shared ERP write, staging, or production action.

## Contracts and paths

- Existing S12 single-use dispatch claim and call identity remain authoritative; the private writer must consume that identity rather than create a parallel authorization claim.
- No PostgreSQL transaction spans physical COM I/O.
- Recovery stays `NOT_READY` while an accepted call is unresolved or the boundary cannot prove quiescence.
- The first qualification target is the disposable `818HA_p2diff` clone on the Ivan lane.

## Verification state

- Reviewed the changed design text against the operator decision and the existing S13 claim/recovery contract.
- No tests, checks, builds, migrations, key generation, COM calls, service changes, deployments to a pre-production environment, or production actions were run for this documentation change.
- The COM boundary's actual behavior remains `NOT_VERIFIED`; required clone qualification remains open.

## Ownership

- Accountable task owner: operator.
- Technical owner of host/connection boundary: Ivan stack, as assigned in the operator's 2026-10-22 instructions and described in `docs/phase2/artifacts/REMOTE_1C_HOST_STACK_2026-10-11.md`.
- Executor: Codex.
- Next action: implement and qualify the private writer contract against the disposable clone; preserve fail-closed state until the required evidence is recorded.
