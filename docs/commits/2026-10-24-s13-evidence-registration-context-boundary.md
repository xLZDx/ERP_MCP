# Change record: Define the S13 evidence-registration trust boundary

## What changed

- Added `docs/phase2/S13_EVIDENCE_REGISTRATION_CONTEXT_DESIGN_2026-10-24.md` describing why the current production verifier result cannot yet authorize database evidence registration.
- Linked the design from `docs/DOCUMENT_INDEX.md` and recorded its concrete dependencies in `docs/phase2/OPERATOR_BACKLOG.md`.
- Recorded the delegated technical decision in `core/DECISION_LOG.md` and the reusable trust-boundary lesson in `core/LESSONS_LOG.md`.

## Why

The current verifier accepts `trusted_now` from its caller and returns a constructible dataclass. The registration composite requires immutable database attempt/intent fields missing from `DispatchAttempt`, plus a validator build identity whose provenance is not established. Wiring these values directly would let a caller claim validation/build facts the system cannot prove.

## Affected contracts and paths

- `src/erp_mcp_private_writer/production_evidence_verifier.py`
- `src/business_ai_gateway/phase2/change/evidence.py`
- `db/phase2/027_private_writer_admission_schema.sql`
- `docs/phase2/S13_EVIDENCE_REGISTRATION_CONTEXT_DESIGN_2026-10-24.md`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `docs/DOCUMENT_INDEX.md`
- `core/DECISION_LOG.md`
- `core/LESSONS_LOG.md`

## Decisions

Keep registration uncomposed. Before adding a registrar, define authenticated trusted time, exact immutable dispatch-attempt/intent lookup, complete per-envelope typed projection, approved validator-build provenance, and the least-privilege evidence-ingest principal. Preserve database-side binding and revocation rechecks. Accountable task owner: operator; executor: Codex. Canonical records do not identify a human/service owner for validator-build provenance, trusted-time authority, or oracle-policy administration.

## Verification state

Documentation/source inspection only. No tests, checks, build, SQL parser, migration, database write, COM call, evidence registration, staging, commit, or push was performed. The document registry was not regenerated because it is generated across Git refs and already contains unrelated working-tree changes; regenerate after the authorized documentation batch is ready for review.
