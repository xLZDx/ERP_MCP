# Change record: Reconcile WP0 access and S13 grant evidence

## Change

- Updated the current operational backlog and WP0 plan to use the operator-approved direct local MCP route, keep the verified Apache/proxies and Ivan stack running, and distinguish read-only source evidence from gate acceptance.
- Added a follow-up correction to the WP0 access note: strict SSH to Ivan succeeded, all nine stack components reported `True`, and a direct local source-health/account read returned 15 machine-reconciled rows. No credential or row content was printed.
- Corrected the S13 ownership inventory: the operator is accountable, Ivan Stack (`ERP_MCP_Ivan_Stack`) owns the existing host/connection boundary, and the future private writer is an S13/S14 deliverable rather than an existing deployed service.
- Recorded the read-only disposable PostgreSQL grant audit: the separate `change_ledger` schema was absent, so its S13 grants remain `NOT_VERIFIED`; role-scoped grants and function privileges on the existing `bag` schema are separate observations. The `bag` catalog was also checked separately for a same-named `change_ledger` table; that table lookup is not the evidence for absence of the separate schema.
- Preserved the earlier wrong-route connector errors and ownership search as historical facts with explicit dated corrections rather than rewriting their provenance.

## Why

The 2026-10-22 operator clarification identified a live local gateway path and an already-trusted Ivan host key, and assigned technical ownership for the Ivan connection stack. The earlier connector recheck used an unapproved tunnel route and therefore did not block the specified local gateway. The authorized disposable database does not contain the S13 schema, so its grants cannot establish the future writer service's effective privileges.

## Contracts and paths

- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/AUTONOMOUS_EXECUTION_PLAN_2026-10-21.md`
- `docs/phase2/artifacts/WP0_MCP_ACCESS_RECHECK_2026-10-22.md`
- `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-22.md`
- `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`
- `docs/phase2/artifacts/WP4_WP10_DEPENDENCIES_2026-10-21.md`
- `docs/commits/2026-10-22-erp-mcp-route-recheck.md`
- `docs/commits/2026-10-22-erp-owner-source-audit.md`
- `core/LESSONS_LOG.md`

During the follow-up correction activity, no service was started or restarted, no database schema/data was changed, no migration was run, and no gate/manifest state was changed. The earlier same-day startup observations are retained and labeled historical in the WP0 note; their service-start/readiness checks are not test-suite results. The public `SECURITY DEFINER` routine finding is recorded for focused authorization review; this documentation correction does not claim an exploit or fix.

## Decisions

- Never use `ERP_MCP_REAL1` for this task. Mint the local `auditor` token in process and use the local gateway.
- Keep the historic 15-versus-16 row discrepancy open; the local read is not a human-signed accounting report or G1/G2 acceptance.
- Keep S13 effective `change_ledger` grants `NOT_VERIFIED` until the permitted disposable qualification environment contains that schema and the database reviewer can inspect its effective grants.
- Do not edit 022–024 or activate recovery from this evidence. Keep lifecycle `NOT_READY`.

## Verification state

- Read-only strict SSH command: `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status"`; exit 0 and all nine reported components were `True`. A separate names-only directory listing of `D:\1c\mcp` also exited 0.
- Read-only MCP calls used `.venv\Scripts\python.exe`, `LaneEnv.load()`, and `Idp(env).token("auditor", ttl=3600)` in process. `source_health` returned `ok=true`; `accounting_balance_by_analytics` returned 15 rows with `VALIDATED_MACHINE_RECONCILED`, `PROFILE_VALIDATED_MACHINE`, `MACHINE_TWO_SOURCE`, and warning `MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT`. The token, row values, amounts and names were not printed.
- The read-only `database-reviewer` used per-role connections from `LaneEnv` to inspect the disposable database on port 18432. The separate `change_ledger` schema and its functions were absent; independently, no `bag.change_ledger` table or matching table grant was found in the existing `bag` schema. The reviewer recorded project role flags/memberships, scoped table/function grants, no RLS among 15 `bag` tables, and the `PUBLIC EXECUTE` `SECURITY DEFINER` function for follow-up. No schema/data mutation occurred.
- `CT14Писатель` results remain in-repository clone measurements (`818HA_p2diff`) only; they are not verified as live Ivan rights.
- No tests/checks were run for the follow-up documentation correction; earlier service-start readiness checks are described in their historical section. No builds, CI, migrations, database writes, COM writes, deployment, push, or PR occurred. Local diff is not yet committed; exact staged patch review is required before each local commit.

## Related implementation status

The staged dependency artifact also records that the focused security reviewer rated the `PUBLIC EXECUTE` finding MINOR and that migration 015 is implemented but `NOT_RUN / NOT_RUNTIME_VERIFIED`. That implementation is a separate, currently unstaged change recorded in `docs/commits/2026-10-22-capability-function-execute-revocation.md`; it is not part of this documentation-only patch. No post-migration privilege claim is made here.
