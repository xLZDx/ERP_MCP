# ERP_MCP Phase 2 — autonomous implementation checkpoint

Date: 2026-10-08
Scope: isolated Phase2 branch, NOT runtime deployment, NOT production GO.
Repository: D:\Repo\ERP_MCP-phase2
Branch: phase2/living-model-connectors-reconciliation

## Implemented and tested locally

- Per-object, namespace-qualified OData EDMX structural digests and observed change classification.
- Pure dependency impact closure; affected / unknown mappings deny, unaffected changes only when graph complete.
- In-memory bitemporal reference ledger: known-time, separately recorded source-effective time, gaps and late corrections. NOT persistent yet.
- Registry-authorized source-wide 1C metadata observer contract: no arbitrary endpoint/credentials, no source writes. NOT wired to live source.
- Google Drive v3 read-only Changes API HTTP reader with hard-coded provider host, opaque page cursor, size limits, sanitized failures and no redirects. Real v3 has no changeId; dedup ID is generated per page+ordinal. OAuth supplied only via trusted server callback. No account OAuth connection created.
- Drive page projector: candidates UNATTESTED; verified exact file scope required; page/cursor atomic persistence still needs a database implementation.
- Deterministic six-column trial-balance comparator for account 521.1 with all analytic rows, Decimal, explicit tolerance policy, exact source snapshot and scope matching, truncated/partial/no-source handling.
- Deterministic posted purchase comparison for MOLDRETAIL-style exact supplier reference and company, posted/deletion flags, timestamp/currency/amount/full document set. No name-only identity join.
- All numeric comparison outcomes remain EVALUATION_ONLY. No connector, LLM, or caller-supplied JSON can auto-mark a native reconciliation PASS.

## Verification

Isolated Windows venv:
    .\.venv\Scripts\python.exe -m pytest -q tests\phase2
    .\.venv\Scripts\ruff.exe check src\business_ai_gateway\phase2 tests\phase2
Observed: 122 tests passed; Ruff All checks passed.
These are SPEC/unit and isolated mock-HTTP tests, not actual 1C/Drive credentials, native report exports, PostgreSQL migrations, financial acceptance or product UAT.

## Critical unclosed deliverables

G0: full Release2 scope/ADR/security/permission approval and donor reuse/license review.
G1: PostgreSQL Phase2 schema, real roles/RLS/FK, bitemporal immutable event storage, versioned accepted head CAS, transactionally durable Drive cursor. A previous attempt to write migration SQL was explicitly blocked by tool safety; no DDL created/applied and no alternative bypass performed. An authorized isolated test DB migration workflow is needed.
G2: real metadata observation via permitted 1C source-wide ACL, source load budget, accepted/observed provenance and version diff under a protected worker.
G3: actual standard native 1C report(s) and independent provenance/accountant attestation; numerical EVALUATION_ONLY is insufficient, especially when 1C accounts/settlement registers differ by configuration.
G4: ERP_MCP-owned Google Drive OAuth authorization, chosen folder/new-child access PoC, shared-drive cursors, token expiry and revocation, real file retrieval, private evidence store and sandbox parser. A connected ChatGPT Drive plugin alone does not grant this server credentials.
G5: reconciliation admin workbench, approvals, UAT and documented discrepancy workflow.
G6/G7: real source-specific production permissions, migration/rollback/backup proof, load/chaos/alert proof and exact-head release sign-off.

## Non-negotiable boundaries

- D:\Repo\ERP_MCP-integration-candidate is not used for Phase2 development.
- GitHub main, R1 deployment, 1C and PostgreSQL production data remain untouched.
- No production report generation, write probe, migration, expansion of grants or service restart.
- No "VALIDATED" fabricated cases. The numeric comparator is not native attestation.
- A branch push and 122 passing tests do NOT mean Phase2 is entirely complete.

## Next highest-leverage actions

1. Get an authorized additive migration path on disposable PostgreSQL with a separate worker role and no effect on R1. Implement transactional append-only observed snapshots, bitemporal queries, accepted head CAS and Drive cursor/outbox.
2. Qualify actual 1C report source on a disposable clone, independent bookkeeper approval and exact 521.1 six-column rows.
3. Authorize a dedicated ERP_MCP Drive OAuth/Service Account according to scope and verify new file/move/revision behavior, then wire HTTP client and private document storage.
4. Implement under test a bounded scheduler and 1C source discovery, then admin discrepancy workbench.
5. Run real integration, fault, load and user/admin production-qualified acceptance; do not swap R1 until gates pass.

Owner/operator approval is needed at each existing governance boundary; no bypass of identity, audit or source-native evidence.
