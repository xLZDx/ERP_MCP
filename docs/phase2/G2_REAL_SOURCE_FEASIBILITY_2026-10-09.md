# ERP_MCP Phase 2 — G2 real 1C feasibility snapshot

Date: 2026-10-09. **Source feasibility only, G2 NOT PASSED.** This probe used the already connected **read-only Release 1 ERP_MCP** gateway, not the Phase 2 capture worker; no accounting facts were exported, no raw credentials read and no write permissions granted.

## Grounded read-only facts

- Authenticated plugin principal was permitted to inspect three registered sources. One existing real reference lane `onec-818ha-reference` was checked by name.
- `source_health`: HTTP 200 / OK. `onec_capabilities(refresh=false)`: platform 1C 8.3.27.2342, OData JSON and Atom supported, 920 published EntitySets, transport profile `ODATA_JSON_V3`, `compatibility_status=SUPPORTED`.
- Capability evidence was returned by the R1 service for its own registered source; that evidence is **NOT a Phase 2 full-source OBSERVED event or an approved living model**.
- Source access exists for **read-only metadata feasibility** in the current connector. G2 still requires a Phase 2-owned authenticated bounded source-wide capture, exact-fingerprint provenance, durable append and cursor/failure-vs-drift processing, company/source ACL semantics, and independent Gate G2 review.

## Client-facing decision

Do not state that Phase 2 is actively monitoring the production reference source, automatically fixes schema changes, or has completed native 1C accounting reconciliation. Read-only R1 connectivity proof does not waive G0/G1, G2, G3 accountant attestation or any product release authority.

**Operator-only missing:** explicit source-specific Phase 2 capture permit and secrets/security owner for any real ingestion. No credentials should be copied from R1 to R2, and this note does not grant consent.
