# Change Record 258 — Fence permit issuance against base barriers

Date: 2026-10-25

## Status

Candidate source-only correction. SQL parsing, migration application, database qualification, and runtime behavior remain unverified.

## What changed

- `private_writer_issue_permit_v1` now takes the namespace-8 physical-base fence, derived from the dispatch intent's immutable base fingerprint, after the namespace-2 switch fence and before namespace 7.
- The S13 issue-permit crosswalk now records this `2 → 8 → 7 → lifecycle → namespace 6 → rows` order and the purpose of namespace 8.

## Why

The accepted S13 design assigns namespace 8 to private-writer slot/barrier transitions and requires it before namespace 7 on private-writer paths. The candidate permit issuer previously took namespace 2 and namespace 7 but omitted namespace 8, so permit issuance was not serialized with a concurrent physical-base barrier transition.

## Evidence and limits

- Source contract: `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`, general rank rule and `issue_permit` crosswalk.
- Candidate migration SHA-256 after this change: `2BD2C3B6100B374FD7ECB051DF049CF68BDAAD2643DC101363A32B4FCA5EA845`.
- The fence uses `intent.base_fingerprint`, obtained by the existing dispatch-intent lookup before ranked locks; later locked intent validation remains in the function.
- No SQL parser, tests/checks, migration, database, staging, commit, or push was run.
- Candidate is not installed, granted, or runtime-qualified.

## Required qualification

After coding closes, test both serial orders between permit issuance and base-barrier transition, including stale/missing intent refusal and exact permit replay. Assert that the same base serializes, unrelated bases remain independent except for hash collisions, and any refusal leaves permit, record, checkpoint, and event state unchanged.
