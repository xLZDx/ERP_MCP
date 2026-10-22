# Change record: Add S12 trusted identity snapshot verification

## Change

- Added `src/business_ai_gateway/phase2/change/trust_registry.py` with exact-scope signer registrations, explicit key versions and rotation history, validity/revocation checks, and a fail-closed verifier for S12 dispatch receipts, outcome evidence, and completion proofs.
- Added supervisor-signed process-instance bindings for service ID, authenticated host ID, host boot UUID, OS PID, and process creation time; receipt and completion verification require the corresponding process binding.
- Exported the reference API from `business_ai_gateway.phase2.change`.
- Added a dated lesson describing why a signature check without a trusted identity and scope registry does not authorize evidence.

## Why

The S12 evidence envelope module validates canonical bytes, role labels, scope fields, and signatures against a supplied public key, but its own module contract states that it does not establish trusted identity or write authority. S12 requires authorization to resolve `(key_id, key_version)` to a scoped service/host identity and requires the writer process instance to be authenticated by a trusted host supervisor.

## Contracts and paths

- `src/business_ai_gateway/phase2/change/trust_registry.py`
- `src/business_ai_gateway/phase2/change/__init__.py`
- `docs/commits/2026-10-22-s12-trusted-identity-verification.md` (this record)
- `core/LESSONS_LOG.md`
- Signer registrations authorize an explicitly enumerated, nonempty set of exact tenant/company/organization/base tuples; wildcard scope is unsupported.
- All evidence must bind to a `DispatchAttempt`; outcome and completion evidence may additionally bind to a verified dispatch receipt.
- Process-instance attestations use a separate domain-separated payload and a `completion_supervisor` key registered to the same host.

## Decisions and limits

- Fail closed for unknown keys, revoked/out-of-validity keys, mismatched role/service/host/scope, invalid process bindings, and signature mismatch.
- Keep the registry snapshot immutable after construction; its authenticated source/provider is outside this module and is not implemented here.
- Keep the implementation explicitly `EVALUATION_ONLY`: it uses the repository's non-constant-time test-lane Ed25519 primitive and is not approved for real signer keys or production evidence.
- Do not generate, export, print, or store any private key in this change. Licensed-host D9/D10b provisioning and public registry publication remain later WP5 work.

## Verification state

- Source implementation only. No tests, checks, builds, CI, migrations, database access, key generation, network calls, service starts, or deployments were performed.
- Runtime identity-provider integration, authenticated registry persistence, host supervisor attestation generation, audit-grade cryptographic-provider selection, and functional/E2E qualification remain **NOT_RUN**.
- The existing `evidence.py` validation and signature helpers remain unchanged; this module is a new authorization layer and its enforcement at every state-changing consumer is not yet wired.
- The first exact-patch review found an omitted supervisor scope check and two documentation/immutability corrections. The revised helper now receives the evidence scope and applies it to supervisor registrations; this is source-level correction only, and a fresh exact-patch review is pending.
