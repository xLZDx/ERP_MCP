# Phase 2 S10 offline closure: engineering handoff and release bundle description

Date: 2026-10-10. Branch: `phase2/living-model-connectors-reconciliation`. Offline base head when this document was written: `414d232` (S9 APPROVED by GPT-PM at `6ee27f1` and pushed; `414d232` adds the S9 report pair and the registry refresh).

This document is documentation only. It adds no code, runs no production action and invents no evidence. Every fact below is quoted or derived from `EVIDENCE_MATRIX.md`, `OPERATOR_BACKLOG.md`, `G1_OPERATOR_BACKLOG.md`, `IMPLEMENTATION_STATUS.md`, `TASK_LEDGER.md`, `PLAN_PHASE2_RU.md` and `core/DECISION_LOG.md`. Where those documents are older than the code (the first four were last refreshed around S5/S9 rows), the DECISION_LOG entries and the per-sprint reports win, and the gap is stated.

## 1. Terminal state: ENGINEERING_HANDOFF

S10 in `PLAN_PHASE2_RU.md` is "Source-specific prod canary under a separate permission; exact-head R2 release bundle" with gates G6/G7. The canary needs separate operator permission and real data, so it is **NOT_RUN**. What can be closed offline is the engineering handoff, and that is the terminal state of this program until the operator acts:

**State: ENGINEERING_HANDOFF.**

- Status ceiling for all Phase 2 code: `IMPLEMENTED_UNVERIFIED`. No story is VERIFIED or DONE (`TASK_LEDGER.md`: "No story marked VERIFIED or DONE without exact-head end-to-end acceptance").
- **Release 2: NO-GO.**
- **G1 NOT PASSED. G4 NOT PASSED. G5 NOT PASSED.**
- **G6-pre NOT PASSED** (not evaluable offline: it needs actual workload metrics, actual fault alarms and repeatable recovery on real infrastructure; the S9 readiness slots are all NOT_RUN).
- No gate G0-G7 has passed (`IMPLEMENTATION_STATUS.md`: "No gate G0-G7 has passed").
- Product acceptance: NOT_RUN. No R2 production GO. No accounting PASS from numeric comparisons alone.

### 1.1 What exists

| Sprint | Content (all unwired reference modules under `src/business_ai_gateway/phase2/`; no Release 1 import) | Plan / report |
| --- | --- | --- |
| S0 | Baseline, inventory, ADR proposals, G1 SQL (`db/phase2/001_living_registry.sql`..`003_security_hardening.sql`), executed on a disposable PostgreSQL 16 | `G1_IMPLEMENTATION_NOTE_2026-10-08.md`, `DECISION_LOG.md` D-001..D-007 |
| S1-S4 | Ports and fakes, connector SDK envelope, scheduler, failure-vs-drift, promotion service, capture loop | `S1_S4_TRACEABILITY.md`, `reports/PHASE2_S1_S4_SPRINT_2026-10-09(.ru).html` |
| S4b | Taxonomy, aliases, capture-loop hardening, capacity drill | `SPRINT_S4B_PLAN.md`, `CAPACITY_DRILL.md`, `reports/PHASE2_S4B_SPRINT_2026-10-09(.ru).html` |
| S5 | Capture permit, side-effect boundary, artifact vault, safe parser (US-021..023 deferred: need real UI/COM) | `SPRINT_S5_PLAN.md`, `reports/PHASE2_S5_SPRINT_2026-10-09(.ru).html` |
| S6 | Evidence attestation, candidate runner, 521.1 six totals, purchases contract | `SPRINT_S6_PLAN.md`, `reports/PHASE2_S6_SPRINT_2026-10-10(.ru).html` |
| S6b | `ap_account_strategy`, `posted_receipts` (`ap.account_based` stays closed) | `SPRINT_S6B_PLAN.md`, `reports/PHASE2_S6B_SPRINT_2026-10-10(.ru).html` |
| S7 | Google Drive over a read-only port and a scripted fake: `drive_oauth`, `drive_scope`, `drive_baseline`, `drive_cursor`, `drive_revisions`, `drive_membership`, `drive_auth_state` | `SPRINT_S7_PLAN.md`, `reports/PHASE2_S7_SPRINT_2026-10-10(.ru).html` |
| S8 | `workbench_types`, `workbench_review`, `timeline_view`, `coverage_view`, `safe_errors`, `jobs_api`, `workbench_session` (no real UI/HTTP) | `SPRINT_S8_PLAN.md`, `reports/PHASE2_S8_SPRINT_2026-10-10(.ru).html` |
| S9 | `ops_types`, `capacity_model`, `capacity_interference`, `audit_gate`, `delivery_replay`, `alert_rules`, `release_migration`, `release_rollback`, `restore_verify`, `export_safety`, `retention_hold`, `g6_pre_readiness` (all outputs stamped `SCRIPTED_OFFLINE_FIXTURE` / `EVALUATION_ONLY`) | `SPRINT_S9_PLAN.md`, `reports/PHASE2_S9_SPRINT_2026-10-10(.ru).html` |
| S10 | This handoff only; canary NOT_RUN | this file |

