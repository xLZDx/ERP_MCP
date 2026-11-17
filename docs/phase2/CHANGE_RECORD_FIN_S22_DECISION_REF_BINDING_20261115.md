# FIN-S2.2 change record — bind returned decision to submitted reference

Date: 2026-11-15
Task: FIN-S2.2 — Implement the protected approval page and session boundary

## Finding

Source review found that the approval page validated the shape of the service-returned
`ApprovalDecision`, including that `decision_ref_digest` was 64 lowercase hexadecimal characters,
but did not compare it with the `decision_ref` in the submitted form. A service-boundary response
for another valid reference could therefore be rendered as “Decision recorded” for this request.

## Decision

Before returning the success page, require the submitted reference to retain its exact token shape
and require the returned digest to equal SHA-256 of those ASCII reference bytes, using a
constant-time comparison. All existing identity, scope, session, action, digest-format, and expiry
checks remain in force. A mismatched service result fails closed as `AUDIT_UNAVAILABLE`; because
the service call has already occurred, this refusal does not claim that the underlying decision was
rolled back or absent.

## Verification and limits

Focused evidence: `uv run --locked --extra dev python -m pytest tests/phase2/test_s16_approval_page.py -q`
— `5 passed in 1.37s`, run by the `functional-test-reviewer` for the FIN-S2.2 worktree at HEAD
`fcf5e6b2dffe0aeb0241c42ac6051ed2af848ebe`. No listener, production binding, or real 1C path was
enabled. This proves the named page-test file only; FIN-S2.2 still needs the remaining sprint-level
verification and review evidence before acceptance.
