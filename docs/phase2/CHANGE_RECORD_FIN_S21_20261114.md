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

## Follow-up implementation — store read failures around apply claim

Source review found that `S16Core.apply` read the persisted receipt outside an exception boundary before claim, during repeated-claim handling, and immediately after `claim_once`. A store exception or malformed post-claim object could escape the core or leave a claim reserved before `BEGIN_APPLY`. The core now maps pre-claim read exceptions and malformed stored objects to fixed refusals. If the post-claim read fails or does not match the claimed transition and approval, it invokes the existing pre-begin release path; no apply-port call is made from that branch.

This is source-only evidence. The focused failure-injection regressions remain `NOT_RUN` under operator rule 4; FIN-S2.1 remains `PARTIAL` and no database-backed claim, listener, production binding, or real 1C write is established.

## Follow-up implementation — store read failure after `BEGIN_APPLY`

Source review found that the post-claim receipt read was guarded, but the same read occurs after `BEGIN_APPLY` has already been durably saved. The existing failure branch was shared with the pre-begin path and could release a claim after the durable transition, allowing another caller to race recovery. The post-begin read now returns the fixed `AUDIT_UNAVAILABLE` refusal without releasing the claim or calling the apply port; the persisted in-progress anchor remains for recovery. The S16 coverage map now distinguishes pre- and post-`BEGIN_APPLY` behavior.

This is source and contract evidence only. The failure-injection regression is `NOT_RUN` under operator rule 4; FIN-S2.1 remains `PARTIAL`, and no database-backed claim, listener, production binding, or real 1C write is established.

## Local commit gate attempt

The local commit was not created. The pre-tool commit gate required a fresh GPT review receipt. The bounded FIN-S2.1 review invocation reached the review tool but returned `ERROR` because its request body exceeded 8,388,608 bytes; it produced no GPT verdict and is not an approval. The review input included the selected FIN-S2.1 paths, but the repository review builder also includes unrelated untracked files. A clean scratch-worktree retry did not reach GPT because PM Bridge has no project-to-conversation binding for that temporary path; the copy was returned to a clean state and removed, with the patch preserved outside the repository. No hook was bypassed and no source files were discarded. Next: obtain a bounded review receipt through the existing ERP_MCP project binding, then retry the local commit.

## Follow-up implementation — fail-closed status store read

Source review found `S16Core.status` read the change store and validated the issued receipt without an exception boundary or exact receipt/error-type checks. A store exception, malformed result, or validator exception could escape the core rather than return its fixed refusal contract. Status now maps these cases to `AUDIT_UNAVAILABLE` and serializes no malformed value; an absent receipt still returns `REF_OUT_OF_SCOPE`. The S16 coverage map records the failure-injection scenario.

This is source and contract evidence only. The focused status-store regression remains `NOT_RUN` under operator rule 4; FIN-S2.1 remains `PARTIAL`.

## Follow-up implementation — guard expiration and verification reads

A complete `ChangeStore.get` scan found unguarded reads in `S16Core.expire()` and `S16Core.verify()`, plus an unguarded expiration read-back after the transition had been saved. These paths now return fixed `AUDIT_UNAVAILABLE` on store exceptions, malformed receipts, validator exceptions, or malformed refusal values. An absent record remains `REF_OUT_OF_SCOPE`; after expiration is saved, a failed read-back leaves the durable transition for recovery rather than attempting a rollback. `verify()` also rejects a malformed change ID/document reference before the store call.

These are source and contract changes only. Failure-injection regressions remain `NOT_RUN` under operator rule 4; FIN-S2.1 remains `PARTIAL`.

## Follow-up implementation — preserve receipt identity on read-back

The expiration and pre-`BEGIN_APPLY` claim-release paths previously accepted a post-save receipt when only its S12 lifecycle record matched. They now also require the original change ID, version, scope, proposal, snapshot, requester, target version, document reference, and approval to remain identical. A mismatched read-back returns `AUDIT_UNAVAILABLE` and is not reported as a successful transition.

This is source-only hardening; the mismatched-read-back regression is `NOT_RUN` under operator rule 4.

## Follow-up implementation — validator exception and error-code boundaries in apply

