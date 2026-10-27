# Change Record 252 — derive S12 COM assignments from the approved payload

Date: 2026-10-25  
Status: source-only candidate; not tested, qualified, installed, staged, or committed.

## Why

com_manifest.py could hash property/value digests but provided no constructor proving those values
came from the canonical approved DraftPayload. A caller could prepare an internally consistent
manifest whose assignment values were unrelated to the approval digest held by the caller.

## Changes

- Added PayloadPropertyBinding to pair a reviewed COM destination with one canonical payload path,
  assignment kind, and COM value type.
- Added assignments_from_approved_payload. It accepts only the typed DraftPayload, enforces the
  currently qualified single-line shape, and requires every business-value leaf to map exactly
  once. Duplicate source or destination bindings, omitted fields, extra fields, and noncanonical
  values fail closed.
- Treated duplicate_override and expected_target_version as explicit control-only inputs rather
  than COM document properties.
- Made the PreparedComManifest constructor require the approved payload digest and exact target
  preimage. It recomputes the frozen payload digest before constructing any assignment manifest;
  POST and UNPOST require an empty payload and no assignments.
- Exported the new API from erp_mcp_private_writer.

## Limits and decisions

This change does not provide the reviewed 1C property crosswalk, discover metadata, authenticate
mapping/configuration, invoke COM, sign a DispatchReceipt, or authorize a write. Existing CT14
evidence proves a bounded clone capability and rights measurement; it does not establish the field
mapping for all DraftPayload values. Destination bindings remain deployment input and must come
from the exact disposable-clone crosswalk before an operational writer can use them. No
OneCWritePort implementation is enabled.

## Verification state

Source was inspected for the frozen payload shape and current manifest API. No tests, checks,
build, SQL parsing, migration, database operation, COM call, staging, commit, or push ran.
Functional behavior, exact clone bindings, and independent review are NOT_RUN.

Source fingerprints:

- src/erp_mcp_private_writer/com_manifest.py: FDCFDC6D5B79A3DBBD5EE23C6EE5F162FA9C934409F8EDD8CA3E6D00D235F5FE
- src/erp_mcp_private_writer/__init__.py: F714241EBF19628C09EE549185B913DE5DD16FE3EDD9926272A5F2C55BAFDB2A

## Affected paths

- src/erp_mcp_private_writer/com_manifest.py
- src/erp_mcp_private_writer/__init__.py
- docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md
- docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md
- docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md
- docs/phase2/OPERATOR_BACKLOG.md

## Next action

Extract the exact destination/source crosswalk from a read-only inspection of the authorized
disposable clone and its CT14 evidence. Then have the test-owning agents qualify full field
coverage and negative mismatch cases after all code work is complete. Do not enable COM dispatch
until mapping provenance, signer/witness identities, invocation guard, and receipt verification
are bound.
