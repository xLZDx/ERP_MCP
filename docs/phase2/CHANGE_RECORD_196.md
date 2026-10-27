# Change Record 196 — serialize evidence admission with trust-registry revisions

## What changed

- `EvidenceTrustSnapshot.revision` and `VerifiedEvidenceRecord.trust_revision` now accept only a positive, canonical decimal PostgreSQL `bigint` value at the trust DTO and verifier boundaries.
- Both single-record and evidence-set registration carry the snapshot revision in the DB payload.
- The migration candidate stores that revision on evidence rows and requires the registration routine to lock the revision row `FOR SHARE` and compare it before acquiring the attempt, key, lifecycle, advisory, or global-fence locks.
- All seven trust-registry tables acquire the revision row `FOR UPDATE` in `BEFORE STATEMENT` triggers. Their existing after-row triggers still increment the revision transactionally.
- The revision row rejects deletion/reinsertion and any update except a one-step increase; truncation is also refused for the revision row and mutable outcome-version-floor policy.
- A stale verification now fails with stable code `EVIDENCE_REGISTER_TRUST_REVISION_STALE`; the test qualification specifies the race and lock ordering.

## Why

The verifier already returned a coherent snapshot revision, but the registrar dropped it. A policy, oracle, process-binding, key-scope, key-version, rotation, or revocation change could therefore commit after verification and before evidence insertion. Rechecking only current key validity/revocation did not cover changes to other trust inputs. A common revision lock now defines the boundary: trust writers lock it before trust rows; evidence registration locks and compares it before its own data locks and holds it through commit.

## Affected paths and contract

- `src/erp_mcp_private_writer/evidence_trust.py` and `src/erp_mcp_private_writer/production_evidence_verifier.py`: shared canonical revision validation.
- `src/erp_mcp_private_writer/postgres_evidence_registrar.py`: revision propagation for receipt and typed evidence registration.
- `db/phase2/027_private_writer_admission_schema.sql`: evidence revision column, seven trust-writer statement gates, stale-revision refusal, and helper ACL.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: stale-revision race and lock-order acceptance.
- `docs/phase2/S13_EVIDENCE_REGISTRATION_CONTEXT_DESIGN_2026-10-24.md` and `docs/phase2/S13_POSTGRES_ADMISSION_SCHEMA_DESIGN_2026-10-22.md`: supersede verifier-only/no-registrar checkpoint wording with current unqualified composition and trust-revision boundary.

## Evidence and verification state

- Source review confirmed the verifier returned `trust_revision`, while the registrar omitted it from its payload and database call. The SQL candidate had after-row revision bumps but no pre-mutation revision lock or registration-time revision comparison.
- Source-only change. Tests, checks, build, SQL parse, migration, database writes, staging, commit, push, and runtime qualification were not run. Candidate 027 remains unparsed, uninstalled, and ungranted. `S13-TRUSTED-VALIDATION-TIME-01` remains `NOT_RUN`.
- Current source SHA-256: `evidence_trust.py` `6CBC4017736BA0C4D8F489BC820C133EBC7356126DCF0B2C02A1710D88A6729E`; `production_evidence_verifier.py` `D26743AC5C9A3A9FE807214E28106666B6DADD457D8E478D5831044F32C5404E`; `postgres_evidence_registrar.py` `015B3DF56E38DC72956BBA762EDF0F9F25DCCD9DFEBA7782FFCC7F4690E63F7F`; candidate `027_private_writer_admission_schema.sql` `A6454CC9D435F6711AE4DE9BC00E7862B2AE2D6E3C202DFF257F28712B0695E5`; qualification plan `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` `B5E724FBD9CB829FDA59AB6F5FB91223D6FB78EDE4FB35EDEE6A93CF87AB9144`.
- Hashes are recorded after the source edits in this record are complete.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Technical owner for production trust-registry administration and validator policy is not established by the reviewed canonical project records. Next: finish source closure, then assign the snapshot-revision race and lock-order qualification to the functional/E2E test roles; use the database reviewer for exact PostgreSQL lock and ACL review after coding closes.
