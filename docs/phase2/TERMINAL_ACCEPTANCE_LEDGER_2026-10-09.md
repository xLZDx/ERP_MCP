# ERP_MCP Phase 2 — terminal acceptance ledger, 2026-10-09

**Overall: NOT TERMINAL / Release 2 NO-GO.** This ledger describes verified evidence and remaining requirements, not a waiver or signing authority. Local code branch: `hardening/phase2-client-safety-combined-20261009`. Product deliverable remains a staged Phase 2 Living Model, **not** a proven autonomous ERP workflow engine.

## Gate decision matrix

| Gate | Current disposition | Grounded evidence | Remaining condition for PASS |
| --- | --- | --- | --- |
| G0 — scope, owner, licensing | BLOCKED | R1/R2 isolation documented; donor/license inventory prepared in `G0_DONOR_PROVENANCE_REVIEW_2026-10-09.md` | Exact-scope owner/architecture/security signoff, donor license review, source registry authority OB-01/04/15 |
| G1 — living PostgreSQL registry | IN PROGRESS, not signed | On code HEAD `edc8d9d`, 280 selected SQL/port integration tests PASS on disposable PostgreSQL 16. Historical G1 65 restore/crash/guard tests passed on `df92cc8`. | Independent DB/security exit decision; final candidate crash/restore/guard/capacity evidence, exact release HEAD |
| G2 — real 1C discovery/metadata | NOT PASSED | Existing R1 read-only source returned health 200 and supported 1C 8.3 OData metadata; offline Phase 2 discovery, scheduler, drift classifiers tested | Phase 2-owned authenticated source-wide capture, source permit, durable job/cursor wiring, exact native source provenance and reviewer decision |
| G3 — accountant-native reconciliation | BLOCKED | Offline comparators, 521.1 contract and fake/SQL preconditions; no native signer evidence from this candidate | Authentic native 1C report bytes, independent accountant attestation and exact six-column/row matched cases |
| G4 — Drive least privilege | BLOCKED | Local change-feed contracts only; not a proved ERP_MCP-owned Drive OAuth session | Narrow ERP_MCP OAuth client, consent, new-file/revoke/move tests, data-owner confirmation |
| G5 — UI/admin UAT | NOT PASSED | Partial contract/code components only | Real audited workbench, operator/admin scenarios and witnessed UAT |
| G6 — operations/canary | BLOCKED | Offline rollback contracts and historic disposable DB crash evidence | Capacity 30/50/100/150, chaos and restore at target, secret rotation owner, production canary permit and rollback |
| G7 — release | BLOCKED | Local code and suite evidence, separate review documents | All prior gates PASS, exact HEAD + configuration/evidence manifest, independent review and release-owner authorization |

## Engineering done on local branches

- `edc8d9d`: DR-01 accepted/observed hash separation with RED/GREEN tests; 780 PASS / 180 SKIP offline and Ruff PASS.
- `aed0948` (applied as combined commit `07dddbc`): SCH-02 sanitized adapter exception/lease-loss errors before returning/persisting. Integrated offline Phase 2 tests: **782 PASS / 180 SKIP**, Ruff/compile PASS; no customer deployment evidence.
- Other committed combined fixes: P-M1 promotion preflight identity/approval guards, backend integer bounds, observed-only metadata labels, scheduler config numeric bounds and evidence docs.
- R1 compatibility suite on code HEAD `edc8d9d`: **1925 PASS / 343 SKIP / 1 DESELECTED**, exit 0 in 400.42 seconds. The deselected stale engineering checkpoint requires governed rebaseline; it has not passed. The later SCH-02 Phase 2-only change is not covered by an exact-head R1 suite.

## Operator-only backlog

OB-01 exact R2 scope and R1 freeze rebaseline, OB-04 authoritative R1 source registry integration model, OB-10 bounded Phase 2 source capture permit, OB-11 independent accountant native report, OB-12 ERP-owned Drive OAuth, OB-13 production secret provider/rotation, OB-14 approved canary window and rollback owner, OB-15 source/license approval, OB-21 release-owner signature. Historical OB-02 (project-to-chat binding), OB-03 (disposable PostgreSQL), and OB-05 (isolated R2 work) were previously addressed in `DECISION_LOG.md`; do not recite them as fresh blocking access requests.

## Release policy

Never advertise automatic bookkeeping writes or universal reconciled reports while G0–G7 remain open. No hardcoded PASS, no fake attestations, no production activation or 1C mutations. Continue independent engineering until the remaining gates require privileged third-party evidence, then keep NO-GO and expose the minimal operator action.
