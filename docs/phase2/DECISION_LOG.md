# Phase 2 decision and evidence log

Append-only. Each entry is a durable decision, piece of evidence or refusal that a new developer needs. Newest last.

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
