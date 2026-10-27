# Change record 243 — S13 evidence scope before verifier-key locks

## Change

In candidate migration `db/phase2/027_private_writer_admission_schema.sql`, `operator_resolve_v1` now scopes all five pre-fence evidence reads and all five post-fence evidence re-reads by the requested `tenant_id` and `company_id` as well as `evidence_ref`. Both pre-lock scans that derive verifier signer-key locks from the five supplied references apply the same scope predicate. `private_writer_record_recovered_terminal_v1` scopes its dispatch-attempt hint lookup by the supplied identity, then scopes the receipt join, four supplied evidence reads, and both verifier-material scans by the attempt's tenant and company. `private_writer_record_verified_success_v1` applies identity scoping to the attempt hint, tenant/company scoping to the three evidence reads before and after fences, and the same scope to both verifier-material scans. `private_writer_record_recovered_not_invoked_v1`, `private_writer_record_terminal_v1`, and `private_writer_attach_recovered_receipt_v1` apply identity scoping to the attempt hint and tenant/company scope to both receipt reads.

## Why

`private_writer_evidence.evidence_ref` is globally unique, while each evidence row also carries tenant and company scope. Looking up a foreign-scope reference globally allowed terminal paths to observe that row and derive verifier-key locks from its signer material before the later scope-binding comparison. Scope-bound reads make a foreign reference indistinguishable from the corresponding absent reference within these paths and prevent foreign evidence from influencing lock acquisition.

## Qualification contract

`S13-OPERATOR-RESOLVE-01` now requires a disposable wrong-scope case for each evidence-reference class used by the path. A reference registered for another tenant or company must yield the same sanitized refusal class as the corresponding absent reference, disclose no foreign row details, acquire no verifier-material lock derived from the foreign row, and leave all row and event snapshots unchanged. This is source-only acceptance; qualification remains `NOT_RUN`.

## Evidence and provenance

- Candidate schema: `db/phase2/027_private_writer_admission_schema.sql`, the six private terminal/recovery evidence consumers and their verifier-key lock-plan queries.
- Evidence table: `change_ledger.private_writer_evidence` has a globally unique `evidence_ref` and separate non-null `tenant_id` and `company_id` columns.
- Reference producer: `src/erp_mcp_private_writer/postgres_evidence_registrar.py`, `PostgresEvidenceRegistrar.evidence_ref` composes the immutable record type and calculated digest.
- Qualification prerequisite: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, `S13-WRITER-EVIDENCE-SCOPE-01` and `S13-OPERATOR-RESOLVE-01`.
- Candidate migration SHA-256: `C93EB060D1D214E30E3F9E520379056C9A1C90C5455D8AA719AC444E5453B288`.
- Qualification prerequisite SHA-256: `48FD43CBB4570CDBC0ABA66631F3129782A7603A6559B914B328922D916E5E0E`.
- Repository HEAD: `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`.

## Verification state

- Manual source/schema/registrar comparison only. No tests, checks, SQL parser, migration, database operation, COM call, stage, commit, or push ran.
- Candidate migration remains uninstalled and ungranted. Effective grants and runtime lock behavior remain `NOT_VERIFIED`; T16 disposable qualification remains `NOT_RUN`.

## Independent source review — 2026-10-25

An actual `code-reviewer` agent performed a bounded read-only review of the six evidence consumers and `S13-WRITER-EVIDENCE-SCOPE-01`. It found no material source finding: the private terminal/recovery paths scope the caller-supplied dispatch-CAS hint by tenant/company, scope referenced evidence before and after fences, and scope verifier-key lock scans before deriving locks. The review confirmed that the disposable criterion requires foreign-scope references to match absent-reference refusal, reveal no foreign fields, derive no foreign verifier lock, and produce zero row/event delta; a foreign dispatch CAS must match an absent scoped CAS. Exact source anchors: migration 027 lines 2799–2803, 2930–2934, 3565–3574, 3591–3596, 3624–3629, 5161–5170, 5270–5292, 5421–5430; qualification prerequisite line 335.

Role/model/effort: `code-reviewer`, GPT-6 Luna, low effort. This review is static source evidence only; no tests, SQL parsing, installation, database operation, or disposable runtime qualification ran. It does not close the broader S13 lock/FK/trigger/effect map or any effective-grant gate.

## Ownership and next action

Accountable owner: operator. Executor: Codex. Continue candidate source closure. After all coding is complete, assign the mapped wrong-scope and lock-trace scenarios to the functional and E2E test roles, then perform the relevant database/security review.
