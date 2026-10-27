# Change Record 255 — Align physical barrier boot-ID validation

Date: 2026-10-25  
Status: source-only; behavior and database qualification not run.

## Why

The candidate S13 table `change_ledger.writer_barrier_acknowledgements` requires
`host_boot_id` to be a canonical lowercase RFC UUID with a defined version and variant. Before
calling the injected barrier-ack verifier, `PrivateWriterService` checked only that this field was
a non-empty string. That allowed malformed values to cross the Python verifier boundary and defer
the refusal to the later SQL adapter.

## Change

- Replaced the non-empty string check with the shared canonical process-instance UUID predicate.
- This matches the UUID shape already enforced by the candidate acknowledgement table and keeps
  malformed signed acknowledgement identities out of the verifier/store path.
- No COM or database behavior was invoked or changed.

## Evidence and verification

- `src/erp_mcp_private_writer/service.py`: barrier acknowledgement validation now uses
  `_is_canonical_process_instance_id(acknowledgement.host_boot_id)` before verifier invocation.
- `db/phase2/027_private_writer_admission_schema.sql`: `writer_barrier_acknowledgements.host_boot_id`
  uses the lowercase UUID/version/variant pattern.
- `src/business_ai_gateway/phase2/change_ledger/uuid_contract.py` defines the shared rule as
  canonical nonzero UUID text, RFC variant, and version 1–8.
- `src/erp_mcp_private_writer/service.py` SHA-256 after this edit:
  `1C215576352B65B43004BAE137B369F40564CE19457CC1A29CACD1D6FBE76A31`.
- Tests/checks, SQL parsing, migration, database operation, COM operation, staging, commit, and
  push: `NOT_RUN`.

## Acceptance follow-up

Functional/E2E qualification must prove malformed, nil, wrong-version, wrong-variant and valid
RFC UUID boot IDs are refused/accepted before the verifier call as appropriate. The candidate
schema still requires independent source review and disposable qualification before installation.
