# S13 terminal recovery before dispatch readiness

## Change

Removed the `readiness_ref IS NOT NULL` requirement from
`private_writer_record_verified_success_v1` in candidate migration 027. A replacement service starts
with a complete but unresolved recovery inventory and intentionally has no readiness reference. The
routine can now terminalize only an already-entered, exact attempt under the current serving
instance/epoch while readiness is false, allowing that inventory to drain.

The separate readiness checks remain on new admission, invocation marking and the final COM-entry
authorization. The no-entry and entered-conflict terminal routines likewise do not require readiness
to reconcile existing inventoried calls. The Python coordinator continues to require the exact
identity/CAS pair in its validated startup inventory for recovery operations. SQL still independently
checks the active serving row, attempt/CAS, evidence and slot under transaction locks; it does not
claim to verify in-memory inventory provenance.

## Why

The previous success-terminal condition created a restart deadlock: startup set `readiness_ref=NULL`
whenever pending calls existed, while terminal success refused unless that reference was non-NULL.
The pending call therefore could not be reconciled and the service could not become ready. Dispatch
readiness is an admission gate; it is not a prerequisite for evidence-terminalizing a pre-existing
physical call.

## Affected contracts and paths

- `db/phase2/027_private_writer_admission_schema.sql`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, `S13-EPOCH-TERM-01`
- `docs/phase2/OPERATOR_BACKLOG.md`
- `core/LESSONS_LOG.md`

## Decisions and limits

- The recovery exception applies only to terminal reconciliation of an already-entered,
  immutable attempt with exact evidence and current active service epoch.
- New admission and COM entry remain gated by non-NULL readiness.
- The service-level startup-inventory membership check remains required for recovery; SQL does not
  assert that it independently authenticated in-memory inventory.
- This change does not resolve the separate OutcomeEvidence version-floor/validator provenance,
  legacy S12 cutover ACL, full lock graph, COM mapping or physical writer composition gaps.

## Verification

Source-only change; exact SQL routine text was inspected. No SQL parser, test, check, build, CI,
migration, database operation, COM call, staging, commit or push was run. The updated SQL source has
not yet received independent database-reviewer or GPT-PM re-review. `S13-EPOCH-TERM-01` remains
`NOT_RUN` and requires proof that readiness stays false during recovery, exact inventory evidence
can drain, admission/COM entry still refuse, stale owners cannot terminalize, and holds/slots remain
unchanged on refusal. Accountable task owner: operator; executor: Codex; technical host owner:
Ivan stack for the licensed writer boundary.

Current candidate migration SHA-256 after this change:
`1FA48170BDFEDE8F39BCB02B35B27ED3F650D9387E6533568B8BA43BCFF4E8E8`. The focused reviewer
inspected the code paths at `027:2856-2867,2945-2949,3034-3053` and the corresponding guards at
`027:1850-1852,2025-2026,2155-2157`; it also checked service startup inventory and dispatch paths
at `service.py:705-727,752-774,915-923`. The review found no issue for the requested boundary.

Current direct gateway evidence, 2026-10-24 19:56 UTC: the project's in-process auditor token
flow and authenticated local MCP session called `source_health` for `onec-818ha-reference`; the
sanitized result was `ok=True` with no tool error. The token was not printed. This is access/health
evidence only and does not qualify business data or writer/COM authority. Full evidence is in
`docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`.

An actual `database-reviewer` completed a focused read-only source review of this terminalization
exception. It found no issue: success terminalization remains gated by current active instance and
epoch, an already-entered attempt, exact valid evidence and the CAS-owned slot; admission,
invocation marking and COM entry retain readiness checks; service recovery requires exact startup
inventory. The review's model/effort were not exposed (`UNKNOWN`), and it performed no SQL parse,
tests, database operation or migration. This is static evidence, not runtime qualification.
