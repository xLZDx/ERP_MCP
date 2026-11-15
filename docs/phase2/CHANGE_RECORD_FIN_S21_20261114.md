# FIN-S2.1 implementation record — 2026-11-14

## Scope

This record covers the fake-backed S16 core implementation for FIN-S2.1 only. It does not qualify a database-backed claim, enable a listener, or authorize a real 1C write. The production surface remains read-only.

## Decisions and implementation

- Keep approval policy in `S16Core`, not in permissive persistence fakes. The core validates token class, requester/approver independence, binding identity and session, nonce/digest/version/scope/expiry metadata, and current principal/target state.
- Compare the binding's `requester_person_id` with the persisted receipt's requester before using the binding for the independence check. A mismatched binding is refused as `APPROVAL_NONCE_INVALID`.
- Revalidate requester identity, epoch dependencies, approver validity, kill switch, target fingerprint/version, and expiry before the apply port. Use the process lock plus `claim_once` so only one contender can enter the apply path; an unknown apply outcome is not retried.
- Validate requester and approver principal/registry field shapes before role membership. Normalize untrusted expiry timestamps to UTC before comparison and fail closed on malformed values.
- `ChangeService`/`ApprovalService` own preview digest and nonce issuance. The page renders the service-returned canonical bytes covered by the digest; model-supplied approval claims cannot replace them.

## Evidence and remaining acceptance

- Current source inspection verified the S2.1 acceptance paths in `src/erp_mcp_s16/core.py`; the task contract is in `docs/sdlc/backlog.md` under S2.1.
- The ledger remains `in_progress` with class `PROHIBITED`: task-specific regression tests are NOT_RUN because `AGENTS.md` operator rule 4 prohibits automatic test/check execution. No S2.1 test, check, build, CI, migration, listener, database, or 1C operation is claimed here.
- A permitted sprint verification window and the assigned test role are required before formal acceptance. This record does not mark FIN-S2.1 complete.

## Follow-up implementation — malformed registry and claim results

Source inspection found that target permission, principal independence, and epoch-dependency results were accepted using Python truthiness. A typed port returning a malformed positive value such as `1` could pass. The core now requires an exact `TargetRecord` with `allowed is True` as an exact boolean, a typed scope/version, and unchanged target version at approval/apply revalidation. It requires exact boolean results for independence and epoch checks, validates approver principal/role/revocation types, and validates the claim token plus refusal error before relying on the store result. The S16 coverage map now specifies malformed-return cases and fail-closed expectations.

This is source and contract evidence only. Focused regression tests were not run because operator rule 4 prohibits automatic tests/checks. FIN-S2.1 remains `IN_PROGRESS`; no database-backed claim, listener, production binding, or real 1C write was enabled.

## Follow-up implementation — bind requester registry identity before approval persistence

The approval decision path previously checked that the current requester registry row was not revoked and matched the person ID and epoch, but it did not check that the row's principal ID matched the issued proposal, its lane matched the proposal scope, or its roles contained an exact `REQUESTER` enum. The core now checks those fields and rejects malformed role containers/members before the decision reaches the store. The S16 test coverage map now requires zero approval-persistence calls for those malformed registry rows.

This is source and contract evidence only. The focused regression is `NOT_RUN` because operator rule 4 prohibits tests/checks in this sprint. FIN-S2.1 remains unaccepted until the authorized verification stage.

## Local commit gate attempt

The local commit was not created. The pre-tool commit gate required a fresh GPT review receipt. The bounded FIN-S2.1 review invocation reached the review tool but returned `ERROR` because its request body exceeded 8,388,608 bytes; it produced no GPT verdict and is not an approval. The review input included the selected FIN-S2.1 paths, but the repository review builder also includes unrelated untracked files. No hook was bypassed and no files were discarded. Next: make the review input bounded without hiding or deleting the other worktree files, then obtain an actual review result before retrying the local commit.