Source review found that approval-time and apply-time calls to `validate_issued_receipt` could let validator exceptions or non-registry error values escape. The post-`BEGIN_APPLY` path also trusted `validate_current_target` to return a registered `ErrorCode`. These boundaries now fail closed: validator exceptions or malformed refusal values become `AUDIT_UNAVAILABLE`; target-validator exceptions or malformed refusal values become `TARGET_REJECTED`. The post-`BEGIN_APPLY` branch retains the claim and durable in-progress anchor and does not call the apply port after these failures.

This is source-only evidence. No regression tests or checks were run under operator rule 4; FIN-S2.1 remains `IN_PROGRESS` and unaccepted.

## Follow-up implementation — bind approval decision read-back to its receipt

Source review found that after `consume_decision_ref_and_nonce` durably stored an approval, `approve()` read the receipt back and accessed its fields without checking the returned type or immutable identity. A malformed adapter result could raise after nonce consumption, and a different receipt carrying the same approval/lifecycle values could be reported as success. The core now requires the exact `DomainReceipt`, the original change/version/scope/proposal/snapshot/requester/target/document identity, and the exact decision and S12 transition before recording in-memory anchors or returning success. If the read-back is unavailable or mismatched, the durable decision remains for reconciliation and the caller receives `AUDIT_UNAVAILABLE`.

This is source-only evidence. No regression tests/checks were run under operator rule 4; FIN-S2.1 remains `IN_PROGRESS` and unaccepted.

## Follow-up implementation — validate apply-port receipt before persistence

Source review found that `S16Core.apply()` checked only the exact `ApplyReceipt` class and matching `change_id` before persisting a port result. Invalid status, correlation ID, or document-reference text could therefore be stored and rejected only later by the MCP serializer. The core now validates the same UTF-8, control-character, and length bounds as the serializer before persistence. A malformed or mismatched result returns fixed `APPLY_UNKNOWN` and is not saved because the port call may already have crossed the execution boundary. The S16 acceptance map records malformed status, correlation, and document-reference results.

This is source and contract evidence only. The focused failure-injection regression is `NOT_RUN` under operator rule 4; FIN-S2.1 remains unaccepted. No database-backed claim, listener, production binding, or real 1C write is established.

## Follow-up implementation — verify apply-result persistence before success

Source review found that `apply()` returned success immediately after `save_apply_receipt()` returned without an exception. A store that silently failed to persist or returned inconsistent state on read-back could therefore produce false success. The core now reads the receipt after saving and requires exact equality with the expected receipt containing the accepted apply status and document reference before setting the in-memory verification anchor. A failed, missing, malformed, or mismatched read-back returns `APPLY_UNKNOWN`; the apply port is never retried because it may already have executed. The acceptance map now includes no-op, exception, and mismatched-read-back cases.

This is source and contract evidence only. The focused failure-injection regression is `NOT_RUN` under operator rule 4; FIN-S2.1 remains unaccepted. No database-backed claim, listener, production binding, or real 1C write is established.

## 2026-11-15 — validate approver session and decision response at the page boundary

Source review found that the approval app accepted a role container by membership alone and showed a success page after checking only part of the returned `ApprovalDecision`. The app now requires exact approver identity, role-container, epoch, and scope shapes before service dispatch. After a decision call, it validates the ticket/action/session/approver/scope binding, version, digest formats, and future-aware expiry before showing success; malformed results map to a fixed refusal. The S16 acceptance map records both cases.

This is source and contract evidence only. The focused ASGI/session/service regressions are `NOT_RUN` under operator rule 4; FIN-S2.2 remains unaccepted. No listener or production binding was enabled.

## Focused verification follow-up — align synthetic callers with page-issued CSRF

The first focused run exposed a fixture defect, not a product authorization gap: `approve()` and direct core-service callers omitted the CSRF token returned by `open_preview()`, which the core correctly requires. Updated only `tests/phase2/s16_helpers.py` and `tests/phase2/test_s16_approval_core.py` to pass that exact token. The failure-injection replay assertion remains fail-closed after a durable decision/read-back mismatch.

Verification: `uv run --locked --extra dev python -m pytest tests/phase2/test_s16_approval_core.py -q` — `48 passed in 1.00s`, run by `functional-test-reviewer` at HEAD `147743e173b1f675f7726ff26aa8ca0995e40f82`. No product code changed in this follow-up. No listener, production binding, database-backed approval, or real 1C write is established.
