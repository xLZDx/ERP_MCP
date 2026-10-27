# Change record 182 — bounded loopback private writer ingress

## Changes made in this turn

- Added `src/erp_mcp_private_writer/private_ingress.py` with authenticated POST routes for a
  ticket/permit dispatch and exact ticket/permit outcome lookup. It checks loopback peer and Host
  addresses, rejects duplicate authorization/content-type/JSON keys, caps UTF-8 JSON request bodies
  at 1 MiB, and uses strict typed request models before calling `PrivateWriterService`.
- The app refuses requests while the service is not ready, maps service failures to fixed error
  codes, does not retry dispatch, and returns only call identity/status fields needed by the caller.
- Exact lookup requires an injected `ExactCallLookupAuthorizer`; without one the ASGI app refuses
  construction. The callback must reconcile the ticket/permit with the authoritative stored permit
  and admission binding, validate the permit signature, and enforce caller/tenant ACL before the
  service reads durable call state. The signature alone does not bind every `ApplyTicket` field.
- Exported the app factory and recorded the loopback-first HTTP candidate in the S13 design.

## Why

ADR-0009 requires an isolated private writer ingress with caller authentication, and S13 requires
durable call-ID dispatch plus authoritative lookup. The candidate transport is loopback-only while
Tailscale interface ACL ownership and caller provisioning remain unknown. The factory creates an
ASGI app but does not bind a socket, launch a service, claim a serving epoch, or authorize a COM
write by itself.

## Security and operational boundary

- Both routes authenticate a verified JWT, fixed private audience and scope, plus an explicit
  client allowlist before reading the request body or accessing writer state.
- The peer address and Host must both be loopback IP literals. This app does not trust proxy headers
  or enable remote/Tailscale ingress.
- The dispatch route still relies on the writer port to verify the signed S12 ticket/permit, base
  fingerprint, current epoch, entitlement and COM-entry guard. The app is not a substitute for any
  of those checks or for the PostgreSQL transaction fences.
- `PrivateWriterService.lookup()` currently validates identity shape but does not perform that
  durable ticket/permit reconciliation and caller authorization. The explicit callback closes the
  HTTP exposure gap only when a trusted implementation is supplied; this turn does not provide that
  implementation.
- The ASGI app remains unwired. No command starts it; production or disposable use still requires
  accepted source/identity provenance, least-privilege grants, recovery readiness, an operational
  COM writer, and qualification evidence.

## Verification and remaining work

- Manually reviewed the route and parser source against `PrivateWriterService.dispatch()` and
  `.lookup()` signatures. No tests, checks, build, listener, service, database, COM operation,
  staging, commit, or push ran. ASGI/auth/parser behavior is `NOT_RUN`.
- After all coding is complete, `functional-test-reviewer` and `e2e-runner` must qualify wrong and
  non-loopback peers/Host values, duplicate headers and JSON keys, oversized/malformed bodies,
  malformed ticket/permit values, service-not-ready refusal, exact replay lookup, stale epoch,
  first dispatch and uncertain outcomes. A disposable runtime with no production source is required.
- A trusted exact-lookup authorizer must be implemented and reviewed before using the lookup route;
  it must permit historical lookup after expiry only when original signed admission is proven and
  the ticket/permit match the authoritative database record.
- Accountable task owner: operator. Executor: Codex. Ivan stack owns the host connection boundary;
  no human owner for IdP client provisioning, Tailscale ACLs, or the future writer-client identity is
  established in the inspected evidence.

## Evidence

- `src/erp_mcp_private_writer/service.py` — dispatch and authoritative lookup contract.
- `src/erp_mcp_private_writer/private_auth.py` — fixed JWT audience/scope and client allowlist.
- `docs/adr/ADR-0009-private-test-writer.md` — private-only ingress and qualification gates.
- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` — local HTTP candidate and
  explicit no-listener/no-runtime status.
