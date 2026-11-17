# FIN-S16 bounded hardening record — 2026-11-14

## Scope and safety boundary

This record covers source and test-contract changes made while continuing FIN-S2.1, FIN-S2.2 and FIN-S2.3. They remain isolated S16 code and fake-backed acceptance work. This record does not enable a listener, wire S16 into the gateway, qualify the S14 writer, authorize a database or real 1C write, or claim sprint acceptance.

## Findings and changes

1. **FIN-S2.1 — apply-time requester registry validation.** The current requester record and dependency-epoch result were treated as trusted typed values after crossing the registry port. `S16Core.decide` now requires an exact `PrincipalRecord`, an exact boolean non-revoked state, a non-empty exact person identifier matching the persisted receipt, a nonnegative exact integer epoch matching the proposal, and an exact boolean `epochs_current` result. Malformed registry state returns `EPOCH_CHANGED` before the claim/apply boundary. The S16 E16-3 contract now requires malformed-registry cases to refuse with zero apply-port calls.

2. **FIN-S2.2 — approval-page ASGI receive bound.** The form body already had an 8192-byte cap but its receive loop did not cap ASGI message count. The page now caps the request at 8192 messages, rejects non-dict events and non-boolean `more_body`, and refuses disconnects or non-request event types. Its 8192-byte cap remains in place. The E16-1 contract now covers empty-message flooding, malformed events, invalid framing and byte overflow, all before `submit_decision`.

3. **FIN-S2.3 — aggregate MCP argument budget.** `_validate_tree` bounded individual values and node count, while the aggregate limit was checked only after creating a `repr` of the full arguments. Traversal now accounts for aggregate keys and values before that conversion, rejects invalid UTF-8 strings and non-finite floats, and retains the post-render limit as defense in depth. E16-3 now requires safe schema refusal and zero service calls for oversized or malformed inputs.

## Acceptance and verification state

- The scoped source changes and the corresponding S16 acceptance-contract updates are recorded in `docs/sdlc/verify-evidence.md` and `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md`.
- No tests, checks, builds, migrations, CI, listeners, database operations, credentials, or 1C business operations were run or used as evidence.
- FIN-S2.1, FIN-S2.2 and FIN-S2.3 remain `IN_PROGRESS`; source inspection and contract edits are not acceptance. Their regression cases must be executed by the assigned test roles only if the operator's automatic-test restriction is revised.
- Commit, review and sprint-gate status remain governed by the repository hooks and `AGENTS.md`. Do not bypass a hook to deliver this record or source changes.

## Follow-up implementation — reject a single oversized approval-form chunk before buffering

The approval form previously appended a received chunk and checked total size afterward. It now checks each chunk against the remaining 8 KiB budget before copying it into the accumulated form body. The S16 E16-1 contract requires the oversized single-message case to refuse before the append and before `submit_decision`.

Focused regression remains NOT_RUN because operator rule 4 prohibits test/check execution. FIN-S2.2 remains `IN_PROGRESS` and unaccepted.

## Follow-up implementation — bound escape-expanded MCP arguments

The aggregate tree check previously counted source UTF-8 bytes, but the dispatcher subsequently builds a Python `repr`, which can expand control characters. The traversal now counts rendered string/key bytes plus container punctuation and bounded scalar representations before the whole representation is built; integer digit size is estimated before conversion. The existing final representation check remains as a second guard. The E16-3 coverage row includes escape-heavy strings.

Focused regression remains NOT_RUN because operator rule 4 prohibits automatic test/check execution. FIN-S2.3 remains `IN_PROGRESS` and unaccepted.

## Follow-up implementation — classify infrastructure failures and preserve post-BEGIN expiry state

`claim_once` exceptions now return `AUDIT_UNAVAILABLE` instead of being mislabeled as an expired claim. Clock failures on both approval-page routes return HTTP 503 with the registered `AUDIT_UNAVAILABLE` refusal; genuine authentication failures remain HTTP 401. If approval, snapshot, or requester expiry is observed after durable `BEGIN_APPLY`, the coordinator returns `APPROVAL_EXPIRED` without attempting the S12 `EXPIRE` transition: that transition is only valid before execution starts, while the consumed claim and `APPLYING` anchor must remain available for recovery. No apply-port call is issued on this refusal path.

Focused regression evidence is pending the assigned test role. This change does not qualify the writer, connect the approval lane to production, or establish sprint acceptance.

Focused regressions after these changes: the assigned functional-test-reviewer ran only `tests/phase2/test_s16_approval_core.py` and `tests/phase2/test_s16_approval_page.py` at the current working tree based on HEAD `e30e2ec10bdd37b6e3d41763865857cafa969574`; 59 passed, 0 skipped, in 0.97s. The requester-expiry case sets requester expiry earlier than proposal/snapshot expiry. Exact-commit rerun remains pending because the source and tests are not committed. Independent review is pending final confirmation on the refreshed diff.

Exact-commit follow-up: at HEAD `7bbbe153259e480d8836234bf298278e2c0fdf57`, the assigned functional-test-reviewer reran the two named S16 modules and reported 59 passed, 0 skipped (0.72s). The exact-head code-reviewer, silent-failure-hunter, and python-reviewer reviews found no actionable findings. The acceptance remains fake-backed; no live IdP/browser, database durability, writer, 1C mutation, production authorization, or final sprint GPT-PM decision is established.