Tests live in `tests/phase2`. Passing tests prove that the reference logic classifies and refuses correctly over scripted inputs; they are not product acceptance and not evidence for G1, G4, G5 or G6-pre.

### 1.2 Gate table G0-G7

Owners and required evidence come from `PLAN_PHASE2_RU.md` section 3; status from `IMPLEMENTATION_STATUS.md` (gate table), `OPERATOR_BACKLOG.md` and the DECISION_LOG entries through S9.

| Gate | Owner | Required evidence | Current status |
| --- | --- | --- | --- |
| G0 | Product owner + architecture + security | Approved scope/ADR/threat model, R1 boundary, source inventory | BLOCKED: scope rebaseline or explicit authority (OB-01), donor inventory and licenses (OB-15) |
| G1 | Database/security review | Real PostgreSQL roles/RLS/FKs/lease/fence/cursor/outbox/replay, not only mocks | **NOT PASSED.** SQL executed on a disposable PostgreSQL 16, 229 integration tests passed on the S5 head `af9f287`; GPT-PM accepted restore, crash and guard mutations at `df92cc8` (no G1 PASS recorded; the final G1 exit review is not recorded as passed) |
| G2 | Metadata/domain review | Full canonical corpus, observed/accepted, unknown impact conservative denial, no AI promotion | NOT_STARTED in the status table: authenticated source-wide 1C observation and bounded worker need real access (OB-10); mechanics exist on synthetic evidence only |
| G3 | Independent accountant + verifier | Authentic report bytes/provenance, qualified recipe/config, six totals plus rows, operation coverage, attestation | BLOCKED: authentic native report and independent accountant attestation (OB-11) |
| G4 | Source owner + security | Narrow Drive access proven; shared drive/membership/revoke/token/revision tests | **NOT PASSED** (BLOCKED): ERP_MCP-owned narrow Drive OAuth (OB-12); S7 is a scripted fake only |
| G5 | Real user/admin UAT | Actual user/admin UAT, safe explanations, operations separation, auditable workbench | **NOT PASSED** (NOT_STARTED): no real UI; S8 is offline view/decision modules |
| G6-pre | Ops + security (readiness for G6) | Actual workload metrics, fault alarms, repeatable recovery | **NOT PASSED**, not evaluable offline; all readiness slots NOT_RUN |
| G6 | Prod owner + ops + security | Default-OFF enablement, pinned source/company/recipe/hash/user, window/expiry/budget, kill-switch, copied-environment qualification; no test probes in prod | BLOCKED: production permission, canary, capacity, chaos, recovery (OB-14); canary NOT_RUN |
| G7 | Release owner | Exact commit/config/recipe/parser/policy/evidence manifest, every mandatory test actual PASS, no P0/P1 blockers; skipped is not PASS | BLOCKED: needs all gates, exact-head manifest and release-owner approval (OB-21) |

## 2. Exact-head bundle recipe

An operator reproduces the engineering evidence for a head `H` as follows. Run from `D:\Repo\ERP_MCP-phase2` on a clean checkout of `H`.

1. Identify the head and confirm it is clean:
   - `git rev-parse HEAD`
   - `git status --short` (must be empty; untracked scratch directories such as `tests/phase2/_red_tmp/` must be absent or explained)
