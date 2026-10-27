# Change record 332 — S12 outcome-version downgrade binding and trust-source request contract

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator; implementation owner: Codex; independent SQL/Python source review: database-reviewer and python-reviewer.
- This change follows `CHANGE_RECORD_331.md`; it does not replace or qualify that validator-build attestation change.
- Candidate migration 027 and the trust/verifier modules were already dirty shared-worktree artifacts. The precise original authorship of their baseline is not established. This turn changed only the source paths listed below and the qualification prerequisites.
- No tests, checks, builds, SQL parsing/migration, database mutation, production composition, staging deployment, commit, or push was performed for this change.

## Code change

The production evidence verifier now enforces the S12 v2 downgrade rule independently of the numeric outcome-version floor: if any oracle is pinned for the exact scope and operation, V1 evidence is rejected even if an inconsistent floor says 1. An absent floor still refuses. The immutable `TrustSnapshotRequest` now marks when a legacy V1 outcome needs the complete operation oracle policy. The PostgreSQL trust adapter passes this bit to candidate SQL; non-outcome records no longer request the complete oracle set. Migration 027 bounds the complete set at 16, fails closed on overflow, and keeps exact-oracle lookup behavior for V2/V3 records. The verifier also refuses multiple floors, off-scope floors/oracles, and oracle rows not requested by the caller, preventing an unexpected tenant or policy row from entering an accepted snapshot.

A database reviewer found the candidate evidence-ingest EXECUTE gate in migration 027: grants remain withheld until certificate-mapped identity isolation from the writer process, authenticated build provenance, and the cross-tenant disclosure boundary pass independent database/security review. The implementation preserves that gate; no evidence-ingest EXECUTE grants were added. The intended application call graph includes protected attempt/trust/evidence/ACK routines, but call-path presence is not authorization evidence.

## Acceptance and source reviews

- Added `S13-EVIDENCE-INGEST-EXECUTE-ALLOWLIST-01`, explicitly separating required calls from current authorization. Runtime EXECUTE remains disabled and effective privileges remain `NOT_VERIFIED`.
- Expanded `S13-PG-SESSION-IDENTITY-01` to cover the evidence resolver and barrier-ack trust/read/write paths and the independent-review prerequisite.
- Expanded `S13-PRODUCTION-EVIDENCE-VERIFY-01` with oracle-pinned V1 downgrade and bounded-complete-oracle-set cases.
- Python reviewer found no actionable issue in the final downgrade/request implementation. The follow-up confirmed strict boolean request semantics, v1-only complete-policy loading, rejection of off-scope/excess floors and off-scope/unrequested oracle rows, and exact-oracle lookup behavior.
- Database reviewer found no actionable SQL issue in the bounded complete-set query; review was source-only and did not parse/apply the migration or verify installed privileges.

## Current source hashes

- `src/erp_mcp_private_writer/production_evidence_verifier.py`: `9E7595AE13B32481319DA14806D886104CD89F39A539B0139E1F4147AE144973`.
- `src/erp_mcp_private_writer/evidence_trust.py`: `22DE4AF97C52CC23DAAC551F756AE9509FFF06672F6A59903BEF71754F103DAF`.
- `src/erp_mcp_private_writer/postgres_evidence_trust.py`: `80B380D55B9E3E1B2907C338A19287112473062199C4FAE5EF2992A96DE7840E`.
- `src/erp_mcp_private_writer/runtime_composition.py`: `D0236A4F98EEF6466801C2813BBCBC01A569E27E1767F7F644F3EE1477502E229`.
- `db/phase2/027_private_writer_admission_schema.sql`: `47CA78440BB25ED38034BFE89896868DB71DC6102B5EEF60719C332A3C38FB2A`.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `8F4F193BE9BC293DCD38FAE62E71E1BB869F1E7E78BB08CF2598CCDF9231C123`.

## Remaining work

1. Codex: finish source review/fixes and verify all trust-snapshot call/signature sites manually.
2. GPT-PM owns architecture adjudication; no new PM request was needed for this focused floor clarification. The existing validator decision remains recorded in `CHANGE_RECORD_331.md`.
3. After code closure, `functional-test-reviewer` and `e2e-runner` own the mapped downgrade, oracle-bound, stale-floor, missing-floor, overflow, and fail-before-registration cases in the approved disposable database.
4. Database/security review must clear the identity/provenance/cross-tenant gates before any evidence-ingest EXECUTE privilege is introduced. The operator remains accountable for external deployment authority.
