# Change record 411 — S16 apply gate, issuance integrity, and decision-page state

**Requested source baseline:** `499baa9` (provided with the fix-batch assignment; not independently resolved here)  
**Status:** source fix batch implemented; tests and runtime evidence `NOT_RUN`  
**Trace:** S16 REQ-007–REQ-013 / S2.1–S2.3; CODE1, CODE2, SEC1, UI1 findings  
**Implementation owner:** Codex  
**Required test owners:** `functional-test-reviewer` and `e2e-runner` after source freeze  
**Exact-head review owner:** GPT-PM after mapped tests and specialist review

## Finding-to-change matrix

| Finding | State | Source change | Remaining acceptance / owner |
|---|---|---|---|
| CODE1 — apply skipped S12 BEGIN_APPLY/T6 | Implemented in source; unverified | Added optional `BeginApplyEvidencePort.read(receipt, claim, now)`. Missing, raised, or malformed evidence refuses before ApplyPort. Core re-reads target, fingerprint, requester epoch/dependencies, approver liveness, and kill state; it overwrites caller, own-change, claim generation, epoch equality, approved version, and authenticated fingerprint from core-owned state. It calls S12 `apply_transition(..., Event.BEGIN_APPLY, ...)`, persists the returned S12 record under the same apply lock, and invokes ApplyPort only after T6 succeeds. | Test default fail-closed and each T6 guard refusal yields zero ApplyPort calls; test exact applied S12 state and threaded at-most-once behavior. Test agents own tests; Codex fixes findings. |
| CODE2 — proposal/rollback trusted builder output and lacked prior live auth validation | Implemented in source; unverified | `ChangeService.propose` and `rollback_propose` validate current typed requester role/person/epoch/expiry and exact registry scope before calling the builder. Service constructs an independent S12 `ProposalContext` from the current registry and server-generated change ID, time, expiry, digest, scope, version, epoch dependencies, business-state digest, currencies, and scoped refs. Both builder outputs must equal the independently parsed S12 proposal and current target record. Raw nonce is no longer sent to the builder. Rollback retains requester operation rights without requiring original-requester ownership. | Test forged builder outputs, stale/revoked requesters, scope/version/epoch changes, and rollback by an otherwise authorized requester. Test agents own tests. |
| SEC1 — store could forge internally consistent preview/envelope/approval | Implemented in source; unverified | Core regenerates canonical preview bytes from the exact stored S12 proposal and target version/class; it parses and reconstructs the S12 approval envelope, validates its raw nonce against `nonce_digest`, and recomputes the approval digest. Per-core in-memory anchors bind proposal, scope/version, preview bytes/digest, approval text/digest, nonce digest, S12 state, and accepted decision. Apply/approval/status/verify fail closed if anchors are missing or stored data differs. A core restart has no anchor and does not recover authority from the fake store. | Test coherent store forgery, envelope nonce mismatch, anchor mismatch and restart-without-anchor refusal. No durability claim. Test agents own tests. |
| UI1 — decision page lacked authoritative state metadata | Implemented in core service contract; UI integration owned separately | `DecisionPage` now carries S12 lifecycle and authorization, immutable snapshot version, proposal creation time, server registry person label, and `decision_allowed`. Page issuance requires a live non-revoked approver, label availability, a valid issuance anchor/current target, S12 `VALIDATED` + `NONE`, and no existing approval. It returns no decision-capable page for already-decided receipts. | UI agent integrates the fields and renders no form when disallowed; `e2e-runner` verifies page states. |

## Changed paths and API contracts

Core-owned source paths changed for this batch: `src/erp_mcp_s16/contracts.py`, `core.py`,
`services.py`, `fakes.py`, and `__init__.py`.

New apply evidence contract:

```python
class BeginApplyEvidencePort(Protocol):
    def read(self, receipt: DomainReceipt, claim: ClaimToken,
             now: datetime) -> BeginApplyEvidence | ErrorCode: ...

S16Core(..., begin_apply_evidence: BeginApplyEvidencePort | None = None)
FakeBeginApplyEvidencePort(evidence: BeginApplyEvidence)
```

`None` is deliberately fail-closed. The fake reader requires an explicit typed evidence value and
does not manufacture positive period, state-digest, writer-lock, ownership-row, or hold evidence.
Test owners must construct and inject an explicit fixture for journeys expected to reach T6/apply.
Core derives identity, role, target, fingerprint, version, epoch, dependencies, generation, and kill
state itself. The port supplies only the observation evidence required by the S12 T6 guards.

`ProposalPort.build` and `.rollback` now accept server-owned `expires_at` and no longer receive the
raw approval nonce. `TargetRecord` supplies the scoped parser facts used by the independent S12
proposal validation. `PrincipalRecord.display_label` supplies the human-facing label; its absence
fails closed for approval page issuance.

## Limits and evidence state

- No tests, imports, static checks, builds, runtime calls, COM calls, listener starts, migrations,
  or production wiring were run in this fix batch.
- `FakeBeginApplyEvidencePort` is a test seam only. Injecting fixture observations is not evidence
  of a real 1C period read, state digest, lock, ownership row, or successful writer operation.
- Issuance and approval anchors live only in the core instance. A new core instance cannot adopt a
  stored receipt as valid; restart/durable recovery remains unsupported in this fake-backed slice.
- Same-process locking and the fake compare-and-set do not prove cross-process or database
  atomicity.
- UI rendering and HTTP headers remain owned by the separate UI source fix and are not verified
  by this record.
- Formal S12/S13/S15 acceptance and production identity/provider qualification are not promoted.

## Ordered next actions

1. Codex completes the coordinated source batch and freezes the exact candidate revision.
2. `functional-test-reviewer` and `e2e-runner` add/run mapped CODE1/CODE2/SEC1/UI1 scenarios only
   after all sprint source is complete; record exact head, command, result, and any `NOT_RUN` cause.
3. Codex resolves valid test findings and obtains relevant independent review on the final diff.
4. GPT-PM reviews the exact tested revision before any push or pull request.
