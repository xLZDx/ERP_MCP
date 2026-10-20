# G0 scope and architecture evidence index — 2026-10-15

## Review request and current state

This index assembles the recorded G0 evidence at source HEAD `63c347441d84ad646a43519efa8d21399ac8949c`. It requests a gate-specific review of scope, architecture, the R1 boundary and donor/license inventory. It does not itself pass G0 or authorize staging, production, real 1C writes, redistribution, or any other release action.

Current manifest state at the source HEAD: G0 `IN_PROGRESS` / `NOT_PASSED`; external evidence `OPEN`; production authorization `NONE`. Keep those values until the gate reviewer accepts this exact evidence and the manifest records its evidence digest.

## Evidence artifacts

Hashes below are SHA-256 of the exact UTF-8 file bytes at the stated source HEAD.

| G0 requirement | Artifact and relevant content | SHA-256 | State / limitation |
|---|---|---|---|
| Scope, operation and channel boundary | `docs/phase2/S11_SCOPE_DECISIONS_AND_GATE_MANIFEST_2026-10-12.md` — scope record, decisions, clone-only purchase-receipt feasibility | `890bec2ab5937735193752ee42f9ab05a37bc6357e0808252fecb45b9d2bf690` | Recorded prototype scope; decisions marked proposed or open remain so. |
| Architecture and threat model | `docs/phase2/S11_DECISION_RECORDS_AND_THREAT_MODEL_2026-10-12.md` — CT1–CT15 and S11 threat decisions | `2b850dd4965675b7fc0140f9cd0406a2769df22651d831dce6b6ddf02a7d61e1` | Design evidence; does not qualify a production implementation. |
| R1 boundary and source inventory | `docs/phase2/S11_SOURCE_EVIDENCE_INVENTORY_2026-10-12.md` — sections 6–7 inventory the R1 write surface and OB-15 state; exclusions and unverified components are explicit | `723329acc6d6e89195dae94ffc69cf1022b585c9b8b7f71d188171b9ef40d5a2` | Limited to its declared inventory purpose; NOT_VERIFIED entries remain open. |
| Donor/license inventory | Same source inventory — sections 9, 9a and 9b | `723329acc6d6e89195dae94ffc69cf1022b585c9b8b7f71d188171b9ef40d5a2` | Accepted by the operator with named deferrals; not broad license clearance. |
| Recorded operator decisions | `docs/phase2/OPERATOR_BACKLOG.md` — 2026-10-14 OB-01 and OB-15 decisions | `6eb1cb0e68a8e8a771cef2f29cc98293ec5a0776f3dfaf81b19571432a70a98f` | OB-01 permits only the isolated prototype on `818HA_p2diff` until G0, without R1 rebaseline. OB-15 is accepted with named deployment deferrals. |
| Reconciliation of historical dependency snapshot | `docs/phase2/S11_EXIT_PACKAGE_2026-10-12.md` — section 6 | `146da7154e5225fca487bfd3b282b2e1a871d1589f54d9ad70de5cf4c075c05a` | Explicitly supersedes the package's older OB-01/OB-15 status; does not pass G0. |
| Feasibility evidence | `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` | `07cce66f04fc67157dfa49fe9c52ecc55946adc606acd902aa0f285e7cbc8eae` | Qualified clone-only COM/file-base purchase-receipt slice; unmeasured cells remain restricted. |
| Operation catalogue and acceptance mapping | `docs/phase2/S11_OPERATION_RULES_AND_STORY_REGISTER_2026-10-12.md` | `8df37a34b3916760fad8dabe54e2eaa5798ee1fa886b0631f47a406d71199144` | Purchase-receipt slice only; other shapes remain unmeasured/out of scope. |
| Gate closure contract | `docs/phase2/PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` — section 9 | `c1fcff7a528a5698520707f1e15e1e7064a5fd594c3438e927178562c573f2d1` | G0 closes only after GPT-PM approval and recorded operator decisions. |
| Current gate-state baseline | `governance/GATE_MANIFEST.json` | `8e3495169cf969aa1fd1f630b1caba7bf59c2f7019bbce7d59240910b9349dce` | G0 is IN_PROGRESS / NOT_PASSED; all production authorization values are NONE. This index does not change the manifest. |

## Decision and deferral boundary

- **OB-01:** the operator decided on 2026-10-14 to allow an isolated prototype until G0 on disposable clone `818HA_p2diff`; no R1 scope rebaseline was approved.
- **OB-15:** the operator accepted inventory sections 9, 9a and 9b with named deferral to deployment qualification for an R2 lock file or SBOM and host-binary license, pin and checksum facts.
- The named deferrals remain open. This index does not claim `LICENSE_BOUNDARY_APPROVED`, complete dependency provenance, or redistribution rights.
- The accepted S11 feasibility slice does not imply support for unmeasured 1C channels, client/server bases, other document types, staging, or production.

## Requested gate decision

Review whether the listed scope/architecture evidence and the recorded OB-01/OB-15 decisions satisfy G0's closure contract. If accepted, record a gate-specific GPT-PM approval tied to this index and its SHA-256, then update the G0 manifest evidence/status accordingly. If not accepted, return the missing evidence as an ordered list. G0–G8 statuses and production authorization have not been changed by creating this index.
