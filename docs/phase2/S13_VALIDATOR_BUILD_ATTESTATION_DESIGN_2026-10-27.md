# S13 validator build-attestation design

Date: 2026-10-27. Status: source contract approved by GPT-PM for implementation; no trust-root,
policy, deployment, or production approval is implied.

## Goal and non-goals

Prevent the evidence registrar from treating a shape-valid `build_id` and matching caller-selected
`policy_id` as proof of the validator that is actually executing. Implement an independently
testable signed-attestation verifier and a default-disabled production composition gate. Do not
invent or provision an issuer, Ed25519 root, CI authority, service account, certificate mapping,
deployment identity, or runtime artifact measurement source.

## Current behavior and options

`postgres_evidence_registrar.py` accepts any object with
`load_current_approved_build()`; it checks the returned 64-character lowercase digest and equality
to a configured policy ID. An injected fake can satisfy these checks without proving a signature or
the executing image. GPT-PM returned an exact `REQUEST_ID`-correlated adjudication for request
`31d04c5c-7a8e-4bf4-8a46-7c8dcf7374c3` in PM Bridge project `erp_mcp`:

1. Defer all verifier code until external inputs arrive. Safe but unnecessarily blocks independent
   source development.
2. Implement the strict verifier and production gate now, but keep composition unavailable until
   externally authorized trust root, policy and deployment identity are actually supplied. This
   option was recommended and accepted for source implementation.

## Design

The verifier consumes a bounded, canonical versioned envelope with a distinct domain
`ERP_MCP_R2:S13:VALIDATOR-BUILD-ATTESTATION:v1\n`. The Ed25519 signature covers schema version,
issuer and key identity/version, policy identity/version, derived content-addressed build ID,
measured artifact digest, immutable source revision, authenticated build-provenance digest,
component, deployment and environment IDs, issue/not-before/expiry times, and unique attestation ID.
Canonical JSON rejects duplicate/unknown/missing fields, floats, noncanonical UTF-8/timestamps and
oversized/deep input. `build_id` is derived from a domain-separated canonical tuple of artifact,
source, provenance and component identity. The verifier checks the exact pinned public-key version,
policy authorization, current revocation state, bounded validity interval using authenticated UTC
time, and equality with a separately measured executing-artifact/deployment identity. The trust
snapshot and runtime measurement must be no more than three seconds old at validation. Before each
evidence insert, the registrar reloads and re-verifies the current attestation; a changed policy,
revision, build, deployment or attestation refuses before opening the database transaction. A signed
claim alone is insufficient to prove the executing code.

Only a verified result may reach `PostgresWriterReceiptRegistrar`; raw caller-provided build or
policy strings are not authority. Test roots and synthetic artifacts live only in a separate
disposable-test source. Production composition requires concrete host-authorized trust, policy,
clock, revocation and runtime-measurement sources, the dedicated evidence-ingest database identity,
and the already-matched evidence dependency graph. No simple boolean, environment switch, or
`is_test_double` flag confers production authority. Until the host sources and approvals exist,
the production gate returns unavailable and evidence insertion remains unreachable.

## Failure modes and response

Missing/ambiguous source, root, policy, clock, revocation or measured artifact; invalid signature;
unknown/revoked key or attestation; expired/not-yet-valid assertion; wrong image/source/component,
deployment or environment; stale policy; malformed or over-limit bytes; timeout; and provider
failure all fail closed before evidence `INSERT`. No unverified cache, environment build ID,
filename, image tag or fallback identity is accepted.

## Rollout, rollback, verification

This is source-only. The implementation is inert until actual host-authorized sources exist; do not
enable runtime composition, install migration 027, mint production keys, or provision the remote
host. Functional-test-reviewer owns canonical golden vectors, signature and negative matrices,
and tests proving fake providers/test roots cannot enter production composition. Security- and
database-reviewers inspect exact final source/hash. Rollback is to retain the existing unavailable
gate; never restore the shape-only provider as production authority.

## Unknowns and owners

Codex owns implementation, test coordination and source reconciliation. GPT-PM owns architecture
adjudication. The operator is accountable for deployment authority. The externally authorized
Ed25519 root and lifecycle, issuer, approved policy/revocation rules, actual build provenance
authority, measured artifact source, deployment identity/certificate mapping, authenticated clock,
and effective privileges are `NOT_ESTABLISHED` / `NOT_VERIFIED`; they are not inferred from this
design or from synthetic tests.
