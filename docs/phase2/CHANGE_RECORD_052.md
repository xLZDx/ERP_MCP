# Change record 052 — specify remaining G1 runtime evidence

## What changed

- Added explicit, falsifiable acceptance boundaries for killing a PostgreSQL backend while explicit SQL `COMMIT` is executing and restoring into a separate PostgreSQL cluster.
- Recorded why the current API-phase termination and same-cluster restore scenarios do not satisfy those G1 criteria.
- Linked the requirements from the G1–G8 closure packet and regenerated the document registry.

## Why

A read-only functional-test review at HEAD `8e923ce` found that the G1 backlog named the missing cases but did not distinguish the required database boundaries from the current harness behavior. The detail gives the permitted test agents a precise future acceptance target without treating planned evidence as executed or passing.

## Contracts and paths

- `docs/phase2/G1_OPERATOR_BACKLOG.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `governance/DOCUMENT_REGISTRY.md`
- `core/DECISION_LOG.md`
- This record

No test code, executable source, SQL, database, container, gate state, or runtime authorization changed.

## Verification state

- Test-boundary statements reconciled with the read-only functional-test review at HEAD `8e923ce`.
- No tests, migrations, or runtime actions run. `git diff --check` is to be performed before commit.
- G1 remains NOT_PASSED; capacity and effective-role/approver evidence remain outstanding.
- Exact-range PM review is required before push.
