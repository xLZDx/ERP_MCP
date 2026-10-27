# Change Record 276 — retire the legacy fence check from S13 writer authority

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical closure owner: Codex. The `code-reviewer`, `functional-test-reviewer`, and `database-reviewer` are execution roles, not project owners; Codex coordinates their later evidence. GPT-PM owns any required product/contract adjudication and the exact-head approval gate before push/PR.
- State: source-only candidate; the focused `code-reviewer` accepted the initial cutover diff, the later full GPT-PM review returned `MODIFY`, and a fresh focused `code-reviewer` accepted the adapter/schema-mode guard at source level. Broad follow-up GPT-PM review, effective grants and runtime qualification are pending.

## Change and reason

Historical migration 006 grants `writer_role` the legacy `fence_check(text,text,uuid,bigint,uuid)` function. It is a point-in-time query in a short transaction and cannot atomically authorize a later physical COM call. Candidate migration 027 now revokes that exact function signature from PUBLIC and the listed runtime principals as part of the coordinated S13 cutover. `SqlChangeLedger.fence_check()` refuses before `invoke()` with `S13_COM_ENTRY_GUARD_REQUIRED` when the S13 schema flag is enabled. The old route and arguments remain available only against the pre-cutover schema; applying 027 while any deployed writer remains in legacy mode is an invalid rollout and must be prevented.

No versioned source caller of `fence_check()` was found in `src/`; the method remains in the adapter contract for legacy mode. This is source evidence only and does not prove effective permissions or runtime absence of an inherited grant.

## Evidence and limits

- Candidate SQL: `db/phase2/027_private_writer_admission_schema.sql:12034-12036`, SHA-256 `9DF1535F38F6FF9AD8C4FD62DD9DAA639232FFEC7433ABC5520F6811325C645A`.
- Adapter: `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py:544-552`, SHA-256 `5AFEF451DD5820490D04ED31479611ABE452F4E402AA8EA81C2F864994D23579`.
- Qualification: `S13-FENCE-CHECK-CUTOVER-01` in `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, SHA-256 `C466D4DF75C01F01FE1FFEFC2FABC52CF5608C46FF16AE0F07FAEBFE62AE9430`.
- Current continuation and access evidence: `CODEX_CONTINUATION_PROMPT_2026-10-22.md`, SHA-256 `E0603781964A681E66A877DB732FDBCF705940586302D30D0B0FDBB26E07E79B`.
- Historical grant and function: `db/phase2/006_change_sweeps.sql:838-861,926-928`.
- Inventory addendum: `S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`, SHA-256 `71E3FAEEB9F25BF9477310A28F680589A97A8A71F9569B90F0B52EC7B3B3F334`.
- Current source head observed: `3e12436`.
- Focused actual `code-reviewer` review: `/root/s13_fence_check_cutover_review`; no source-level blocker found. The reviewer confirmed that S13 mode refuses before `invoke()`, legacy mode retains the route, candidate 027 revokes the exact signature, and no `src/` caller exists beyond the adapter. Model and effort metadata were not exposed; they are `NOT_EXPOSED`, not inferred.
- Candidate migration remains unparsed and unapplied. No effective ACL query, test/check, build, CI, database operation, COM operation, stage, commit, or push was run for this change.

## Remaining acceptance and next step

The focused source diff has been reviewed, but this is not installed or runtime evidence. After coding is complete, the functional-test owner must prove S13 mode makes zero SQL calls and pre-cutover legacy routing remains unchanged; the rollout contract must reject a 027-installed database paired with a legacy-mode writer. The database reviewer must query `has_function_privilege` for every runtime role and inherited membership on the disposable S13 schema. Race recovery/epoch advancement against the old point-in-time result and prove no physical invocation follows it. The source revocation alone is not effective-grant or runtime evidence.

Accountable owner: operator; executor and technical-closure owner: Codex. The functional-test and database-reviewer roles will execute their scoped evidence work when coding is complete. Next: continue remaining S13 code closure, then start the test and database-qualification phase.

## Pre-commit GPT-PM review — 2026-10-26

Request `c6c7dc4f-11f6-4810-9cad-326f3d1e6a67` was sent through PM Bridge to canonical project `erp_mcp` / repository `https://github.com/xLZDx/ERP_MCP.git` and correlated to reply `e8866c5f-24c2-5fd8-b3ee-0026449439b0`. Verdict: **MODIFY — source-only pre-commit**. The review confirms the S13 fail-closed `fence_check` adapter refusal and SQL revoke, but does not approve the source gate. It identifies B-01 (no operational 1C writer/property/transaction implementation), M-01 (no enforced schema-mode/startup compatibility), M-02 (database entry authorization is not proof of physical COM entry), M-03 (stale worker/takeover needs physical proof), M-04 (evidence providers and resolver are injected, not operationally bound), and M-05 (effective grants/complete lock graph are unverified). SQL parsing, migration, effective ACL query, disposable races, tests, COM and deployment remain `NOT_RUN`/`NOT_VERIFIED`; no commit or push is authorized by this reply. Exact next source work is to close any independently implementable compatibility gap, while the writer implementation remains gated on the verified disposable-clone property/credential/transaction manifest and test-owned qualification.

## Current-turn source follow-up — adapter/schema mode guard

To address only the independently implementable part of GPT-PM finding M-01, `SqlChangeLedger.invoke()` now checks the candidate marker type `change_ledger.private_writer_identity_v1` inside its owned READ COMMITTED transaction and before role/scope setup or the selected business function. The observed marker must exactly match the adapter's immutable `private_writer_schema_enabled` setting; otherwise the call fails with `S13_SCHEMA_MODE_MISMATCH`. This rejects either settled mismatch before the business function is called. It does not make rolling migration safe and does not replace the requirement to stop/upgrade every legacy writer before applying migration 027. The earlier GPT-PM `MODIFY` predates this delta. A fresh focused actual `code-reviewer` review (`/root/review_schema_mode_guard`) found no source-level blocker and accepted the guard's ordering and fail-closed mismatch behavior. This is not runtime, migration, effective-grant, or broad GPT-PM approval; those remain pending.

- Adapter `sql_ledger.py:369-375`, SHA-256 `363DA1B62EF4E51FA7136ADF4F450E1EF2ADD209173D8445B54A7E940685351B`.
- Qualification `S13-ADAPTER-SCHEMA-MODE-01`, prerequisite document SHA-256 `F3A5DC2AB17D58B064AAEA8D62822FCAB18856365BBA276E7FF912C9B167587B`.
- Review evidence: focused actual `code-reviewer` accepted the source-level guard; model/effort metadata were not exposed. No test, check, SQL parse, migration, build, COM call, stage, commit or push ran for this follow-up. A later read-only catalog query found that the disposable database has no `change_ledger` schema or S13 marker, so it could not qualify the guard or candidate grants.
