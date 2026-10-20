# Change record 137 — regenerate document registry after S13 backlog reconciliation

## Goal and scope

Refresh the repository's generated document inventory after CR136 and include the reconciled S13 operator backlog and its linked change record.

## Changes and affected paths

- Regenerated `governance/DOCUMENT_REGISTRY.md` with `node scripts/build_document_registry.mjs`.
- The generator exited 0 after scanning four refs: local `main`, two worktree refs, and `origin/main`.
- The generated inventory reported 203 tracked paths and zero local-only paths at generation time.

## Verification and limits

- Documentation generation only; no tests, runtime checks, database access, or migration execution were performed.
- Registry output is an inventory and does not validate acceptance or gate status.

## Ownership and next action

- The operator remains accountable for delegated project closure; GPT/Codex performed this registry refresh.
- Formal S13, R-01/R-03, G1–G8 and release statuses remain as documented in the current S14 packet and gate manifest.
