# Change record 058 — record R-01 and R-03 source inventories

## What changed

- Added a source-only inventory of the synthetic dispatch receipt path and its opt-in completion guard to the S14 risk packet.
- Added a source-only inventory of legacy verifier registration and verification paths, including the superuser exception and receipt use.
- Updated the operator backlog with exact source findings and the concrete next evidence required for each risk.
- Recorded the findings and scope limits in the decision log and regenerated the document registry.

## Why

The prior R-01 and R-03 entries stated proposed dispositions and acceptance requirements but did not distinguish inspected source paths from unknown deployed state. The inventory makes that boundary explicit so the proposals are grounded in code without implying production qualification.

## Contracts and paths

- `db/phase2/015_ed25519_signatures.sql`
- `db/phase2/016_dispatch_receipt.sql`
- `db/phase2/017_receipt_hardening.sql`
- `db/phase2/018_wire_payload_receipt.sql`
- `src/business_ai_gateway/phase2/simulation/synthetic_dispatch.py`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/phase2/CHANGE_RECORD_058.md`
- `core/DECISION_LOG.md`
- `governance/DOCUMENT_REGISTRY.md`

## Decisions and limits

- R-01 remains OPEN. The identified receipt coordinator is explicitly synthetic and the SQL receipt marker is opt-in. No production writer entry point is present in this repository, so source review cannot inventory deployments or prove universal production enforcement.
- R-03 remains OPEN. SQL 015 defaults ordinary new registrations to Ed25519 and retains legacy verification; live key rows and signature uses are database evidence and were not queried. No key was registered, revoked, altered, or exposed.
- G0–G8, S13, production authorization, and Release 2 states are unchanged.

## Verification state

- Read-only source inspection only; no tests, checks, migrations, database access, key access, real-system access, or production actions were performed.
- The document registry generator is run after adding this record.
