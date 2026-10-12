# Phase 2 cutover plan: zero-interference to Release 1 (DRAFT)

Owner request: develop Phase 2 independently, switch only when accepted. Branch:
phase2/living-model-connectors-reconciliation from main at 94f4cee5842776d0b8810cf3f38e2682a701002a.

## Phase 1 isolation before cutover

Do not use D:\Repo\ERP_MCP-integration-candidate as the Phase 2 execution directory. It has staged/unstaged concurrent work. Do not reset, stash, kill, or copy its private environment. Use D:\Repo\ERP_MCP-phase2 for an independent git clone, dedicated .venv/containers/test DB/redis/ports/secrets/OAuth issuer/testing tunnel as required. No real 1C writes; report capture on approved disposable copies only. Branch exists remotely but independent Windows clone is not yet executed by DC_MCP, which exposes no arbitrary shell.

The Phase 2 branch starts from *committed remote main*, not every local unfinished integration change. Preserve the base commit hash and record a future forward sync as a controlled task. Do not cherry-pick unreviewed dirty files across worktrees.

## Sync strategy before switching

1. Finish/release R1 independently. Obtain signed exact R1 main commit + release evidence, configuration and migrations.
2. Integrate R1 -> Phase2 (not Phase2 -> main) in a reviewable PR/merge after R1 is stable. Do not force-push, rewrite R1 refs or discard conflicts.
3. Verify R1 API/ACL/OAuth/native report/tool parity and all R2 G0..G7 gates on exact Phase2 candidate.
4. Validate additive migration, role-grant diffs, audit provenance and restore on disposable copy before staging.
5. Deploy separate Phase2 staging using distinct credentials, storage prefixes, jobs and endpoints, with all new features disabled by default.
6. Shadow compare metadata and reports without changing accepted R1 state. No silent automatic promotions.
7. Gradually canary Phase2 for explicit source/company and approved operation; monitor p95/p99, errors, accounting differences, source load and audit.
8. Operator GO only on evidence; switch traffic via configured router/feature flag. Keep older R1 deployment and recovery route ready.
9. Roll back route flag and disable R2 jobs on anomaly; never restore revoked grants or unverified models by rollback.
10. Post-switch reconcile source state/queues and record final versioned sign-off.

## Stop conditions

Any reconciliation mismatch, unqualified native report, missing evidence, cross-tenant ACL issue, source overload, unattested accepted model, broken OAuth or audit, unbounded worker or unavailable rollback -> NO-GO.

## Current proof

Remote branch created and core Phase2 documentation committed. Isolated OBSERVED-only structural fingerprint module and 10 candidate tests committed. Container unit-check ran successfully; not an exact-branch hosted CI gate and not production acceptance. Original 38-file ZIP still in conversation artifact, not in Windows git branch until SHA-verified import via scripts/phase2/bootstrap-local.ps1.

## Decisions before actual cutover

Operator must approve Release 2 scope/ADR, accept qualifications and authorize target-specific enablement and migration. Independent Windows clone must be materialized and checked. Set actual throughput budgets from representative 1C load tests. Production remains NO-GO until gates pass.
