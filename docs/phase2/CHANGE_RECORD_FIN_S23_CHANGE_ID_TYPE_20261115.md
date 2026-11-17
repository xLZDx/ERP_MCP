# FIN-S2.3 change record — require string change identifiers

Date: 2026-11-15
Task: FIN-S2.3 — Expose exactly the approved five model-facing tools

## Finding

Manual source review found that the tool adapter passed model input directly to `UUID()` in
the status, apply, rollback-proposal, and verify paths. Python's UUID constructor also accepts
integer and byte inputs, although the manifest contract declares `change_id` as a string. An
adapter that does not enforce its published schema could therefore accept a wrong wire type.

## Decision

Use one adapter helper that requires an exact string before parsing the UUID. Preserve the
existing UUID string parser behavior and keep all authorization, scope, and service checks
unchanged. A non-string value follows the adapter's fixed `SCHEMA_INVALID` path before service
dispatch.

## Verification and limits

This is source-level contract hardening. The focused adapter regression remains to be authored
by the test role and is `NOT_RUN`; operator rule 4 prohibits pytest and automatic checks.
FIN-S2.3 remains unaccepted until the verification gate is available.
