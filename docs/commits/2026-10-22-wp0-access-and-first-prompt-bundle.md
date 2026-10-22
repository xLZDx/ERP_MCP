# Change record: WP0 access recheck and first autonomous prompt bundle

## Summary

This local documentation commit reconciles the operator's 2026-10-22 environment, access,
ownership, writer-boundary and Git clarifications with the earlier autonomous prompts. It adds
sanitized WP0 evidence for current local listeners, the strict Ivan SSH check, the two
read-only source calls, the Phase2 comparison limitation, and the disposable PostgreSQL grant
review. It includes the three operator-delivered autonomous prompt documents in the first
commit as requested.

## Why

The older records described a failed strict SSH route, Apache on 18088, an incorrect
interpretation of the 21200 process, and a Git staging prohibition. The operator supplied
verified corrections: Apache/proxies already run on 8088, 21200 is the project venv-launched
Phase2 module, Ivan is reached as `koros@100.88.71.74` with strict host verification, Git
staging/local commits are allowed, and the Ivan stack owns the intended private writer host
boundary. The new runtime evidence also found unresolved source and service-configuration
gaps, which are recorded without financial rows, amounts, names, tokens or DSNs.

## Paths

- `docs/phase2/AUTONOMOUS_EXECUTION_PLAN_2026-10-21.md` — marks 2026-10-21 environment
  observations as historical and points to the current correction.
- `docs/phase2/AUTONOMOUS_AGENT_PROMPT_2026-10-21.md` — marks the first-round prompt as
  superseded and corrects the stale branch, Apache and Git-staging statements.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md` — makes the latest operator decision
  authoritative and links the current WP0 evidence.
- `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-22.md` — records current-turn
  runtime, source and grant observations with values and names omitted.
- `docs/phase2/artifacts/WP4_WP10_DEPENDENCIES_2026-10-21.md` — marks older table facts as
  superseded and updates current dependencies and ownership.
- `docs/phase2/S13_BUSINESS_KEY_LOCK_ORDER_NOTE_2026-10-22.md` — clarifies technical ownership
  versus the absence of a named human contact.
- `core/DECISION_LOG.md` — records the current operator decisions and scope.
- `core/LESSONS_LOG.md` — records the route-specific-token and sanitized-comparison lesson.

The three autonomous prompt documents were untracked operator deliverables at the start of this
turn. Existing changes in the dependency note and project logs were also present before these
edits. They were reviewed and are included only as task-related history; this record does not
attribute their earlier creation to the current turn. `MCP-RSV-Data.zip` is excluded and remains
untouched.

## Decisions and boundaries

- Do not restart Apache or proxies; do not replace the running 21200 Phase2 process.
- Use route-specific short-lived tokens only in process memory; use the local gateway client
  for local calls and the trusted Ivan-issued token for the Ivan route.
- Keep the Phase2 read surface evaluation-only; the observed mismatch and tool errors are not
  promoted to a pass.
- Do not apply migrations until code/design work reaches the authorized disposable-database
  qualification phase. No source write or migration occurred here.
- Keep WP9 optional, off the critical path. Do not push or open a PR until GPT-PM approves the
  exact final head.

## Verification state

Runtime observations: local listeners on the requested ports were present; strict SSH status
reported all nine Ivan stack components `True`; local and Ivan `source_health` calls returned
healthy; account 521.1 reads returned 15 and 16 rows with unequal in-memory contents; the live
Phase2 server reported both outbound gateways unconfigured; direct in-process reconciliation
reported a partial mismatch and gateway tool errors. The read-only database reviewer found no
`change_ledger` schema/functions in the disposable PostgreSQL database, so S13 effective grants
remain `NOT_VERIFIED`. The exact sanitized evidence is linked above.

Document registry generation before this commit scanned 46 refs and recorded 426 tracked
paths. It will be regenerated after this commit so the committed WP0 artifact and change record
appear in the snapshot. No tests, lint, build, check, CI, or migration was run in this phase.
