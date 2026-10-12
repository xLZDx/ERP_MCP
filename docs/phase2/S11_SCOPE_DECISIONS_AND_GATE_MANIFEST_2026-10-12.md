# S11 scope record, decisions, glossary, read-back inventory and gate manifest (2026-10-12)

Status: DRAFT for GPT-PM review. Baseline: plan revision 5. Companion records: `S11_DECISION_RECORDS_AND_THREAT_MODEL_2026-10-12.md`, `CT14_FEASIBILITY_SPIKE_2026-10-12.md`, `S11_SOURCE_EVIDENCE_INVENTORY_2026-10-12.md`. Machine-readable manifest: `governance/GATE_MANIFEST.json`. This record closes no gate and approves no code. No test, CI or mutation run.

## 1. Scope decision record and replacement of R2-REQ-15

- Decision (operator, 2026-10-11): "read-only was Phase 1"; version 2 must change 1C data from a ChatGPT or Claude prompt and reconcile the result.
- Superseded text: `R2-REQ-15` in `TDD_PHASE2_RU.md` line 55: "separate dev/prod permissions, default OFF prod, no business writes". The old requirement stays valid for the legacy Phase 2 read path and its gates G0-G7; it is not edited.
- Replacement for v2 (`R2-REQ-15v2`): separate target classes by authenticated base fingerprint (disposable clone under the test-lane policy; staging always DENY; production default DENY and only under a signed single-purpose operator permission); business writes exist only through the governed write path (separate authorization, approval by a person other than the requester, durable audit before the effect, read-back verification); the legacy read path keeps denying every non-READ class; deletion, marking for deletion and real-money actions remain operator-only and outside the v2.0 catalogue.
- OB-01 (scope rebaseline or explicit permission for an isolated prototype): the operator's 2026-10-11 decision and the GO of 2026-10-12 cover the prototype on the disposable clone only; whether they count as the OB-01 record is for the operator and GPT-PM at G0. OB-15 (donor and license inventory): not started; see section 6.

## 2. Glossary

| User-level term | Concrete 1C object |
| --- | --- |
| purchase invoice, receipt | document `ПоступлениеТоваровУслуг` (purchase receipt of goods and services) |
| contract | catalogue `ДоговорыКонтрагентов` |
| post / unpost | write mode `Проведение` / `ОтменаПроведения` on the document |
| draft | a saved, not posted document (`Проведен` = false) |
| change | one immutable proposal: one operation, one target, one approval |
| marker | a record, written in the same 1C write, that ties a 1C object to a change id and digest |
| target version | the object data version token (`ВерсияДанных`) read before the write |
| registrar movements | rows in registers whose recorder is the document |

## 3. Decisions (proposed here; the owner of each is named)

