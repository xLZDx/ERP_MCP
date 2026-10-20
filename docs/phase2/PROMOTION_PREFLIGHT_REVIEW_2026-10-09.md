# Phase 2 promotion preflight — independent review (2026-10-09)

**Severity:** MAJOR (preflight boundary violation), **product release:** NO-GO unchanged.
**Scope:** read-only inspection of `D:\Repo\ERP_MCP-phase2\src\business_ai_gateway\phase2\promotion.py`, currently untracked in the concurrently active Phase 2 worktree (base tracked HEAD `9cb6634`). The script reviewed is not a committed/release HEAD. **No active working file was edited.**

## Reproduced case

A stale/misrouted `AttestationReader.find_attestation(scope, candidate_rev2, evidence_ref_rev1)` can return a valid `AttestationView` for *revision 1*. The service checks `decision`, revocation, expiry, recomputed evidence digest, observer trust, approver independence, and head CAS, **but does not compare** `att.revision_id` against `candidate` or `att.evidence_ref` against the requested reference. It invokes `port.promote_head`, contrary to the stated preflight invariant that an invalid attestation never reaches the write port.

**Probe:** `var/promotion_reader_probe.py` in this isolated safety worktree dynamically loaded the uncommitted active `tests/phase2/test_promotion.py` fake (no network/DB writes), created two distinct observed revisions, supplied an approved attestation from rev1 as a stale answer for rev2 and attempted rev2 promotion with rev1 evidence.

Observed output:

```text
outcome= REJECTED_EVIDENCE
code= EVIDENCE_NOT_FOUND
write_port_attempts= 1
new_version= None
```

The **port itself rejected** the mismatched attestation, so this probe demonstrates a missing *service-layer* guard, not an unauthorized production write. SQL must still independently enforce the invariant. The existing test for another revision uses a normal reader that returns `None`, so it does not exercise the stale/misrouted-result path.

## Required minimal fix in the active promotion lane

In `PromotionService._run`, immediately after `find_attestation` returns, reject if `att.revision_id != candidate` or `att.evidence_ref != evidence.evidence_ref` (and reject malformed/invalid view types), before any trust check, head lookup or `port.promote_head`. Return an explicit sanitized `REJECTED_EVIDENCE` result. No success status or acceptance side effect. Keep SQL authoritative against revocation/CAS races.

Regression RED/GREEN must assert `SpyPort.promote_calls == 0` for stale attestation of another revision and for stale matching revision but mismatched reference. Add a control showing a valid reference still reaches the port exactly once. Review in the owning Phase 2 lane after the untracked work becomes a stable commit; do not silently merge worktrees.

## Other review note

`rollback` performs `get_head` before validating requester independence and all input shapes; check whether its documented guard ordering promises no read/side-effect before authorization. This is a hypothesis for a dedicated negative test, **not** a demonstrated production leak.

**Status:** OPEN in active Phase 2 lane; no false green, no bypass, no production permission granted.

## Untracked source snapshot provenance

- `promotion.py` SHA-256: `58a114bc255e402a3c5100d03af6499a1b603d4d44d0d6141286b31158134948`.
- `test_promotion.py` SHA-256: `26bd4ee47f116811f3ad03fcdc3e6993a89eed1f86b74f6d81d2880a00230b3a`.
- These are hashes of *untracked working files* on the Razer at review time; they are not Git HEAD evidence. Recheck before applying the finding if parallel engineering modifies them.
