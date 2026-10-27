# Change Record 201 — preserve unknown writer outcomes after admission

## What changed

- After admission and the invocation-stage transition, map a port-raised `ServiceError` to the stable `WRITER_OUTCOME_UNKNOWN` response with `outcome_unknown=true`.
- Added `S13-WRITER-ERROR-UNKNOWN-01` to the later disposable qualification plan. It distinguishes no-effect proof from an arbitrary exception and requires same-call lookup with no second physical invocation.

## Why

The service commits durable admission before invoking the port and has no signed no-effect evidence when the port raises. Re-raising a port-supplied `ServiceError` allowed its default `outcome_unknown=false` to escape after that commit. That response could falsely describe an unresolved external outcome as known. Only the existing signed receipt/recovery path may terminalize the call as no effect.

## Evidence and verification state

- `src/erp_mcp_private_writer/service.py` candidate SHA-256 after this focused edit: `7661D54049738983C7CD378D00BDA02CCA2E1E29370059F33B1D1F4885F1874C`. The file had pre-existing changes; this record attributes only the post-writer-call exception mapping above to this change.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` current SHA-256: `D356AD6BD740DA6BC24E2B7C4BE262B6A59F73E1B97DFEF23AF08286FA4B37C6` (recomputed after the later S13 candidate cases were added).
- The latest document-registry generation reports 46 refs, 459 tracked Markdown paths, and 110 local-only paths; registry SHA-256: `AC39AD4454D77CD460A846CE4F24611E1D8127D09A5A127398D0A0392A70F815`.
- Source inspection only. Tests, checks, build, CI, migrations, staging, commit, and push were not run; the new scenario remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: map the scenario to the exact-head functional/E2E tests after coding closes. Keep retries lookup-only until trusted evidence resolves the durable call. No runtime result is claimed.
