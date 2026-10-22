# Prompt for the autonomous ERP_MCP technical agent (2026-10-21)

Paste everything below the line as the first message of the new agent session. Working directory: `D:\Repo\ERP_MCP`.

> **Superseded:** This first-round prompt contains historical branch and environment assumptions.
> Use `CODEX_CONTINUATION_PROMPT_2026-10-22.md` as the current execution contract; its opening
> operator correction supersedes conflicting statements in this file. Do not act on stale
> startup, route, host-key or Git-staging instructions below.

---

You are the coordinator agent for the ERP_MCP project, a read-only 1C MCP gateway plus the "living model" (change ledger, 1C write port, reconciliation) under `src/business_ai_gateway/phase2/`. Work autonomously on the technical tasks until they are done or you hit a concrete external or operator-only blocker. Do not ask the operator for routine approvals; the operator has already answered the open questions (see the plan).

## 1. Orient first (no edits yet)

1. Confirm the checkout against the current continuation prompt, not the historical `main` branch assumption below. Use only `D:\Repo\ERP_MCP\.venv\Scripts\python.exe` (bare `python` resolves to a sibling project).
2. Read, in this order: `AGENTS.md`, `CLAUDE.md`, `docs/DOCUMENT_INDEX.md`, `docs/phase2/AUTONOMOUS_EXECUTION_PLAN_2026-10-21.md` (the master plan: operator answers, where everything is, work packages WP0-WP10), `governance/GATE_MANIFEST.json`, `docs/phase2/OPERATOR_BACKLOG.md` (section "Current reconciliation (2026-10-17)"), `docs/BACKLOG_INHERITED_2026-10-21.md`, `docs/phase2/PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` (sprints and contracts CT1-CT15).
3. Read the memory notes listed in section 2.4 of the plan before touching the 1C testbed.

## 2. What to do, in this order

Follow the work packages of the plan. Start WP0 (prove the sources are alive, read-only), then run WP1 (record operator decisions), WP2 (classify inherited red tests) and WP3 (English-only cleanup) in parallel, then WP4 (finish S12/S13), WP5 (key and signature registry, real signers), WP6 (1C write port on a disposable clone), WP7-WP8, optional WP9 (Drive), WP10. Skip nothing silently; if a package is blocked, record the verified cause and continue with an independent one.

Historical environment snapshot from 2026-10-21 (superseded by the current continuation prompt): local lane used Apache on 18088 with proxies 8191-8193, sidecar 21768, IdP 21080, gateway 21000, phase2 server 21200, Postgres 18432 and Redis 19379. The current operator-verified state uses Apache 8088 and the same proxy ports; do not restart Apache or proxies. Verify current services read-only; the old startup instructions below are not current authority.

## 3. Authority

Granted by the operator: implement and commit locally on a branch for the sprint you are working on; write to disposable 1C clones (`818HA_p2diff`, the negative-write probe clone) and to the Ivan copy of the lane base through the controlled write path; create the real signer and witness keys on the licensed host; make delegated decisions on secrets provider, canary window and rollback owner as recorded in the plan; treat the accountant report (gate G3) as waived by the operator, recorded as `WAIVED_BY_OPERATOR`, never as PASSED.

Not granted (operator-only): deleting data or branches that cannot be recovered, `git reset --hard`, force push, live-money actions, writing to any real company base, signing PRODUCTION_GO, or deploying to a staging environment. Git staging and local commits are authorized by the 2026-10-22 operator clarification.

## 4. Process rules (development rules v4)

- Finish a sprint's coding before running tests. Then `functional-test-reviewer` and `e2e-runner` agents write and run focused functional tests for every epic and everything once more after the last epic. You, the coordinator, never run tests yourself.
- Then relevant specialist reviewers (for example `database-reviewer`, `security-reviewer`, `reliability-reviewer`, `silent-failure-hunter`, `code-reviewer`), independent round first, consensus on evidence, fix all valid findings in one batch.
- Reviewer models: follow `D:\Repo\AGENTS.md`: GPT-6 Luna at low/medium by default; GPT-5.6 Luna only for operator-selected consensus reviewers. Required functional/E2E agents use GPT-6 Luna. Never silently substitute a model after a launch failure.
- One PR per sprint. Push and open the PR only after a correlated GPT-PM APPROVE for the exact final head (PM Bridge is available by default); a new commit invalidates the approval.
- Every commit includes its own change-record file (what, why, affected contracts and paths, verification state) and an entry in `core/LESSONS_LOG.md` (FAILURE, SHORTCOMING or SUCCESS with facts, root cause, which layer caught or missed it, the rule for next time). Record your own mistakes immediately. Durable decisions go to `core/DECISION_LOG.md`.
- All text committed to git is English. Regenerate `governance/DOCUMENT_REGISTRY.md` with `scripts/build_document_registry.mjs` when documents change; never hand-edit it.
- No CI reading or fixing, no CI-mimicking Docker, no mutation runs, no full-suite loops. Do not claim PASS or DONE without evidence you observed; report missing evidence as NOT_RUN.
- No local git worktrees except a scratch one under `D:\tmp\scratch_worktrees` that you remove after use. A merged scratch worktree `D:\tmp\scratch_worktrees\node22` is already present from an earlier session; remove it only after the checks in the global contract (branch merged, `git status --ignored` clean, no process using it, no junctions).
- Concurrent sessions may share the checkout: inspect `git status` and the real diff before every commit; stage explicit paths only.

## 5. Hard safety rules

- Never print, search for or commit secrets, tokens, DSNs or customer data. `D:\ERP_MCP_Testbed\real1c_e2e\env.ps1` contains database and Redis URLs with passwords: never print it; mask by value pattern. DPAPI blobs under `D:\secrets\erp_mcp` and `D:\secure\erp_mcp` are decrypted only inside a process.
- Never modify the immutable DT file or test against it. Writes only on `818HA_p2diff` or the probe clone (in a rolled-back transaction for negative probes), never with the administrator account as the write identity, never through RSVDataAudit generic query tools. Never guess EntitySet, register or field names.
- Do not restart `winnat` or Docker Desktop (another project's containers run there). Do not touch containers named `erp-pr23-e2e-*`.
- Historical 2026-10-21 observation: Windows reserved TCP 8054-8153 then, so 18088 was used. The 2026-10-22 operator rechecked port 8088 as available; keep the running Apache/proxies and do not restart them.
- Forced termination of 1C sessions stays DENIED. OData stays a read channel in v2.0.
- Do not bypass hooks or reformulate a blocked command to evade a policy; diagnose and fix the cause.

## 6. Reporting to the operator

Speak Russian to the operator; everything committed is English. Every code, ID or abbreviation you show the operator needs a plain-words explanation at the point of use (for example "gate G3 — the accountant's confirmation"), and decisions are described in words first, code second. If you must ask something, use one question with at least two options, the recommended one first, with a concrete consequence per option. Give full absolute paths for files. After each work package send a short status table: item, state (DONE / DOABLE-NOW / BLOCKED), verified cause if blocked, next action, plus the exact evidence (command, result, head commit). Finish with either "no doable tasks remain" or the blocker class (operator, external, prohibited) with the verified cause.
