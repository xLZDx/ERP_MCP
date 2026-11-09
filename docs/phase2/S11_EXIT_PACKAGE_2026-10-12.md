# S11 exit package (2026-10-12)

Status: DRAFT submitted for the GPT-PM S11 exit decision. Evidence head: `8dc9bbba4ccc482113cfeee737497e42f43ea2bc` (local `main`, nothing pushed); this file is committed after that head and is not part of the listed evidence. Plan baseline: revision 5. This package approves nothing by itself: S11 exit, the S12 interface freeze, G0-G8, any push and any production action stay with their own decisions.

## 1. Deliverables against the plan's S11 list

| Deliverable (plan section 8) | Evidence file | Blob id at the evidence head | State |
| --- | --- | --- | --- |
| Scope decision record and R2-REQ-15 replacement, glossary, decisions D4-D12, H3 N and X, read-back inventory | `docs/phase2/S11_SCOPE_DECISIONS_AND_GATE_MANIFEST_2026-10-12.md` | d1c53ac5a057 | complete as a record; D4, D6-D8, D12 are PROPOSED for GPT-PM acceptance; D5, D9, D10 are decided by the operator (clone-only extension, separate checkpoint machine, operator approver) with the concrete host and person id still to be supplied |
| Threat model, S11-A..D settlement, CT1-CT15 mapped to code anchors and measured facts | `docs/phase2/S11_DECISION_RECORDS_AND_THREAT_MODEL_2026-10-12.md` | eff8ee75c07c | complete (20 threat rows, revision 3) |
| CT14 feasibility matrix, operation-by-channel scope decision | `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` | b0f64c9bd2a2 | accepted by GPT-PM as a qualified feasibility slice (COM, file base, purchase receipt create/post/unpost, clone only); unmeasured cells have conservative restrictions |
| Extension, custom role, rights evidence | `testlane/onec_extension/` (STATUS.md blob 868ab0f5ba66; Rights.xml sha256 `e9296a472dc320c18fccf3a2831d2f549737cb124438bc2c32116ee8b1b8f785`) | see left | complete for the clone; GPT-PM verified the file hash and the allowlist equality |
| Source-evidence inventory | `docs/phase2/S11_SOURCE_EVIDENCE_INVENTORY_2026-10-12.md` | e8ff8ec069ae | complete for its declared purpose: sections 1-9 with explicit exclusions and reasons (section 8); agent-reported entries are labelled as such |
| OB-15 donor and license inventory | inventory section 9 | e8ff8ec069ae | DRAFT delivered; the operator's approval is open |
| Operation catalogue v0, canonical business keys, per-operation rule table | scope record section 4, `docs/phase2/S11_OPERATION_RULES_AND_STORY_REGISTER_2026-10-12.md` | db980bfbab96 | complete for the purchase-receipt slice; other shapes are UNMEASURED and outside the freeze |
| Test design: invariant matrix, coverage gaps, stories, DoD, focused tests | `docs/phase2/S11_TEST_DESIGN_PACKAGE_2026-10-12.md` and the V2 story register | bf031f0cd493, db980bfbab96 | accepted by GPT-PM as design evidence; story ids reconciled in the register |
| Gate manifest, status ledger, closure validator | `governance/GATE_MANIFEST.json`, `scripts/validate_gate_manifest.mjs`, `scripts/sign_waiver.mjs`, `governance/WAIVER_SIGNERS.json`, `tests/gate_manifest/run_fixtures.mjs` | d60757502a40, 2c533837d6e5, 7941bd3dc2c6, 53eac14de43a, 4afe298e1206 | complete; fixture run 87 of 87 asserted, GPT-PM closed S11-R01, S11-R01a and S11-R02 |

## 2. Review history of S11

GPT-PM rounds on S11 (PM Bridge project `erp_mcp_r2`): the plan baseline revision 5 approved; round 1 five MAJOR (S11-G01..G05) closed; round 3 S11-R01 closed with a residual S11-R01a; round 4 S11-R01a (waiver authority) and S11-R02 (rights evidence) raised; round 5 both CLOSED with 0 BLOCKER and 0 MAJOR open. The remaining GPT-PM list for S11 exit was the documentation items now delivered (OB-15 draft, inventory completeness or explicit exclusion, purchase-receipt rule table, story-id reconciliation, stale-wording reconciliation, exact-head manifest).

## 3. Tracked operator dependencies (not performed, not approved by this package)

| Item | Needed by | State |
| --- | --- | --- |
| OB-01 scope rebaseline recognition | G0 closure | OPEN, operator |
| OB-15 approval of the donor and license inventory | G0 closure | OPEN, draft delivered |
| D9 concrete checkpoint host, account and signer custody | before S13 implementation | decision recorded, host to be named |
| D10 operator person id | before S12 starts | decision recorded, id to be supplied |
| Waiver signer key registration in `governance/WAIVER_SIGNERS.json` | only to exercise the G4 waiver path | OPEN, operator |
| OB-11 accountant attestation | G3 and later gates | OPEN, not an S11 or S12 dependency |
| Production canary permission, IdP, UI scope | later gates | OPEN, not an S11 dependency |

## 4. Honest limits

Everything measured on 1C was measured on the disposable clone, file base, COM, one document type and one posted shape; nothing is authorized for staging, production, another base or a client-server installation. Fixture and 1C results are reported by agents and by the main session; GPT-PM verified file hashes and static consistency, not the live runs. Forced termination stays disabled, unresolved calls use the base-wide hold, the marker is an untrusted label verified by hash, OData writes and contract updates are outside the first freeze. G0-G8 stay NOT_PASSED and Release 2 stays NO-GO.

## 5. What the S12 freeze package must contain (from the GPT-PM verdict)

Accepted D4, D6-D8, D12 and the operator person id; the purchase-receipt-only catalogue; CT1 identity and live-epoch contract; CT2 logical key, canonical digest, marker distrust and recovery proof rules; CT3 call ownership and base-wide hold; CT5 checkpoint and signer interface; CT7 independent post and unpost approvals; CT9 kill-switch modes; CT10 full transition table and error codes; CT13 budget matrix; CT14 channel and rights qualification; CT15 conservative recovery and liveness; operation-specific verification evidence; E-series acceptance mapping with the documented NOT_RUN capabilities. A separate GPT-PM approval of that actual interface contract is required.

## 6. Current decision reconciliation (2026-10-15)

The dependency table above is a snapshot from 2026-10-12. The later operator decisions recorded in `docs/phase2/OPERATOR_BACKLOG.md` supersede its OB-01 and OB-15 states:

| Item | Current decision/evidence | Remaining G0 acceptance |
| --- | --- | --- |
| OB-01 — scope | DECIDED 2026-10-14: isolated prototype until G0 on the disposable clone `818HA_p2diff`; no R1 scope rebaseline. | Include the recorded decision and its narrow boundary in the G0 evidence package and obtain the gate review. |
| OB-15 — donor/license inventory | ACCEPTED_WITH_NAMED_DEFERRAL 2026-10-14: inventory sections 9, 9a and 9b accepted; R2 lock file/SBOM and host-binary license, pin and checksum facts deferred to deployment qualification. | Preserve the deferral in the G0 evidence package; do not claim the deferred deployment evidence or broad license-boundary clearance is complete. |

The scope decision record, threat model, R1 boundary and source inventory remain the recorded G0 inputs. This reconciliation does not itself approve G0 or alter `governance/GATE_MANIFEST.json`: G0 remains NOT_PASSED until the exact evidence package is reviewed and the gate manifest carries valid evidence. No production authorization is implied.
