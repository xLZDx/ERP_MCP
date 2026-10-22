# Change record: validate private-writer identity field types

Date: 2026-10-22  
Scope: fail-closed validation of S13 private-writer admission input.

## What changed

- Hardened `src/erp_mcp_private_writer/service.py` so malformed runtime values in the frozen `ApplyTicket` and `DispatchPermit` dataclasses return stable `ServiceError` codes before any admission-store call.
- Validate the operation and UUID-bearing IDs are strings before membership/UUID parsing, require integer (not boolean or float) generation and epoch fields, and type-check optional target/version/repair fields.
- Require tenant, company, and organization identity values to be non-empty strings before constructing the durable `CallIdentity`.

## Why

Python dataclass annotations do not enforce field types at runtime. An unhashable operation value could otherwise raise a raw `TypeError` during allowlist lookup, while values such as `1.0` can compare equal to integer `1`. The coordinator boundary should refuse malformed identity values deterministically before the durable store sees them.

## Contracts and paths

- Supported operations remain the frozen S12 set `CREATE_DRAFT`, `POST`, and `UNPOST`; `UPDATE_DRAFT` remains refused.
- This change validates input shape only. It does not implement durable admission, a PostgreSQL adapter, trusted key loading, a COM writer, or runtime authorization.
- Errors remain fail-closed; no automatic retry or external write is introduced.

## Verification state

- Manual source review only. Tests, checks, builds, CI, migrations, database writes, COM calls, service restarts, and deployments were not performed for this code change.
- Required functional/E2E verification remains `NOT_RUN` and must be performed by the designated test roles after in-scope coding is complete.

## Ownership and next step

- Accountable task owner: operator; executor: Codex.
- Next step: continue the durable admission/fence implementation only after the complete SQL grant and lock-order contract is resolved; keep lifecycle `NOT_READY` until the real boundary is qualified.
