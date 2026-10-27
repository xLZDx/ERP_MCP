# WP5 checkpoint signer domain allowlist

## Change

Added `checkpoint_signer` to the DPAPI-backed Ed25519 signer's exact message-prefix allowlist.
The role can sign only the existing versioned checkpoint envelope
`change-ledger-checkpoint|v2|...` and permit digest domain `change-ledger-permit|v1|...`.
Added `CheckpointSignerHexAdapter` to expose only that role through the checkpoint protocol's
lowercase-hex signature representation.

## Why

The trust snapshot and candidate S13 SQL schema accept a separately registered
`checkpoint_signer`, and the S13 permit routine requires that role. Before this change, the signer
constructor rejected the role because it was absent from `_ROLE_MESSAGE_PREFIXES`; checkpoint and
permit signing could not use the intended provider even with a correctly scoped key. The prefixes
match `CheckpointRecord.signing_payload()` and `permit_signing_payload()` in the existing contract.
The raw DPAPI signer returns 64 signature bytes, while checkpoint and SQL callers require 128
lowercase hexadecimal characters. The explicit adapter resolves that representation mismatch and
rejects other signer roles at construction.

## Affected contracts and paths

- `src/erp_mcp_private_writer/dpapi_signer.py`: role-to-message-domain allowlist.
- `src/erp_mcp_private_writer/checkpoint_signer_adapter.py`: checkpoint protocol signature adapter.
- `src/erp_mcp_private_writer/__init__.py`: public package export for composition callers.
- `src/erp_mcp_private_writer/evidence_trust.py`: existing trusted role vocabulary.
- `src/business_ai_gateway/phase2/change_ledger/checkpoint.py`: existing checkpoint and permit
  signing payloads.
- `db/phase2/027_private_writer_admission_schema.sql`: S13 permit signature role/domain checks.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`:
  `WP5-CHECKPOINT-SIGN-01` acceptance scenario.

## Decisions and verification state

The allowlist adds no key, changes no database grants, and does not provision or approve a signer.
Qualification must still verify raw Ed25519 output, lowercase-hex encoding through the adapter,
registered key/version/scope/validity/revocation, and rejection of all other role/prefix pairs.
Static source comparison only; tests, checks, key generation, signing, database work, migration,
COM calls, staging deployment, commit and push are `NOT_RUN`.

Baseline: the file was already untracked before this edit; its pre-edit SHA-256 was
`1331E299A2819B947B050EE38CCBBA923F2CEA5A5E37A31267C93675B5E10790`. No inherited content was
discarded or reset.

An actual focused static code review confirmed both exact prefixes and found no broad-prefix issue.
It identified that raw signature bytes still needed conversion to the checkpoint protocol's hex
string. `CheckpointSignerHexAdapter` was then added as a separate follow-up. A focused re-review
reported no material findings: it checked the exact signer type/role, checkpoint protocol shape,
64-byte length validation, lowercase 128-character encoding, and both signing domains. No tests,
checks, signer invocation, key operation, database operation, or runtime qualification was
performed. Source hashes at review: `dpapi_signer.py` SHA-256
`880F2D580FF6D0DF35D9F8776AB7B7F362F77D2EEF2E220AB267B8EE904B4A52`;
`checkpoint_signer_adapter.py` SHA-256
`399952A80848AEA0BD960C7C8FB9F192D77A89602237D247EA6C0C321E0776D4`.
The package export was then reviewed statically for import order; no reverse package-root import or
circular dependency was found. `__init__.py` SHA-256 at review:
`60A66E7BA867566107A43FDAF8D00B8636D9C5205E7EAC961FC63A8B524336DF`. No Python import was run.