2. Offline tests (project interpreter, not bare `python`):
   - `.venv/Scripts/python.exe -m pytest tests/phase2 -q`
3. Lint:
   - `.venv/Scripts/python.exe -m ruff check src/business_ai_gateway/phase2 tests/phase2 scripts`
4. PostgreSQL integration (only with a disposable database; the DSN is operator-supplied, see `EVIDENCE_MATRIX.md` for the container used so far): set `ERP_PHASE2_TEST_DSN` and `ERP_PHASE2_REQUIRE_PG=1`, then `.venv/Scripts/python.exe -m pytest -m integration`. Without a DSN the integration tests are skipped, which is NOT_RUN, not PASS.
5. Exact-head document inventory (uses only objects of `H`, so it is reproducible on any clean checkout):
   - `git ls-tree -r --name-only H -- docs core governance reports` lists the tracked documents of the head; compare the Markdown subset with what the evidence section of the release decision cites.
   - `governance/DOCUMENT_REGISTRY.md` is NOT release evidence. The generator `scripts/build_document_registry.mjs` inventories every local and remote branch and the untracked Markdown of attached worktrees, so its output depends on repository-local state outside `H` (on the development machine it lists tracked paths of other branches and local-only paths). It is a navigation aid for the development machine only. Do not run it before comparing: regenerating overwrites the committed file and makes `--check` pass trivially. If you run it anyway, run `git diff --stat governance/DOCUMENT_REGISTRY.md` afterwards and discard the change (it is not part of `H`).
6. Sprint reports (RU and EN, with the test traceability matrices): `reports/PHASE2_S1_S4_SPRINT_2026-10-09(.ru).html`, `reports/PHASE2_S4B_SPRINT_2026-10-09(.ru).html`, `reports/PHASE2_S5_SPRINT_2026-10-09(.ru).html`, `reports/PHASE2_S6_SPRINT_2026-10-10(.ru).html`, `reports/PHASE2_S6B_SPRINT_2026-10-10(.ru).html`, `reports/PHASE2_S7_SPRINT_2026-10-10(.ru).html`, `reports/PHASE2_S8_SPRINT_2026-10-10(.ru).html`, `reports/PHASE2_S9_SPRINT_2026-10-10(.ru).html` (file pattern `reports/PHASE2_S*_SPRINT_2026-10-10*.html` for the 2026-10-10 sprints, `..._2026-10-09*.html` for the earlier ones).
7. Final check: `git status --short` must again be empty (no regenerated or scratch file). Then compare your results with the last agent-run results below and record them in `EVIDENCE_MATRIX.md` as a new row with the head from step 1.

### 2.1 Last agent-run results (not an operator measurement)

- `tests/phase2`: **6126 passed, 229 skipped**; ruff clean; at exact head `6ee27f1` (`core/DECISION_LOG.md`, "Phase 2 S9 closed and pushed"). The 229 skipped are the PostgreSQL integration tests without a DSN (NOT_RUN offline). The tests were run by the agent/developer; the last PostgreSQL integration run recorded in `EVIDENCE_MATRIX.md` is 229 passed on the S5 head `af9f287`, so integration is NOT re-measured for S6-S9 (those sprints have no database code).
- GPT-PM independently reran its 20,000-input capacity invariant scan with zero invalid plans (S9).

### 2.2 GPT-PM approval heads per sprint (from `core/DECISION_LOG.md` and `docs/phase2/DECISION_LOG.md`)

| Sprint | Approved exact head | Note |
| --- | --- | --- |
| S0 / G1 baseline | `45a7b1a` (APPROVE for push only), `df92cc8` (G1 exit evidence accepted) | G1 itself not passed |
| S1-S4 | `5000043` | plain push `df92cc8..5000043` |
| S4b | `a2219b0` | origin `6f80219` after merging origin main |
| S5 | `af9f287` | 0 BLOCKER / 0 MAJOR |
| S6 | `c194760` | per the S6 sprint report ("pushed after GPT-PM APPROVE on c194760"); no matching DECISION_LOG entry was found, so confirm there before relying on it |
| S6b | `b5ae365` | after a REJECT on `09536a3` (10 MAJOR) and one self-inflicted regression fixed |
| S7 and S8 | `fa4852d` | rounds 2-9 after REJECTs at `e5761eb`; S7-M03 closed by removing root re-admission (fail closed) |
| S9 | `6ee27f1` | rounds: `292a62d` REJECT (9 MAJOR), `23a055f` REJECT, `92cc3d9` REJECT, `6ee27f1` APPROVE; push `fa4852d..6ee27f1` |
| S10 | none | documentation only; offline closure has no approved head yet |

