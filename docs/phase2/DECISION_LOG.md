# Phase 2 decision and evidence log

Append-only. Each entry is a durable decision, piece of evidence or refusal that a new developer needs. Newest last.

## 2026-10-08 — D-002: first real PostgreSQL run, operator decisions

Operator (2026-10-08): PostgreSQL and Docker exist on this machine, create a disposable instance (I had wrongly concluded none existed from a PATH-only check; Docker Desktop is installed but not on PATH). Own container `erp-phase2-test-pg` (postgres:16-alpine, 127.0.0.1:55712, `--rm`, no volume, random password kept only in the session scratchpad) was started; the existing R1 containers were not touched. Result: migrations 001-003 apply, 20/20 integration tests pass after fixing four wrong test expectations (see IMPLEMENTATION_STATUS). G1 moves from "SQL never executed" to "SQL executed on a disposable DB, integration subset green"; G1 is still not PASS (no backup/restore, crash/kill, capacity, mutation checks, GPT-PM and independent review of the final head).

Operator decisions: (1) no CI and no pytest suites are run as gates; (2) Phase 2 is not mixed with R1 (OB-05 answered: R2 stays isolated), but the latest R1 updates are pulled into this branch by merge (R1 itself is never modified); (3) the independent reviewer is GPT-PM, so the local re-review requested earlier is replaced by the GPT-PM sweep once OB-02 is resolved.

## 2026-10-08 — D-001: multi-reviewer round on HEAD 9b4fc0c, remediation and verification round

**Decision.** Before any further S0–S10 work, the whole Phase 2 tree was reviewed by six read-only local reviewers (Sonnet; database, security, Python, test adequacy, reliability, architecture), remediated in one batch, then re-reviewed (SQL, Python+security, test adequacy; fixes and regressions only). Operator instruction: "run the whole project through local agents and GPT before going further". Local agents were authorized for this run by that instruction.

**GPT-PM step: NOT DONE.** `pm_rosetta_plan` was refused: no PM Bridge project to conversation binding exists for `D:\Repo\ERP_MCP-phase2` (only `erp_mcp-integration-candidate` and `erp_mcp-native-reports`). The Release 1 chat was deliberately not reused (project isolation). Blocker OB-02 in `OPERATOR_BACKLOG.md`. Consequence: this work is ungoverned in Rosetta terms (`governed=false` acts), no GPT-PM APPROVE exists, and **no push or PR may happen** until OB-02 is resolved and a correlated APPROVE is recorded for the exact head.

**Round 1 findings (static, nothing executed on PostgreSQL).** Highest severity:
- Tenant isolation rested on a client-settable GUC; no role binding, no source/company scope.
- `promote_head` did not authenticate the approver and `accepted_heads` could be changed by direct DML.
- `recorded_at` client-controlled; not commit-ordered.
- `commit_cursor_page` advanced the cursor when `page_events` was NULL and was not fenced by the job lease.
- No roles, PUBLIC EXECUTE open, no `search_path` pinning, TRUNCATE unguarded.
- Python: EDMX structural hash ignored unnamed content; GAP events displaced the OBSERVED head; Drive removals/unknown changes silently dropped with the cursor advancing; truthy ACL check; no audit before connector calls; backend-id aliases bypassed the budget; empty-vs-empty reconciliation returned MATCH.
- Tests: static SQL text tests were counted as G1 evidence; concurrency tests could not fail; ledger and status documents contradicted each other.
- Architecture: Phase 2 code sits inside the R1 fingerprint and CI trees; own `living.sources` instead of reusing the R1 registry; no G0 rebaseline.

**Remediation.** `db/phase2/001`/`002` rewritten, `003_security_hardening.sql` added, Python modules fixed, decorative tests replaced by behavioral tests, PostgreSQL integration tests written but **not run** (no authorized database).

**Verification round findings and handling.**
- SQL: 12 of 13 earlier findings fixed, 1 partial. New: N-1 (re-running 001/002 after 003 undoes hardening), N-2 (independence by role name only), N-3 (`recorded_at`/`ingest_seq` not commit-ordered), N-4 (no rebase of cursors/jobs after epoch bump), plus minor N-5..N-11. Fix batch in progress at the time of writing.
- Python/security: 17 of 19 fixed. New: F1 (ACL-filtered fingerprints diffed as complete), F2 (UNKNOWN Drive changes only advisory), F3 (tenant not verified against the registry), plus minor F5..F9. Fix batch in progress at the time of writing.
- Tests: five MAJOR gaps (temporal lock, `trashed` mapping, Decimal precision path, empty-rows branch, integration-suite skip safety) fixed.

