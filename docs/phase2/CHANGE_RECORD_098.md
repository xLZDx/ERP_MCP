# Change record 098 — clarify R-01/R-03 source findings and current gate state

## What changed

- Revalidated and clarified the R-01 source inventory: migration 016's receipt requirement is opt-in; migrations 017/018 carry or wire-bind a marker but do not make it mandatory; the located coordinator and writer are synthetic, and `OneCWritePort` is only a protocol.
- Expanded R-03 acceptance to cover legacy-algorithm denial for evidence, checkpoint, permit, and dispatch-receipt actions; non-secret deployed-key/use inventory; custody provenance; historical-record classification; and the schema's missing signing-time algorithm/fingerprint bindings.
- Reconciled current formal gate and push status in the risk packet, simulation plan, and SDLC state while preserving dated historical snapshots.
- Added a current R-01/R-03 disposition section to the operator backlog, preserving lane labels as roles rather than named people.
- Regenerated the document registry to include this change record and the updated document titles.

## Why

The prior source inventory was accurate at its recorded revision but did not explicitly state that it had been revalidated at the current code HEAD. Its R-03 summary did not enumerate all four shared-verifier action paths or fully define the independent inventory and custody evidence needed for acceptance. Some active text also described the earlier push decision or gate snapshot as pending/current. This update distinguishes source-confirmed behavior, unknown deployed state, historical snapshots, and current acceptance requirements.

## Contracts and paths

- `db/phase2/015_ed25519_signatures.sql`
- `db/phase2/016_dispatch_receipt.sql`
- `db/phase2/017_receipt_hardening.sql`
- `db/phase2/018_wire_payload_receipt.sql`
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `src/business_ai_gateway/phase2/change_ledger/write_port.py`
- `src/business_ai_gateway/phase2/simulation/synthetic_dispatch.py`
- `src/business_ai_gateway/phase2/simulation/reference_writer.py`
- `governance/GATE_MANIFEST.json`
- `governance/DOCUMENT_REGISTRY.md`
- `docs/phase2/S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/phase2/SIMULATION_PROGRAM_PLAN_2026-10-15.md`
- `docs/sdlc/STATE.md`
- `docs/phase2/CHANGE_RECORD_098.md`

## Decisions and limits

- R-01 and R-03 remain OPEN. No production writer, deployed key, secret, signature, or live database state was inspected; no exploit or deployed vulnerable key is claimed.
- The proposed R-03 disposition blocks `KEYED_HASH_STANDIN` for all four new-action paths while allowing only read-only historical verification if required. Cutover and rollback remain separate planned work; the current code does not implement that disposition.
- R-01/R-03 owners remain project-design and key-governance lanes. No human owner is recorded or inferred.
- Current manifest status remains G0 PASSED for the narrow prototype scope; G1–G8 NOT_PASSED; S13 not started/not approved for formal entry; production authorization NONE; Release 2 NO-GO.
- The local push through `ecd1779673f00209ac540729f420c2b4d5dddbbe` is complete. This documentation update creates a later local HEAD; any subsequent push requires fresh exact-head PM approval.
- The document registry is generated from tracked Markdown. Refreshing it is included in this documentation commit; it does not require a separate change record or commit.
- Preserved unrelated untracked `.claude/`.

## Review and verification state

- Source behavior was checked read-only against migrations 015–018 and the named Python interfaces/coordinator at code HEAD `ecd1779673f00209ac540729f420c2b4d5dddbbe`. The inspected migration/coordinator/writer blobs are unchanged from inventory HEAD `450f977`.
- The R-01 and R-03 findings derive from the completed read-only code-explorer, security-reviewer, and database-reviewer evidence supplied for this update; they are not runtime or deployed-state findings.
- No tests, builds, lint, CI, migrations, database operations, key access, real-system access, or production actions were performed.
- Ran `node scripts/build_document_registry.mjs` to refresh the generated document inventory.
- No commit or push was performed as part of this record.

## Acceptance

- R-01 accurately distinguishes opt-in prototype behavior from production-boundary requirements.
- R-03 enumerates all four new-action signature paths and defines non-secret deployed inventory, historical/new-use classification, custody proof, and signing-time provenance limitations.
- Current gate state and completed local push are distinguished from historical snapshots; formal G1 and other open gates are not represented as passed.
- Documentation changes and the generated registry are ready for one local documentation commit; any later push remains subject to exact-head PM approval.
