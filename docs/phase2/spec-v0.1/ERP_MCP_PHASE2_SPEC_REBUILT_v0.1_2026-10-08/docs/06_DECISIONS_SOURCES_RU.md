# ERP_MCP Phase 2 — ADR Proposals, Decisions, Risks and Sources

**Version 0.1 · October 8, 2026 · DRAFT.** These proposals do not automatically change the normative Release 1 architecture decisions.

## Candidate Architecture Decisions

**R2-ADR-01:** Keep observed metadata separate from accepted metadata. A scanner must never act as an automatic approver.

**R2-ADR-02:** Use PostgreSQL for bitemporal events and current projections; consider TimescaleDB only after a measured benchmark.

**R2-ADR-03:** Reports captured through a manual or qualified automated standard UI, or through a qualified standard reporting engine, may qualify as native evidence. Synthetic/custom-query results are not upgraded automatically.

**R2-ADR-04:** Native-report capture is a distinct control-plane capability and is **OFF by default** in production.

**R2-ADR-05:** Require genuine evidence and attestation foreign keys, independent roles, and operation-specific validation policies.

**R2-ADR-06:** Use a reusable connector event/provenance contract with pinned donors, license review and dependency audit.

**R2-ADR-07:** Start Drive integration with polling, a real permission proof of concept, and independently stored immutable captured bytes. Do not assume revision coverage is complete.

**R2-ADR-08:** Enforce physical-backend-wide budgets, lease fencing and transactional outbox.

**R2-ADR-09:** Keep accounting-based accounts payable separate from settlement/open-item reconciliation strategies.

**R2-ADR-10:** Financial acceptance requires matching scope, cutoff and source consistency, not just a matching report date.

**Approval sequence:** Risk review → impact analysis → independent tests → operator governance decision → implementation. Changing what qualifies as native evidence requires a normative amendment at implementation time. Do not relabel historical reporting-engine artifacts retroactively.

## Key Risks and Acceptance Criteria

| ID | Severity | Risk | Required protection |
| --- | --- | --- | --- |
| RK01 | Critical | Fabricated ten PASS results | Genuine artifact and digest, evidence FK, independent approver; TC083/101 |
| RK02 | Critical | A report-generation action writes business data | Procedure qualification, rights checks, no arbitrary execution; TC073–075 |
| RK03 | Critical | Tenant metadata/evidence leakage | Scoped keys, PostgreSQL RLS, authorization epoch; TC011/014/120 |
| RK04 | High | The same internal calculator generates expected and actual values | Standard report provenance and genuinely independent validation |
| RK05 | High | Opening/turnover errors cancel out to an equal final net balance | All-six-column reconciliation; TC089 |
| RK06 | High | Metadata/capture overloads a 1C backend | Shared physical-backend budget and load tests |
| RK07 | High | Intermediate source changes are not observed | Gaps and unknown effective time; never fabricate history |
| RK08 | High | Drive scopes exceed the intended folder or exclude new files | Actual grant proof of concept |
| RK09 | High | Token expiry or revocation breaks background processing | `AUTH_REQUIRED`, alerts and re-consent |
| RK10 | High | UI-dependent trial-balance/account-card export produces no data through COM | Explicit `UNSUPPORTED` and qualified UI fallback only under permit |
| RK11 | High | Backdated corrections appear between two reads | Same snapshot/cutoff or `INCONCLUSIVE` |
| RK12 | High | Specification PASS is presented as production evidence | Explicit `NOT_RUN` and release guard |
| RK13 | High | Time zone, currency or rounding is unknown | Verify full scope before arithmetic |
| RK14 | Medium | Unbounded storage growth | Deduplication, partitioning, retention and approved archive |
| RK15 | High | Restore resurrects revoked permissions | Current policy and epoch validation |
| RK16 | High | A reporting recipe becomes invalid after source configuration changes | Requalification |
| RK17 | Medium | A new revision overwrites a historical PASS | Immutable history, with current applicability tracked separately |
| RK18 | High | A test runtime is mislabeled as production | Authority field and target-specific release gate |

## Open Decisions

Confirm the real native UI executor, 1C topology and configuration edition, source time zone and currencies. Select a production consistency mechanism and appoint an independent accountant approver.

