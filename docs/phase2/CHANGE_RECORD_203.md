# Change Record 203 — require canonical UUID text at writer admission

## What changed

- `_identity` now checks the exact UUID wire length before parsing `change_id`, `call_id`, `permit_id`, and an optional repair-authorization ID.
- After parsing and nonzero validation, the change and call IDs must equal their original lowercase canonical text, matching the existing exact comparison for permit and repair IDs.
- The refusal occurs before database admission and writer selection. The qualification case was already specified by `S13-INVOCATION-CONTEXT-BINDING-01`.

## Why

The previous code parsed change and call IDs and placed their normalized forms into `CallIdentity` without checking the original text. UUID-equivalent uppercase or braced inputs could therefore cross the service boundary as a different accepted representation. Exact-text rejection preserves the signed/call identity contract and bounds parser input before normalization.

## Evidence and verification state

- At change 203's checkpoint, the full candidate source `src/erp_mcp_private_writer/service.py` SHA-256 was `4E18F251A8664EFAAB78095E3A2FD32480E327C6DB503B43FBE4D8FAF22D2CF0`. The file had pre-existing changes; only the canonical UUID checks above are attributed to change 203.
- At change 203's checkpoint, qualification plan `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` SHA-256 was `5354990D58BFE1D1A04F3CED55D4F132F34E70778BE55A33E54F92979064D4AD`.
- The current qualification plan SHA-256 is `D356AD6BD740DA6BC24E2B7C4BE262B6A59F73E1B97DFEF23AF08286FA4B37C6`. The latest registry contains 110 local-only paths and has SHA-256 `AC39AD4454D77CD460A846CE4F24611E1D8127D09A5A127398D0A0392A70F815`.
- A read-only `code-reviewer` pass found no issue in this focused change; model/effort metadata was unavailable (`UNKNOWN`). This is source review only and does not change the qualification state.
- Static source inspection only. Tests/checks/build, migration, database access, COM, service startup, and disposable qualification were not run. `S13-INVOCATION-CONTEXT-BINDING-01` remains `NOT_RUN`.
- The source file had pre-existing modifications. This record attributes only the pre-parse length and exact canonical-text checks above to this change.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: after all in-scope coding closes, assign uppercase, braces, compact, URN, overlength, nil, and canonical controls to the functional/E2E roles; qualify SQL UUID constraints independently through the approved disposable-database path.
