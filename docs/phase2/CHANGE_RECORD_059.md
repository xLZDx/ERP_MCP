# Change record 059 — verify actual G1 scope revocation after restore

## What changed

- Replaced the no-op `living.role_scope` update in the cross-cluster restore scenario with a delete of the exact `living_reader` grant for tenant A and source s1.
- Asserted that a context opened before deletion and a fresh context afterward are both denied in the source and restored target databases.
- Updated the G1 backlog, decision log, and document registry.

## Why

GPT-PM static review request `5d3e9bb2-cc4f-40a3-afc2-269faf379fb6` identified MAJOR G1-M01: updating `source_id` to itself did not revoke the authorization and could not prove a fresh session could not reacquire the scope. The review rejected exact HEAD `99b7d4c6bdee9284b59ad405e97f810cc536ebd8` and did not authorize push.

The replacement removes exactly one existing grant, requires a fresh connection to fail `living.set_scope`, and requires an already scoped connection to fail after deletion. SQL 003 checks whether the grant remains before comparing the captured scope epoch, so both denial paths are expected to report `SCOPE_NOT_GRANTED`.

## Contracts and paths

- `tests/phase2/test_g1_restore.py`
- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `docs/phase2/CHANGE_RECORD_059.md`
- `core/DECISION_LOG.md`
- `governance/DOCUMENT_REGISTRY.md`

## Verification state

- The `functional-test-reviewer` updated the focused scenario. This is source-level remediation only; no tests or checks were run.
- Runtime remains `NOT_RUN` because `D:\Repo\AGENTS.md` prohibits pytest. No database, container, or migration was touched.
- At this commit, a complete PM re-review was pending. It was subsequently completed at exact HEAD `17b6de78743f2e40f6ae0f6bca322b4e87ba7d96`; see `CHANGE_RECORD_060.md`. This static approval does not satisfy runtime or final push approval.