Approve the policy for eligible native evidence and per-operation claims coverage separately from file counts. Complete donor inventory and licensing. Decide the Drive account/file/folder/shared-drive permission model; retention, legal holds and data residency; hardware/load budgets and stop thresholds. Production needs a durable browser-accessible HTTPS identity provider, separate from any temporary tunnel.

## Local Sources Reviewed for the Initial Proposal

| Ref | Material and qualification |
| --- | --- |
| L01 | `docs/PHASE_2_REQUIREMENTS_BACKLOG_DRAFT_2026-10-08.md`: existing Release 2 backlog; reviewed |
| L02 | `AGENTS.md`, `docs/DOCUMENT_INDEX.md`: precedence of SECURITY/GOVERNANCE/SCOPE_FREEZE; prohibit arbitrary write/query/secret actions |
| L03 | `docs/NATIVE_REPORT_CAPTURE_RUNBOOK.md`: R1 UI-only eligible class, diagnostic engine, UI-dependent reports, side effects, disposable clone, ten existing cases, missing settlement-register issue |
| L04 | `reports/LOAD_TEST_REPORT.md`: real PostgreSQL/synthetic callbacks; **production capacity NOT APPROVED**. Previously inspected `app.py`/`db.py`/`fanout.py`/sidecar limits are not real capacity evidence |
| L05 | PDCC `services/gmail-connector/src/history-runtime.ts`, `services/slack-connector/src/index.ts`, `host/telegram-connector`: previously inspected donor paths; new pin/license audit mandatory in S0 |
| L06 | `ERP_MCP/testbed/ferma_onec/reconcile.py`, `docs/FERMA_1C_SYNTHETIC_TESTBED_IMPLEMENTATION.md`: previously inspected comparator and test-oracle patterns |
| L07 | ERP `docs/architecture/R12_TEST_DATA_PLATFORM_TDD.md`, `workers/reconciliation-jobs`: design references; the worker was a placeholder |
| L08 | `reports/CHATGPT_READER_BOOTSTRAP_REPAIR_2026-10-07.md` and related discussion: historical access/profile/evidence findings, **not** a new live attestation |
| L09 | Historical Git status and logs: the working tree was dirty; the last observed short SHA was `4a21a01`, previously `1294b42`. This does **not** certify the current/deployed HEAD |

## External Primary Sources Checked on October 8, 2026

| Ref | Documentation |
| --- | --- |
| W01 | [Google Drive change management](https://developers.google.com/workspace/drive/api/guides/manage-changes) |
| W02 | [Drive API scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) |
| W03 | [OAuth token expiration](https://developers.google.com/identity/protocols/oauth2) |
| W04 | [Drive notifications](https://developers.google.com/workspace/drive/api/guides/push) |
| W05 | [PostgreSQL row-level security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) |
| W06 | [Official 1C REST interface](https://1c-dn.com/1c_enterprise/rest_interface/) |
| W07 | [Drive changes.list API](https://developers.google.com/workspace/drive/api/reference/rest/v3/changes/list) |
| W07b | [Drive revisions](https://developers.google.com/workspace/drive/api/guides/manage-revisions) |
| W08 | [Workload Identity Federation](https://docs.cloud.google.com/iam/docs/workload-identity-federation) |
| W09 | [PostgreSQL 16 range types](https://www.postgresql.org/docs/16/rangetypes.html) |

Provider documentation is **not** an implementation guarantee. The Drive changes feed does not guarantee a complete history of all revisions; Viewer or read-only access does not guarantee history API support. A connector must not elevate permissions or call a `keepForever` mutation merely to download history. Workload Identity Federation does not automatically grant Drive permissions. OData also supports writes, so read-only operation must be enforced by ERP_MCP contracts and 1C privileges.

## Evidence at the Original Design Checkpoint

Only project documents and companion specification files were prepared. Native UI, real 1C, Drive, production execution, new grants, migrations, deployment and load tests were **not** performed in this initial checkpoint. Specification self-tests verified structure, fixtures and counterexamples, **not** a running product. All 144 product test scenarios remained `NOT_RUN` at that time.

**This is historical design evidence. For current status, inspect the exact Git HEAD, test logs, decision records and owner-approved gates.**
