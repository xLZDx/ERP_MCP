# Change Record 223 — make the serving-authority lease monotonic

## What changed

- `_WindowsLease` now uses slots, fixes its mutex owner and creating thread, and refuses deletion.
- The release flag can transition once from `False` to `True`; it cannot be reset to make a released
  lease appear held again.
- Extended `S13-SERVING-MUTEX-CONFIG-IMMUTABILITY-01` with lease mutation, thread-affinity,
  single-release and post-release assertion cases.

## Why

The lease is the capability passed to startup-recovery operations. Its `assert_held()` check is only
meaningful if the bound mutex, owner thread and released state cannot be substituted or reset by
ordinary instance mutation. A second release could otherwise corrupt host-wide exclusion, while a
reset could make downstream code accept a lease that no longer owns the Windows mutex.

## Affected contracts and paths

- `src/erp_mcp_private_writer/windows_authority_mutex.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

## Evidence and verification state

`windows_authority_mutex.py` was already untracked before the current edit. Its captured pre-edit
SHA-256 was `9428AAF1F57BB677F6FEEB46F66966110BF44B5473C2413CBBA359321546FC0D`. Current SHA-256:
`F8B86771F79216887FFF72DAF99B058A19EA14562282D563CEC2D12FF60E8A56`. Current qualification
prerequisite SHA-256: `90E9C89AAF2C81DC8BDE2909471ED92AC6D251EFBB62CFFE1C8C206F45764CF6`.

Only source inspection and hash capture were performed. No tests/checks/build, Windows mutex/ACL or
lease runtime, PostgreSQL, staging, commit or push ran. Runtime qualification remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after source coding closes, functional/E2E roles
qualify lease acquisition, same-thread assertion, one-time release, post-release rejection and
constructor/ACL failure cleanup; Python/security/reliability reviewers inspect the exact host-lock
boundary.
