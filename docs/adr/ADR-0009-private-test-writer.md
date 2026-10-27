# ADR-0009 — Isolated private writer for disposable 1C qualification

**Status:** Accepted by explicit operator decision, 2026-10-22; implementation and qualification are incomplete.

## Context

The production 1C data plane is read-only by construction (ADR-0001). The accepted P5 assurance
scope nevertheless includes a separate disposable read/write clone for controlled test-only
historical/future write validation. The S12/S13/S14 contracts need a real persistence boundary and
physical COM call boundary to qualify stable call identity, crash recovery, stale-epoch rejection,
authoritative outcome lookup and quiescence. Existing clone rights evidence does not establish an
implemented or qualified service boundary.

The operator explicitly authorized the bounded private writer described in Scope Freeze §8.2 and
selected the licensed Ivan lane, a COM connector, and disposable clone `818HA_p2diff` as the first
qualification target.

## Decision

Build one separate private writer service for test-only disposable 1C clones. Bind it to loopback or
Tailscale and keep it off the public tunnel and model-facing MCP. The production read-only tool
inventory, gateway routes, and production 1C permissions remain unchanged.

The service contract must provide:

- stable call-ID idempotency and global call-ID non-reuse;
- stale lifecycle and serving-epoch rejection before physical invocation;
- authoritative lookup by the original call ID after any uncertain response;
- a complete quiescence barrier that retains holds for unresolved calls;
- separate bounded PostgreSQL transactions that never span COM I/O;
- exact signed S12 evidence and T16 recovery authorization before terminal recovery;
- an isolated physical COM boundary using only the least-privilege `CT14Писатель` identity.

The only approved 1C operations are create draft, read back, post, and unpost as separate governed
changes. Hard delete, administrator credentials, arbitrary caller-provided URLs/code, generic COM
execution, production or real-company writes, and registration as a public MCP mutation tool are
out of scope. Start on disposable `818HA_p2diff`; any additional target must be positively identified
as a marked disposable clone before a call is possible.

## Security and qualification gates

- Base identity and configuration fingerprint are checked at the service boundary; a mismatch
  refuses before COM.
- The selected loopback/Tailscale ingress authenticates each caller and enforces an explicit
  least-privilege ACL. Disposable qualification proves both an authorized call path and refusal of
  unauthenticated/unauthorized callers before admission or COM.
- PostgreSQL admission and the physical COM writer are separate trust boundaries. SQL fencing alone
  does not prove the COM barrier; COM evidence alone does not prove durable admission or database
  grants.
- A call that may have entered COM is never retried with a new call ID. Missing, ambiguous, stale,
  or contradictory evidence leaves the call unresolved and its hold in place.
- Runtime admission remains disabled and lifecycle remains `NOT_READY` until the disposable
  PostgreSQL and physical COM acceptance suites, least-privilege review, and applicable security,
  reliability, and database reviews pass on the exact candidate.
- The disposable service must be absent from the production process/tool/package inventory and must
  refuse any production source/base identity.

## Consequences

- This is a narrow test/assurance rebaseline for `S13-PRIVATE-WRITER-1`; it does not lift the
  production scope freeze or promote the deferred production write plane.
- PostgreSQL schema, adapter, authenticated process binding, grants/RLS, physical COM implementation,
  tests and runtime qualification are still required. No service or readiness transition is implied
  by this decision record.
- Production DoD D5 remains unchanged. A separate non-production D19 gate records writer isolation
  and disposable qualification.
- Technical host/connection ownership is the Ivan stack (`ERP_MCP_Ivan_Stack`); the operator is the
  accountable task owner and Codex is the local executor. No individual human contact for the future
  writer implementation is named.

## Traceability

- Scope Freeze §3.6 and §8.2
- P5 controlled disposable assurance scope in `docs/MASTER_PLAN.md`
- `S13-PRIVATE-WRITER-1` in `docs/REQUIREMENTS_TRACEABILITY.md`
- S12 freeze, S13 PostgreSQL admission design, S13 Ivan writer design, and CT14 clone evidence