| # | Decision | Owner | State |
| --- | --- | --- | --- |
| D4 | Write topology: COM connector on a licensed host with a private access path; the service is the only holder of the write identity; OData stays read-only; no public tunnel for writes. | GPT-PM review, operator veto | PROPOSED |
| D5 | Dedicated marker mechanism and a least-privilege write role require a 1C configuration extension. Plan section 14 excludes configuration changes except an HTTP-service extension approved by a separate decision, so this extension needs its own decision before S12 and a separately authorized spike on the clone. | GPT-PM review, operator | DECIDED by the operator on 2026-10-12 (chat answer to a direct question): the configuration extension is permitted ONLY on the disposable clone `818HA_p2diff` for measurement; production and staging are not covered and need a separate decision with a signed permission. The measurement result decides whether the create/post/unpost slice qualifies. |
| D6 | Numbering: the system never sets a document number; 1C auto-numbering is used. A supplier number and date are stored as business-key fields; because numbers repeat across years, every lookup filters by date. | GPT-PM | PROPOSED |
| D7 | Time and money semantics: ledger timestamps are UTC; 1C dates convert explicitly with the base time zone; `as_of`, start and end carry a timezone offset; grant windows are half-open [start, end); amounts are gross, in document currency, no conversion (CT13). | GPT-PM | PROPOSED |
| D8 | Approval TTL versus queue wait: an approval expires 24 h after issue; the maximum queue wait is bounded by the TTL; an approval that expires before the effect boundary is refused and a new approval is needed; the effect boundary check is the authority. | GPT-PM | PROPOSED |
| D9 | External audit-checkpoint store and signer (CT5): a separate host or account, write-only service rights, signing key held outside the DB administrator's trust boundary. | operator | DECIDED by the operator on 2026-10-12: a separate machine or account, write-only for the service, the signing key held by a separate signer outside the database administrator's trust boundary; the concrete host and account are still to be named by the operator before S13. |
| D10 | Approver identities and person ids; auto-approval policy only on the test lane. | operator | DECIDED by the operator on 2026-10-12: the operator is the approver, plus an auto-approval policy only on the test lane (clone), visible in the audit; the operator's person id is still to be supplied before S12 and no other approver exists. |
| D11 | Rollback by marking for deletion stays forbidden (operator-only class); only unposting and correction exist in v2.0. | operator | OPEN, treated as forbidden |
| D12 | Contract update is outside the first S12 freeze until a durable provenance mechanism and a least-privilege role are measured (see the CT14 record, section 5). | GPT-PM | PROPOSED |

## 4. Canonical business keys

- Purchase receipt: base fingerprint, organization, counterparty, contract, supplier document number, supplier document date, kind, currency (a date filter is mandatory).
- Contract: base fingerprint, organization, counterparty, contract number, contract date.
- A create attempts a lock keyed by the hash of this tuple; inside the serialized writer the absence of a document with that key (and of the marker) is re-checked immediately before the atomic write (CT2).

## 5. H3 evaluation parameters, fixed before any measurement

- N = 30 real or realistic invoices on the test lane (xlsx or csv first; PDF and image as a separate stratum). X = at most 10 % of material fields corrected by a human across the set, with no confidently wrong material field passing unreviewed. A "corrected field" = any change a human makes to an extracted amount, VAT, counterparty, contract, date or currency before approval; a reformatting of the same value is not a correction. Material fields are always human-reviewed regardless of confidence. The evaluation set is frozen by file hash before extraction runs. If PDF misses X the supported path stays xlsx/csv and manual entry (plan H3 fallback).

## 6. Read-back inventory (H4) and open S11 inputs

| Needed for verification | Measured on the clone (COM) | Gap |
| --- | --- | --- |
| Document fields and posted flag | read by reference: yes | none for COM |
| Lines of tabular parts | yes (earlier edit tooling reads Товары, Услуги, Оборудование, ОбъектыСтроительства) | none for COM |
| Movements by registrar | yes: accounting register and accumulation register by recorder query | the movement collection on a loaded object is lazy; use registrar queries; other document types unmeasured |
| Object version token | yes | token is opaque; compare for equality only |
| Same reads through the v1 gateway (OData/MCP) | not measured in this pass | S15 decides whether a v1 read extension is needed; an incomplete read-back blocks the affected operation type |

Not yet produced and still S11 deliverables: the OB-15 donor and license inventory, the "invariant -> scenario -> failing assertion at the enforcement boundary" matrix, the TDD/sprint/stories/DoD set and requirement-derived test coverage (authored by `functional-test-reviewer` and `e2e-runner` under the development rules), and the per-operation expected-movements rule table beyond the purchase receipt.

## 7. Gate manifest and status ledger

`governance/GATE_MANIFEST.json` carries the gate DAG of plan section 9 and the four-field status ledger (`engineering_status`, `gate_status`, `external_evidence_status`, `production_authorization`) for G0-G8. Every gate is NOT_PASSED. `scripts/validate_gate_manifest.mjs` is the closure validator (acyclic DAG, known predecessors, four fields present, no PASSED gate without an evidence reference, G4 passes only as PASSED or an approved waiver, G8 implies no other gate). The validator was written in S11 and has NOT been run: running it belongs to the S19 closure evidence.
