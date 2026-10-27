# Change record 171 — shared S12/S13 Python UUID contract

## What changed

- Added `src/business_ai_gateway/phase2/change_ledger/uuid_contract.py` with separate predicates for canonical nonzero UUID text and process-instance UUID text (RFC variant, versions 1–8).
- Routed the S12 invocation context and exact ticket/permit comparison, S13 private-writer service, PostgreSQL store, evidence-attempt source, evidence registrar, and trusted-process snapshot validation through those shared predicates while retaining each existing error code.
- Added `S13_PYTHON_UUID_CONTRACT_2026-10-25.md` and indexed it in `docs/DOCUMENT_INDEX.md`.
- Validated trust-snapshot process-ID element types before duplicate detection so an unhashable malformed value returns the stable request error instead of leaking `TypeError`; added `S13-TRUST-REQUEST-SHAPE-01` for post-coding qualification.

## Why

The Python boundaries had repeated implementations of the same nil/canonical/process-instance rules. A single domain-level predicate makes their accepted spelling and version contract explicit and reduces drift. Database-side validation remains independent and unchanged.

## Affected contracts and paths

`write_port.py`, `service.py`, `postgres_store.py`, `postgres_attempt_source.py`, `postgres_evidence_registrar.py`, and `evidence_trust.py` continue to refuse malformed identifiers before their existing SQL, trust, or writer boundary. Invocation-context ticket/permit comparison rejects UUID-equivalent but noncanonical text instead of normalizing it into a match. Generic ledger IDs remain version-agnostic; process-instance IDs require a canonical nonzero RFC UUID with a supported version.

## Decisions and limits

This is source-only behavior consolidation. It does not change PostgreSQL SQL, migration state, effective grants, host identity, or COM behavior. The candidate schema remains uninstalled/ungranted, and the physical writer remains non-operational. The version/variant rule must still be compared to SQL by the database reviewer and qualified in the disposable environment.

## Verification state

Actual read-only `code-reviewer` agent passes (GPT-6 Luna, low effort) found no BLOCKER or MAJOR issue in UUID predicate parity, import direction, exact ticket/permit comparison, caller error mapping, or validation order. The focused follow-up confirmed alternate UUID spellings return `INVOCATION_CONTEXT_MISMATCH`, which the service retains as its sanitized `WRITER_CONTEXT_INVALID` refusal before writer selection and COM entry. It also confirmed malformed unhashable trust-request elements now return the stable request error before any pool or row access, without changing duplicate or valid-control behavior. Manual source inspection only; no tests, checks, builds, SQL parsing, database operation, migration, COM operation, service restart, staging, commit, or push was performed for this change record. Functional and E2E cases remain `NOT_RUN` until coding closes.
