# ERP_MCP Phase 2 — customer release readiness (2026-10-09)

**Release disposition: NO-GO.** Engineering progress is not customer product acceptance. This record accompanies the isolated branch `hardening/phase2-budget-validation`; it does not replace the authoritative gate decision.

## Release boundary and terminology

- Phase P2 in the Release 1 master plan = capability routing, not an AI workflow engine.
- Release 2 / Living Model is separately developed in an isolated branch. It is not a full autonomous workflow/copilot product today.
- A product demonstration must distinguish: working read-only R1 tools, code/reference implementations in R2, and future ERP Platform capabilities.
- No public statements about unattended posting, automatic approval, reconciled accounting PASS, or production-ready R2 without exact-source and independent acceptance evidence.

## Current evidence

- R2 committed source baseline: `9cb66343456c37e914fb473dc5aa0f03cf0ea325` at branch creation; original Phase 2 worktree contains other uncommitted files, deliberately untouched.
- Earlier safety commits: `4c74af8` (strict physical-backend budget types), `406a8bd` (strict reference trust labels) and `875bcc9` (initial readiness snapshot). This addendum extends the metadata-observation guard.
- Six budget misconfiguration cases and fifteen authority/trust-spoof cases were demonstrated failing before their repairs, then passing afterward; an additional positive trust-compatibility case remains green.
- On final local isolated Phase 2 code: **349 passed / 65 skipped**; Ruff **PASS**. The skipped 65 PostgreSQL tests are **NOT_RUN on this new HEAD**. Earlier 65 PostgreSQL integration passes on `df92cc8` do not transfer by assertion.
- G1 restore/crash/guard-mutation evidence in `EVIDENCE_MATRIX.md` was reviewed and approved for *push* on `df92cc8`, not G1 release exit. G0–G7 are not all PASS.
- The in-memory ledger, per-process budget, callback-based 1C and Google Drive clients, and comparison classes are not wired end-to-end production workflows.

## Critical blockers (no autonomous override)

| Gate | Disposition | Missing confirmation |
| --- | --- | --- |
| G0 | BLOCKED | Scope rebaseline, donor licensing, and source registry/ownership design decision |
| G1 | IN PROGRESS, NOT PASSED | Exit approval and exact-HEAD capacity, DB/security/recovery evidence as required |
| G2 | NOT_STARTED as product gate | Authenticated live 1C source-wide capture and bounded worker |
| G3 | BLOCKED | Genuine 1C native report and independent accountant attestation |
| G4 | BLOCKED | ERP_MCP-owned minimal Google Drive OAuth and consent; no invented grant |
| G5 | NOT_STARTED | Real admin workbench and witnessed acceptance |
| G6 | BLOCKED | Authorized production configuration, canary, capacity, chaos and rollback |
| G7 | BLOCKED | All prior gates, independently verified release evidence, release owner approval |

## Operator backlog reconciliation

`OPERATOR_BACKLOG.md` includes historical statements that are superseded by `DECISION_LOG.md`: OB-02 (dedicated Phase 2 PM Bridge chat) is resolved in D-003, OB-03 (disposable PostgreSQL) was resolved in D-002, and OB-05 (R1/R2 work separation) has an answer. The newer Rosetta plan-go binding still has a mechanical unresolved status (D-006/007). **Do not call these historical blockers open verbatim.** OB-01 scope authority, OB-04 registry architecture, OB-10/11 real 1C and accountant evidence, OB-12 Drive consent, OB-13 rotation owner, OB-14 deployment permit, OB-15 license review and OB-21 release approval remain materially open unless a new exact-head decision resolves them.

**Terminal condition for this patch branch:** all edited files reviewed, local tests and lint green, commits pinned; no merge/push/production actions until the project's exact-head governance and real-world prerequisites permit them. **Terminal condition for the product is not met.**

## Parallel development review tail — P-M1 OPEN

Read-only review of currently untracked `phase2/promotion.py` and its fake-based test found a missing attestation identity echo check. A stale attestation from revision A supplied for revision B caused `REJECTED_EVIDENCE`, but only after **one write-port attempt** (`write_port_attempts=1`). The underlying port rejected, so no successful unauthorized promotion is proven. The independent repro, source hashes, and precise required negative test are in `PROMOTION_PREFLIGHT_REVIEW_2026-10-09.md`. The active parallel engineering lane must fix and retest this before its promotion-service story can be considered accepted; this isolated safety branch does not touch that uncommitted file.
