# Change record 047 — reconcile G1 and S13 historical evidence

## What changed

- Reconciled the 2026-10-08 G1 implementation/backlog notes against migrations 001–018, the evidence matrix, current gate contract, and 2026-10-15 checkpoint.
- Updated S13 review notes for later implementation of approval digest 009, event hash 011, and verification tick spacing 012; retained partial real 1C ownership, MFA, key custody, and checkpoint limits.
- Added exact G1 exit gaps and the independent static review results to the risk/gate packet.
- Linked the reconciliation from the current plan and decision log; regenerated the document registry.

## Why

Independent database and security reviewers at HEAD `8935deda93a41075681e8df8abc4cadd3b9cce8d` found stale 2026-10-08/14 blocker text that understated later synthetic implementation. The same reviews confirmed that formal G1/S13 acceptance still lacks specific runtime and external evidence. This record updates historical status without changing gate state.

## Contracts and paths

- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `docs/phase2/G1_IMPLEMENTATION_NOTE_2026-10-08.md`
- `docs/phase2/S13_REVIEW_FINDINGS_2026-10-12.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/phase2/SIMULATION_PROGRAM_PLAN_2026-10-15.md`
- `core/DECISION_LOG.md`
- `governance/DOCUMENT_REGISTRY.md`
- This record

No source, schema, test, key, gate status, or runtime authorization changed.

## Independent review evidence

At HEAD `8935deda`, the database reviewer and security reviewer used GPT-6 Luna at medium effort. Both were read-only and ran no tests, checks, or migrations. The database review identified stale historical statuses and confirmed missing G1 acceptance (kill timed inside COMMIT, restore into another cluster, and gate-specific capacity/evidence review). The security review found R-01 and R-03 to be production-blocking MAJOR design gaps while the write port remains non-operational; it found no cross-tenant bypass in migrations 016–018 under the documented ledger-owner/superuser trust boundary.

## Verification state

- `git diff --check` is required for this documentation-only delta before commit.
- No tests or migrations run.
- G1 remains NOT_PASSED; formal S13 remains NOT APPROVED; Release 2 remains NO-GO.
- Requires exact-range GPT-PM review before push.
