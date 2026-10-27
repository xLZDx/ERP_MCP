# Change record 186 — bind private-writer payloads to the approved digest

## What changed

Added `parse_writer_payload()` using the existing S12 proposal parser rules. Before durable
admission, `PrivateWriterService` now parses `CREATE_DRAFT` into the normalized typed payload,
requires empty payloads for `POST`/`UNPOST`, recomputes the CT2 payload digest with the ticket's
target version, and rejects a mismatch. The writer receives only the normalized dictionary used
for that digest.

## Why

The accepted writer-port contract requires the physical writer to canonicalize its payload and
match the approved digest. The service previously deep-copied any dictionary and passed it to the
writer without establishing that the supplied values were the approved payload.

## Affected contract and paths

- `src/business_ai_gateway/phase2/change/proposal.py` — reusable frozen-shape writer payload parser.
- `src/erp_mcp_private_writer/service.py` — pre-admission digest validation and normalized payload
  passed to the physical writer port.
- `src/business_ai_gateway/phase2/change/proposal.py`, `payload_digest()` — CT2 digest binds the
  typed canonical payload plus target version.

## Decisions and boundaries

- `CREATE_DRAFT` reuses the same field, decimal-normalization and organization-scope rules as
  proposal parsing; a digest mismatch refuses before store admission, invocation marking, or COM.
- `POST` and `UNPOST` must carry exactly an empty object, and their digest still binds the exact
  approved target version.
- `UPDATE_DRAFT`, OData writes, and any unapproved operation remain refused/out of scope.
- This does not provide the missing 1C field/property crosswalk, sign receipts, authorize a write,
  or enable the private service.

## Verification state

- Manually compared the parser, payload canonicalization, operation scope, and service call order.
- No tests/checks, build, SQL parsing, database/migration, COM, service/listener, staging, commit,
  or push was run. Behavioral acceptance remains `NOT_RUN`.

## Remaining acceptance and ownership

This closes the service-side approved-payload equality check only. A concrete COM adapter still
needs the authenticated disposable-clone crosswalk, operation manifest, writer identity, effective
rights, and an atomic 1C precondition. Those remain unverified; physical dispatch stays disabled.
The operator is accountable task owner; Codex is executor; the Ivan stack is the technical owner
of the existing host/connection boundary. Next: continue source closure without inventing a field
mapping, then run focused functional/E2E qualification only after coding is complete.
