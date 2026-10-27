# Change record 183 — exact caller scope authorization for private writer ingress

## Changes made in this turn

- Added `src/erp_mcp_private_writer/private_authorization.py` with immutable exact grants keyed by
  the verified OAuth client-ID/subject pair, binding that principal to tenant, company,
  organization, and lowercase base fingerprint. Empty, malformed, or mutable grant sets are
  rejected at construction.
- The authorizer requires the trusted writer ticket/permit verifier for new dispatch. It checks the
  exact client grant first, then invokes ticket and signed-permit verification; dependency errors
  or the bounded five-second verification deadline fail closed without including dependency text or
  credentials and before S13 admission.
- Historical outcome lookup checks the same client/scope grant but intentionally does not require a
  currently unexpired permit. The subsequent service lookup reads the exact immutable call identity
  from the authoritative S13 store and cannot dispatch or mutate. This lets a caller recover an
  already-admitted call after permit expiry without granting new physical work.
- Updated `private_ingress.py` to require the concrete configured authorizer on both routes and to
  map authorization failure to fixed 403/503 responses. Exported the implementation and its types.
- Updated the S13 design to distinguish the source candidate from configured, provisioned, or
  qualified runtime behavior.

## Why

The caller JWT proves an OAuth client identity and private-writer scope, but alone does not bind
caller-supplied `ApplyTicket` fields to a tenant or physical base. A signature on the dispatch
permit alone does not bind every ticket field either. Each endpoint therefore needs a client-to-scope
grant, and new dispatch also needs the S12 ticket/permit verifier. For lookup, the exact persisted
S13 identity is authoritative; imposing dispatch-time permit expiry on recovery lookup would prevent
legitimate status reconciliation.

## Security and operational boundary

- Grants are exact tuples with no wildcard matching and are copied into an immutable map. This code
  does not choose or provision the grant source; deployment must supply authenticated configuration
  from the approved IdP/service-ownership path.
- The injected ticket/permit verifier must be the trusted S12 authority. An absent, test-only, or
  untrusted verifier is not acceptable for a listener.
- The store's exact lookup remains responsible for matching every immutable identity field against
  a persisted admitted call. `NOT_ACCEPTED` or mismatch never triggers dispatch.
- No listener, client provisioning, database schema, grant, COM call, stage, or runtime was created
  or changed. This is source implementation only; runtime qualification and security review remain
  open.

## Verification and remaining work

- Manually reviewed the new authorizer and both ingress call paths against
  `ApplyTicket`, `DispatchPermit`, `PrivateWriterService.dispatch()`, and
  `PrivateWriterService.lookup()` source contracts.
- No tests, checks, build, listener, database action, migration, COM call, staging, commit, or push
  ran. Behavior is `NOT_RUN` pending the authorized functional/E2E phase after coding closes.
- After coding closure, the test roles must prove wrong-client/subject/scope denial, permit and ticket
  refusal, verifier outage, historical lookup after permit expiry, exact stored identity matching,
  and that lookup never calls dispatch. Specialist security and database review remain required.
- Accountable task owner: operator. Executor: Codex. Technical owner of IdP provisioning and the
  approved per-client scope-grant source is not established in the canonical sources inspected.

## Evidence

- `src/erp_mcp_private_writer/private_authorization.py`
- `src/erp_mcp_private_writer/private_ingress.py`
- `src/erp_mcp_private_writer/service.py`
- `src/business_ai_gateway/phase2/change_ledger/write_port.py`
- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md`
