# S19 production canary recipe — preparation only

Status: **NOT EXECUTABLE**. This is a preparation artifact for G6, not permission, a target
selection, or evidence that a canary ran. No production canary was executed while preparing it.

## Entry conditions

Before scheduling any G6 action, the evidence bundle must establish all of the following on the
applicable exact heads:

1. G3 accountant attestation is `PASSED`.
2. G5 user acceptance is `PASSED`.
3. G6-pre operational readiness is `PASSED` with measured workload, alarms and repeatable
   recovery evidence.
4. G8 controlled-change acceptance is `PASSED` for all required scenarios and exact-head review.
5. The production target is registered by its authenticated base fingerprint and company scope.
6. The operator signs a separate, bounded permission containing the exact base, company,
   operation, amount limit, expiry and purpose.
7. A named rollback owner, independent observer, change window and notification route are recorded.

At the S19 residual-register snapshot, the entry gates G3, G5, G6-pre and G8 are `NOT_PASSED`;
G6 itself has not run, and production authorization is `NONE`. Staging is never a substitute for
the production canary and remains denied for writes. General release additionally requires G7
and the separate operator `PRODUCTION_GO` decision; this recipe grants neither.

## Values that must be filled by the later authorized change record

| Field | Required value | Current value |
|---|---|---|
| Exact production base fingerprint | Registered immutable target identity | `UNSET` |
| Company / organization scope | Exact registered scope | `UNSET` |
| Operation | One already-qualified low-risk operation from the approved catalogue | `UNSET` |
| Amount / count limit | Explicit finite cap; no inferred default | `UNSET` |
| Window and expiry | UTC start/end and permission expiry | `UNSET` |
| Purpose and expected effect | Specific business outcome and independent read-back | `UNSET` |
| Rollback owner and route | Named person and reachable escalation path | `UNSET` |
| Operator signature | Signature over the exact scope and expiry | `NOT_PROVIDED` |

Do not fill these placeholders from a model suggestion or environment label. The authorization
decision must bind the registered target fingerprint and the selected company/operation at the
writer boundary.

## Safeguards and execution outline (not an executable command sequence)

1. Freeze the exact reviewed code/configuration head and verify the four entry gates again.
2. Verify the registered target fingerprint, company, operation allowlist, permission expiry,
   finite limit, private ingress and kill switch. Deny staging and any mismatched target.
3. Have the operator sign the bounded G6 permission; store the receipt outside source control and
   bind its digest and exact scope to the change record. Do not put credentials or signature secrets
   in this document.
4. Start only within the signed window with an independent observer. Submit one proposal through
   the approved UI/API; a second request or a retry is not authorized by this recipe.
5. Require audit-before-effect, the one-use approval, exact company/target/version re-check,
   operation/amount limit enforcement and an independent 1C read-back/reconciliation receipt.
6. Stop immediately on scope mismatch, missing audit, duplicate/uncertain call, limit breach,
   unavailable read-back, unexpected register effect, alert failure or kill-switch activation.
   Preserve the unknown outcome and hold the target; never blind-retry a possibly applied write.
7. Record the exact evidence, outcome, deviations and observer. Do not call the canary successful
   until the independent read-back and accounting reconciliation support the expected effect.

## Rollback and stop handling

Rollback is a new, separately approved change with its own proposal, authorization and verification;
it is not database/history restoration. The plan forbids automatic rollback when dependent
documents, a closed period, externally consumed identifiers or later edits make it unsafe. In
those cases return `ROLLBACK_REFUSED`, leave the original document intact, preserve the hold and
escalate to the named operator/rollback owner. Unknown outcomes stay held until independently
resolved; a timeout is not proof of failure.

## Required run record (only after separate authorization)

```text
status: NOT_RUN
reviewed_head:
target_fingerprint:
company_scope:
operation:
permission_receipt_digest:
permission_expiry_utc:
window_utc:
limit:
proposal_id:
approval_receipt:
audit_receipt:
independent_readback:
reconciliation:
alerts_and_observer:
outcome:
rollback_or_stop_result:
deviations:
reviewer:
```

## Source contracts

- `docs/phase2/PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md`, §§4, 9, 10 and CT4/CT7/CT14.
- `docs/phase2/S14-S19_SPRINT_PLANS_AND_ACCEPTANCE_MAP_2026-10-17.md`, S19 and ordered stop
  conditions.
- `governance/GATE_MANIFEST.json` for live formal gate and production-authorization states.
- `docs/phase2/S19_RESIDUAL_RISK_REGISTER_2026-11-19.md` for current residuals and owner gaps.
