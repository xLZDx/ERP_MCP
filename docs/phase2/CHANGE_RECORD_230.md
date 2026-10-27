# Change Record 230 — record current Ivan stack boundary evidence

## What changed

- Added the current-turn strict SSH status and read-only service-directory inventory to the WP0 access/source recheck artifact.
- Explicitly records that the inventory does not establish the licensed clone identity, current effective 1C rights, or COM transaction semantics.

## Why

The stack health check and service-directory listing are narrower than the acceptance requirement for current clone rights and the physical writer transaction boundary. The durable record keeps that distinction visible and prevents a healthy stack status from being treated as proof of write qualification.

## Affected contracts and paths

- `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-25.md`

## Verification state

The evidence artifact was already untracked/modified before this turn; its pre-edit hash was not captured. Current SHA-256: `EAC8681F1B0C3F25472E0BCFC48EBCC83EA98E3AD9A2013E04095F6526CC25EA`.

The recorded command used strict host-key checking and returned `True` for postgres, redis, apache, proxy8191–8193, sidecar, IdP and gateway. The directory listing emitted filenames only. No file contents, credentials, COM operation, database operation, service change, restart, test, check, build, migration, staging, commit or push occurred.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Ivan stack is the technical owner of that host stack. Next: use its authenticated service identity to obtain a read-only current clone/security profile and separately determine whether its connector provides the required transaction boundary; do not infer either from this inventory.
