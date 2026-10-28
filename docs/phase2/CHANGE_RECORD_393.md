# Change Record 393 - S16 sprint plan rev 2 after security and architecture review

## Ownership and scope

- Date: 2026-10-28. Documentation only: revises `docs/phase2/S16_SPRINT_PLAN_2026-10-28.md` (rev 2). No code, no tests, no gate change.

## What and why

- Two independent read-only reviews (security-reviewer, architect) found 0 BLOCKER and 7 MAJOR in rev 1: decision logic could live in fakes; apply-time re-validation (target fingerprint, principal epoch, approver liveness, claim-once race) was missing; the private listener relied on header absence; verify cannot cover POST/UNPOST (S15 supports CREATE_DRAFT only); rollback_propose had no mapping to admitted operations; nonce/preview digest ownership was unassigned; E4 named a non-existent error code.
- Rev 2 adds an S16-owned decision core, the missing assertions, a "Review resolutions" section mapping each finding to its change, and open questions Q12-Q14.

## Verification state

- NOT_RUN: re-review of rev 2, GPT-PM review. Documentation-only.
