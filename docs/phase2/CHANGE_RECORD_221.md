# Change Record 221 — freeze serving-authority mutex identity

## What changed

- `WindowsServingAuthorityMutex` now freezes its deterministic name, process registry key, loaded
  Windows API handles and kernel mutex handle after ACL verification succeeds.
- The constructor keeps configuration mutable only until setup is complete, so its existing ACL
  verification failure path can still close a newly created handle before the object escapes.
- Added `S13-SERVING-MUTEX-CONFIG-IMMUTABILITY-01` for configuration mutation refusal, no
  instance-dictionary bypass, failure cleanup, and normal close-state behavior.

## Why

The host-wide serving mutex is the outer exclusion gate for startup takeover and physical
quiescence. Replacing its OS handle or identity after its owner/DACL was verified could redirect
later acquire/release operations to an unchecked kernel object. Only the closed/open lifecycle state
remains mutable after construction.

## Affected contracts and paths

- `src/erp_mcp_private_writer/windows_authority_mutex.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

## Evidence and verification state

`windows_authority_mutex.py` was already untracked before this edit. Its captured pre-edit SHA-256
was `0ECAA967187FCD4E05506FD3EC5FC5A39FAEFBA087A68748A0239A3448413C2D`. Current source-only
verification does not include Windows mutex creation, ACL or lease behavior. Tests/checks/build,
database access, staging, commit and push were not run. Runtime qualification remains `NOT_RUN`.

Current `windows_authority_mutex.py` SHA-256: `9428AAF1F57BB677F6FEEB46F66966110BF44B5473C2413CBBA359321546FC0D`.
Qualification prerequisite after later source closures SHA-256: `90E9C89AAF2C81DC8BDE2909471ED92AC6D251EFBB62CFFE1C8C206F45764CF6`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after code closure, the functional/E2E roles
qualify the named-mutex ACL, handle mutation refusal, lease acquire/release, close and failure cleanup;
security/reliability reviewers inspect the exact host-locking diff and its integration with COM
quiescence.
