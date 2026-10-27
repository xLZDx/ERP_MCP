# Change record: Record S13 source-final grant and lock findings

## Change

- Added `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`, a static role/signature inventory of granted mutation functions and source lock paths from migrations 004–026.
- Added dated S13 review notes to the writer-path inventory, current operator backlog, and WP4–WP10 dependency record; corrected their current S13 summaries to distinguish completed source tracing from unverified deployed grants and writer boundaries.
- Regenerated the document registry from committed Git refs only.
- Appended a lesson-log entry documenting the accidental `git diff --check` invocation.

## Why

The canonical S13 inventory explicitly required a database reviewer to reconcile the per-API map with function/grant inventory and establish a viable all-path lock order before proposing a fence migration. The read-only review reconciled the explicit runtime grants, traced the identified helper/trigger and recovery-stage paths, and documented UPSERT conflict targets. It confirmed that `validate` takes a record lock before `A:key` and that the event-trigger request order can take the chain advisory lock before requesting the lifecycle row. The artifact records these source findings without claiming a runtime deadlock or proposing a migration.

## Contracts and paths

- Recovery refusal and lifecycle `NOT_READY` are preserved.
- No SQL migration, source behavior, live database privilege, authorization, or release state changed.
- The inventory is static migration-source evidence only; it is not evidence of installed grants, live role membership, or a physical writer boundary.

## Decisions

- Do not claim a runtime deadlock cycle from the source lock-order contradictions alone; recovery remains disabled and no concurrency execution occurred.
- Treat event trigger alphabetical ordering as the relative trigger-request order, backed by official PostgreSQL trigger documentation; some call paths may already hold the lifecycle row before event append.
- Record source-visible conflict targets and later explicit locks without claiming a global runtime wait graph. Do not propose a new fence migration until effective deployed grants and the actual service boundary are established.
- At the time of this inventory, canonical project records did not identify the actual writer/service owner. In a later 2026-10-22 clarification, the operator identified the Ivan stack (`ERP_MCP_Ivan_Stack`) as technical owner of the existing host/connection boundary and designated the future private writer as an S13/S14 deliverable on that lane. The operator is accountable for the delegated task; Codex is the executor. A separate named human contact for the future writer service remains unestablished.

## Verification state

- Actual database-reviewer source review was read-only at base HEAD `0fe023db1ec2adcf1820356db1dd1db09d23c3ab`; exact migration/function/grant/lock references are included in the inventory.
- The PostgreSQL trigger-order claim was checked against the official PostgreSQL 16 documentation: <https://www.postgresql.org/docs/16/trigger-definition.html>.
- Registry generation command: `node scripts/build_document_registry.mjs --exclude-local-only`; exit 0, scanned 46 refs and 426 tracked Markdown paths, local-only `NOT_ENUMERATED`, at base HEAD `0fe023db1ec2adcf1820356db1dd1db09d23c3ab`.
- No tests, builds, CI, migrations, live database access, or remote calls were performed for the original inventory pass. After it was written, a separate read-only SSH session used `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74` to run `D:\1c\mcp\run-mcp-stack.ps1 -Action Status` and list `D:\1c\mcp`; all nine stack components reported `True`. This confirms the observed stack status and directory listing only, not PostgreSQL effective grants, the COM writer boundary, or transaction/quiescence behavior.
- An independent read-only `database-reviewer` reviewed the source grant map and exact helper/trigger paths at base HEAD `0fe023db1ec2adcf1820356db1dd1db09d23c3ab`; the final static crosswalk covers recovery stages and identified UPSERT paths. Result: no missing granted mutation signature after adding `set_sweep_policy` and `renew_writer_lease`; no single all-path lock order is proven. The launch record does not expose model or reasoning effort; these are NOT_VERIFIED and are not inferred.
- `git diff --check` was invoked during this turn. It emitted line-ending warnings for `docs/phase2/artifacts/WP4_WP10_DEPENDENCIES_2026-10-21.md` and `governance/DOCUMENT_REGISTRY.md`, and no whitespace diagnostics. No tests, builds, CI, migrations, live database access, or remote calls were performed.
- GPT-PM review via PM Bridge request `4eaa72a1-b8e4-465e-aa0c-17305ea93891` returned **APPROVE** for its reviewed six-file package, 0 BLOCKER, 0 MAJOR and two MINOR items. A second review, request `8ef10f76-4f0d-4c63-a980-f1fe9234f92e`, correlated reply `630d0b43-f392-5ff8-9fb0-cc064d32ce92`, returned **APPROVE**, 0 BLOCKER, 0 MAJOR and one MINOR; it verified the two earlier findings as closed and identified a traceability gap between the `complete_signed` wrapper and final `complete` definition. That gap was corrected with direct references to wrapper 007:418-435 and final body 021:46-110. A third review, request `49c2b337-2a90-4ff3-85a5-d510a98b61e7`, correlated reply `167e91af-1629-5366-a964-f6ad5f022b78`, returned **APPROVE**, 0 BLOCKER, 0 MAJOR and one MINOR. It confirmed the traceability correction and requested a clearer S13 current-state cell; that cell was updated to distinguish completed source tracing from broader in-progress engineering. The reviewer said this narrow correction did not require another full pass. Each approval was scoped to its attached local-documentation set, not a Git diff, SQL execution or migration verification.
- The original work record said no files were staged because the then-available task wording was interpreted as forbidding Git staging. The operator clarified on 2026-10-22 that the prohibition concerns a staging deployment, not Git's index, and explicitly authorized staging and local commits with a dedicated change record and lesson per commit. That clarification supersedes the earlier interpretation. No push was performed.

## Lesson

A row-trigger coverage map and source grant list do not prove a shared writer fence. Final function versions, explicit grants, helper and trigger locks, and PostgreSQL trigger firing order must be reconciled before designing recovery activation.

## Static lock-graph follow-up — 2026-10-23

### Change

- Extended `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md` with a source-level FK relation map for change-ledger migrations 004–026, the associated trigger-generated writes/reads, and an explicit split between closed declarations and still-open ordering edges.
- Added exact source anchors for the known `records` self-reference SCC, its child relations, the independent `grants`, `approval_nonces`, `holds`, and `registry_changes` parent edges, current advisory namespaces, and representative unique-conflict domains.
- Corrected the graph description to note that `dispatch_permits` has no `grant_id` FK in its DDL and that the current source does not establish pairwise deadlock freedom.

### Evidence and limits

- Sources read: `db/phase2/004_change_ledger.sql` through `026_lifecycle_checkpoint_payload_minimization.sql`, the current S13 inventory, and `S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`. Repository migration enumeration confirms files 001–026 are available; this follow-up's change-ledger graph scope is 004–026.
- Static searches covered `REFERENCES`/`FOREIGN KEY`, trigger declarations, advisory-lock calls, row-lock clauses, and `ON CONFLICT`/unique-index declarations. No database connection or SQL execution was used.
- Closed evidence is limited to declarations and source-visible first edges. Open items recorded in the inventory include a universal pre-row entry fence; deterministic ordering within the records self-SCC and child relations; `validate` record-before-key and token-before-record source orders; parent prelocks for evidence, witness cosign, anchor-gap cosign and approval-envelope paths; lifecycle/event-chain trigger ordering; global identity and verifier-material lock participation; and exact cross-path conflict/wait behavior.
- No tests, checks, builds, migrations, database writes, or service actions were run. No migration or application source was edited. Existing staged and concurrent work was preserved; no commit or push was made in this follow-up.
