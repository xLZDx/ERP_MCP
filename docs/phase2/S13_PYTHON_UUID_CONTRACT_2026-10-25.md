# S13 Python UUID contract

## Goal

Keep Python-side canonical UUID admission consistent across the private-writer service, PostgreSQL adapters, and trusted process snapshots. Process-instance IDs must be lowercase canonical nonzero RFC UUIDs with an RFC variant and a supported version (1 through 8). Other ledger identities remain lowercase canonical nonzero UUIDs without imposing a version policy.

## Non-goals

This does not change SQL constraints, authorize a schema install, establish effective database grants, qualify process identity, or enable a COM writer. It does not constrain opaque domain references to UUIDs.

## Design

Add a dependency-light S12/S13 UUID contract module with separate predicates for generic canonical nonzero UUIDs and process-instance UUIDs. Replace duplicated Python predicates at service admission, receipt registration, trust snapshot validation, PostgreSQL result decoding, and the S12 invocation context with the shared functions. Ticket/permit comparison requires exact canonical text; a UUID-equivalent alternate spelling is not normalized into a match. Keep each caller's existing stable error code and validation order. SQL retains its matching database-side constraint because database entry points must reject invalid input independently.

## Failure modes

Wrong type, malformed text, uppercase/noncanonical text, nil UUID, unsupported process version, or non-RFC process variant is refused before the caller's existing external operation. No UUID is normalized into a different identity. No exception text from parsing is exposed.

## Rollout/rollback

Source-only and additive. Call sites retain their current acceptance behavior; rollback is a source revert. The migration candidate remains uninstalled and ungranted. No runtime rollout is authorized by this change.

## Test plan

After all in-scope coding closes, functional-test-reviewer maps canonical/lowercase, nil, malformed and unhashable request elements, version/variant, exact ticket/permit comparison, and valid-control cases to the S13 identity gates. Database review separately compares Python predicates with the candidate SQL constraints. Until then all runtime and test evidence remains `NOT_RUN`.

## Unknowns

The live database role, installed schema, effective grants, and host-attested process IDs remain unverified. The accepted process UUID version range is sourced from S12/S13 process-identity design; the valid per-host generation mechanism is still awaiting licensed-lane qualification.
