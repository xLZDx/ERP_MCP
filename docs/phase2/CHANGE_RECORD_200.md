# Change Record 200 — bound canonical UUID parsing

## What changed

- Added an exact 36-character precondition to the shared canonical UUID parser and retain its single parsed `UUID` object for process-instance variant/version checks.
- Preserved exact lowercase canonical text and nonzero UUID requirements; process UUIDs still require RFC variant and version 1 through 8.
- Added `S13-PYTHON-UUID-01` to the disposable qualification plan for oversized and noncanonical inputs, valid controls, and the independent SQL boundary.

## Why

`UUID(value)` has work proportional to the supplied string length. The shared predicate could receive noncanonical values and would parse them before rejecting them by round-trip comparison; the process predicate parsed accepted values a second time. Exact wire-length rejection bounds that parser input and the shared parse keeps policy consistent.

## Evidence and verification state

- `src/business_ai_gateway/phase2/change_ledger/uuid_contract.py` SHA-256: `AD567CC8710F96CE52E92527D3624D2550740B1C40FA4E6B1884E28CEE0E060A`.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` current SHA-256: `D356AD6BD740DA6BC24E2B7C4BE262B6A59F73E1B97DFEF23AF08286FA4B37C6` (recomputed after the later S13 candidate cases were added).
- The latest document-registry generation reports 46 refs, 459 tracked Markdown paths, and 110 local-only paths; registry SHA-256: `AC39AD4454D77CD460A846CE4F24611E1D8127D09A5A127398D0A0392A70F815`.
- Source inspection only. Tests, checks, build, CI, migrations, staging, commit, and push were not run; the new qualification case remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: include the new case in the exact-head functional/E2E map after all in-scope coding closes; database review must compare Python and SQL UUID predicates. No runtime or database qualification is claimed.