### 2.3 The release head

This document cannot contain its own commit hash. **The release head is whatever the final GPT-PM approval and its `core/DECISION_LOG.md` entry name.** Any later commit invalidates that approval. Any evidence in this bundle must be read against the head it names, not against the branch tip.

## 3. Operator-owned checklist

Engineering cannot close these; each is a precise blocker, not a workaround request.

- [ ] Re-issue the token for MCP `erp-mcp-818ha`: it answered 401 `AUTH_HEADER_REJECTED` when last observed on 2026-10-10 (recheck before relying on this). Auth is not bypassed.
- [ ] Real 1C data: scoped read access and the source-specific capture permit for `onec-818ha-reference` (OB-10), native report bytes, MOLDRETAIL posted-receipt data.
- [ ] Accountant attestation (G3, OB-11): independent export and attestation for 818 HA SRL, account 521.1, 2026-08-01..2026-08-31.
- [ ] Google OAuth and real Drive (G4, OB-12): ERP_MCP-owned OAuth client and narrow folder / new-child grant.
- [ ] G5 user/admin UAT on a real UI.
- [ ] G0-G7 decisions: G0 scope rebaseline or explicit prototype authority (OB-01), donor license approvals (OB-15), the source registry choice (OB-04), secret provider and rotation owner (OB-13), R1 shadow-compatibility and canary approval with rollback owner (OB-14), R2-US-047 scope (OB-20), release-owner approval for `PRODUCTION_GO` only after G0-G7 actual PASS (OB-21).
- [ ] Close GitHub issues #28, #29, #33, #37 as the owner (they were commented with fix commits and left open for the owner).
- [ ] S10 canary permission with the four pinned parts: recipe, identity, window, budget (plus kill-switch and copied-environment qualification per G6).
- [ ] Any deletion (including retention execution): separately and explicitly authorized; no S9 module deletes anything (`executed=False`).

## 4. NOT_RUN list

Reported as NOT_RUN, never as PASS:

- Real workload / capacity measurement (the only measurement is the S4b disposable-container drill in `CAPACITY_DRILL.md`, "not a capacity guarantee").
- Staging alarms and real alert delivery to a human.
- PostgreSQL restore beyond the G1 same-cluster `pg_dump -Fc` proof; restore into another cluster or version.
- Migration rehearsal on the real R1 schema (S9 classifies steps over `db/phase2` SQL text only).
- Retention approval and any deletion.
- Release 1 shadow regression.
- Hosted CI (no CI by operator decision 2026-10-08).
- Real Google OAuth, real Drive, real UI (all S7/S8 behavior is over fakes).
- Real 1C read, real paginated source, native bytes, MOLDRETAIL data, accountant attestation.
- PostgreSQL integration for S6-S9 (no DB code; last integration run on `af9f287`).
- Mutation runs (NOT_RUN by operator rule 2026-10-09).
- The S10 production canary itself.

## 5. Accepted backlog (known, not fixed, not blocking the offline closure)

From the S9 closure entry and the S7/S8 decisions in `core/DECISION_LOG.md`:

1. Delivery claim lease expiry is not checked by `_fenced` (`delivery_replay`).
2. `place_hold` quota-slot leak (`retention_hold`).
3. `confirm_release` reads a point-in-time snapshot (`retention_hold`).
4. Tenant-wide duplicate audit request ids (`audit_gate`).
5. S7 removed Drive roots return only with a new checker: root re-admission was removed (fail closed) in round 9 instead of being patched again; a future backend-enforced, version-bound claim is needed.
6. An unaudited in-memory run stays visible until recovery (S8 session/run behavior).

Documentation gap noted at S9 closure: the S9 section of `S1_S4_TRACEABILITY.md` still shows the counts collected at `50e4c6e`; the S9 report carries the current per-file counts.
