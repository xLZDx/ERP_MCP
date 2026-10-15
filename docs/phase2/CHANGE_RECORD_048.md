# Change record 048 — reconcile current G0 decisions

## What changed

- Added a dated reconciliation to the S11 exit package so the 2026-10-14 OB-01 and OB-15 decisions supersede the older dependency snapshot.
- Updated the G0 row in the current risk and gate packet to require an exact-head evidence index and gate review while preserving the named OB-15 deployment deferrals.
- Regenerated the document registry.

## Why

The S11 exit package still listed OB-01 and OB-15 as open even though the operator backlog records the decisions. That stale snapshot obscured G0's actual remaining acceptance: assemble and review the exact evidence package, without treating deferred deployment evidence as complete.

## Contracts and paths

- `docs/phase2/S11_EXIT_PACKAGE_2026-10-12.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `governance/DOCUMENT_REGISTRY.md`
- `core/DECISION_LOG.md`
- This record

No source, SQL, tests, key, gate state, or runtime authorization changed.

## Verification state

- Reconciled against the 2026-10-14 decisions in `docs/phase2/OPERATOR_BACKLOG.md` and the G0 closure contract in plan section 9.
- No tests or migrations run. `git diff --check` completed without findings.
- G0 remains NOT_PASSED pending exact evidence review; production authorization remains NONE.
- Requires exact-range GPT-PM documentation review before push.