**Evidence status (measured on the worktree immediately before commit, base HEAD 9b4fc0c).** `pytest -q tests\phase2`: 310 passed, 20 skipped (PostgreSQL integration, `NOT_RUN`), exit 0; `ruff check src\business_ai_gateway\phase2 tests\phase2`: exit 0; `compileall`: exit 0. Full repo `pytest`/`ruff` and R1 regression: NOT_RUN.

**Fix batches after the verification round.** SQL N-1..N-8, N-10, N-11 done (N-9 documented: GUC epoch is protection against stale writers, not a malicious role). Python F1, F2, F3, F5, F6, F7, F8 done; F4 (audit of denied attempts, actor in Drive audit) and F9 (per-call node limit, concurrency semaphore) left open. Not independently re-reviewed; F1-F3 tests were not mutation-checked.

**Known risks carried forward.** The `DO ... EXECUTE $body$` wrapper that makes 001/002 re-apply-safe is syntactically unverified; `claim_outbox` RETURN QUERY with UPDATE is unverified; `living_publisher` is a fifth cluster-global role; the migration checksum is still a session setting verified then cleared. First thing to run when a disposable PostgreSQL exists: `test_n1_reapply_001_002_after_003_equals_single_pass`.

**Not verified.** Any SQL behavior (syntax, RLS, grants, concurrency, backup/restore), `SET ROLE` plus `SECURITY DEFINER` semantics, R1 regression suite, performance, Google Drive API behavior stated from memory.

**Open decisions for the operator.** OB-01 (G0/rebaseline), OB-02 (ChatGPT conversation for Phase 2), OB-03 (disposable PostgreSQL), OB-04 (source registry reuse), OB-05 (R1 fingerprint/CI isolation). See `OPERATOR_BACKLOG.md`.

**Status impact.** `IMPLEMENTATION_STATUS.md` and `TASK_LEDGER.md` refreshed to this evidence. G1 stays BLOCKED / IMPLEMENTED_UNVERIFIED. Release 2 stays NO-GO.

## 2026-10-08 - D-003: GPT-PM plan APPROVE, sweep REJECT of a8b5b4d, remediation

PM Bridge: Phase 2 registered as erp_mcp-phase2 on a new ChatGPT conversation supplied by the operator (the bridge cannot create the first chat for an unregistered project; one conversation cannot serve two projects). Plan erp_mcp-phase2-2026-10-08T19-20-52-493Z-75918d (hash a1ba0886...) APPROVED by GPT-PM, GO bound. Adversarial sweep on exact head a8b5b4d: **VERDICT: REJECT** (3 BLOCKER, 5 MAJOR, 6 hypotheses to test, NOT_RUN items do not block a push of the isolated branch but block release; push needs a new exact-head APPROVE).

Handling (every finding was first reproduced against the code or the real database):
- BLOCKER-01 commit_cursor_page replay with a different batch: fixed (page digest, CONFLICTING_PAGE_REPLAY). BLOCKER-02 outbox claim without fence: fixed (claim_generation, authenticated identity). BLOCKER-03 recorded_at vs commit: fixed by a documented settled-horizon rule (knowledge_horizon, KNOWLEDGE_HORIZON_NOT_SETTLED); the same query no longer changes its answer after a late commit.
- MAJOR-01 attestation authenticity: trusted_reviewers, evidence digest bound to the revision digest, decision, expiry, revocation, re-checked in promote_head (still a database-level contract, not external cryptographic proof). MAJOR-02 revoke barrier: role_scope changes bump scope_epoch atomically. MAJOR-03 audit of denied attempts and actor: done for Drive and 1C discovery. MAJOR-04 discovery concurrency: BackendId budget slot plus semaphore. MAJOR-05 documentation drift: EVIDENCE_MATRIX.md and a doc lint test.
- Also closed: F4, F9.

Residual, stated honestly: an API that passed assert_scope just before a concurrent revoke commits is only re-checked under the source lock in commit_cursor_page; the horizon is pessimistic while an ingest is in flight; asyncio.to_thread work cannot be cancelled mid-fingerprint; the budget is single-process; backup/restore, kill -9 mid-page, capacity and mutation checks are still NOT_RUN; the hypotheses H-01..H-06 are covered only by the tests listed in EVIDENCE_MATRIX.

Evidence: see EVIDENCE_MATRIX.md (326 passed/25 skipped without a DSN, 25 integration passed on the disposable PostgreSQL 16, ruff exit 0). Next: bounded GPT-PM verification of these fixes and direct regressions; push only after a correlated APPROVE on the new exact head.