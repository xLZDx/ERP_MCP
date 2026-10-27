# Change Record 219 — freeze PostgreSQL writer-adapter configuration

## What changed

- Froze instance configuration for `PostgresAdmissionStore`, `PostgresEvidenceAttemptSource`,
  `PostgresWriterReceiptRegistrar`, `PostgresEvidenceKeyResolver`, `PostgresEvidenceTrustSource`,
  `PostgresOutcomeEvidenceProvider`, and `ProductionEvidenceVerifier` after construction.
- Instance reassignment, deletion, delete-then-reassign, and adding undeclared fields now fail with
  stable class-specific `AttributeError` codes. Pool references, timeouts, and injected verifier,
  source, and registrar dependencies therefore remain the values that passed constructor validation.
- Added `S13-DB-ADAPTER-CONFIG-IMMUTABILITY-01` to require mutation attempts to cause no pool,
  lookup, provenance, or evidence-source side effects.

## Why

The adapters validate bounded timeouts and depend on injected pools authenticated as narrowly
privileged PostgreSQL identities. Before this change, ordinary post-construction attribute
assignment could replace a validated pool/dependency or raise a timeout beyond its constructor
maximum. The transaction and trust boundaries need to preserve the validated configuration for the
life of each adapter.

## Affected contracts and paths

- `src/erp_mcp_private_writer/postgres_store.py`
- `src/erp_mcp_private_writer/postgres_attempt_source.py`
- `src/erp_mcp_private_writer/postgres_evidence_registrar.py`
- `src/erp_mcp_private_writer/evidence_key_resolver.py`
- `src/erp_mcp_private_writer/postgres_evidence_trust.py`
- `src/erp_mcp_private_writer/postgres_outcome_provider.py`
- `src/erp_mcp_private_writer/production_evidence_verifier.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

## Evidence and verification state

These seven Python modules were already untracked before the current edits; their prior worktree
provenance is not attributed to this turn. Hashes captured before this turn's edits were:

- `postgres_store.py`: `40F837809BD9600D9A8BFAF4B0A0E2E637B4DFDDF24073734052F23B0417B9AC`
- `postgres_evidence_registrar.py`: `6BD3772B4F7A3887EC07C67A0D2F4B7B5E40EE2E56CA31F6ECA1E1D004A036E1`
- `evidence_key_resolver.py`: `5556ED3F4623569E1C16010A0C3B4DB7C867BCD05274EBF3FB03056367AF6574`
- `postgres_evidence_trust.py`: `0C7D32AE8D4591F2A4C3CCCAD5D20B70A57DC8AE2EFA92B70DBEDB998F8C9DB2`
- `postgres_outcome_provider.py`: `11660F5F388CD12A2D9C7BCA5D525BEB34A7A8743F332A8354A8872E1DA883F0`
- `production_evidence_verifier.py`: `7CCF2EA7E95C23D98970DB9E2046A9A9DFCA435A182C15E332681F08A1E6E1CB`
- `postgres_attempt_source.py`: baseline hash was not captured before its edit.

Current hashes after the edits:

- `postgres_store.py`: `F9BB826FDE2893A2E3A87C82C51B1873CC8C88B2C594826087633F3A24895297`
- `postgres_attempt_source.py`: `E4A05D1D10EB6B481DECD4BE83A02EFE1A1F4BDE6BCCCDC000DD160D536E90D5`
- `postgres_evidence_registrar.py`: `CB1850C2B8ACD09C919FC6B11727BBE6A4842C4AD616102E7C5F234142A394CD`
- `evidence_key_resolver.py`: `0ED69A00402828923172EB6CDFEE48FF075E364010738B8624ECC3F18F8B4D46`
- `postgres_evidence_trust.py`: `076F2786D6F3E4E13E91BD3DFCAC39E35ADC6E1D2B3E63A675A3898B9C55BD5D`
- `postgres_outcome_provider.py`: `BCD1AD395AE7F8525759B1BB726656ED9D38E31D007987A74B9AE0D49D1361FA`
- `production_evidence_verifier.py`: `5F6FEE98F998237274889EA3C5A9501D5BD8C7ED300BB21093ECCB8F8E4BE7F9`
- Qualification prerequisite after later source closures: `90E9C89AAF2C81DC8BDE2909471ED92AC6D251EFBB62CFFE1C8C206F45764CF6`

Only source inspection and hash capture were performed. Tests/checks/build, PostgreSQL access,
database migration, COM, staging, commit, and push were not run. Qualification remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after coding closes, the functional/E2E roles
must attempt replacement, deletion, and re-addition for every listed field and prove zero dependency
calls on refusal; the Python/database reviewers then review the exact final source and dedicated
database-role boundaries.
