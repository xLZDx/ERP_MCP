# S14 Risk and Gate Closure Packet — 2026-10-15

## Purpose and authority boundary

This packet turns the open R-01/R-03 findings and the current G0–G8/S13 status into explicit engineering dispositions and acceptance evidence. It records proposals for future production design; it does not pass a gate, authorize a real-system operation, or change the approved non-gating synthetic scope.

Source of truth reviewed: `docs/phase2/OPERATOR_BACKLOG.md`, `docs/phase2/PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` (especially §§9–10 and the G8 acceptance contract), `docs/phase2/S11_SCOPE_DECISIONS_AND_GATE_MANIFEST_2026-10-12.md`, `governance/GATE_MANIFEST.json`, and the S14 simulation checkpoint. `GATE_MANIFEST.json` still records every G0–G8 gate as `NOT_PASSED` and production authorization as `NONE`. PM Bridge has no separate gate records for `erp_mcp_r2`. Read-only database and security reviews at HEAD `8935deda` reconciled stale G1/S13 claims; their exact findings and remaining evidence are recorded in `G1_OPERATOR_BACKLOG.md` and `S13_REVIEW_FINDINGS_2026-10-12.md`.

## R-01 — dispatch receipt requirement

**Disposition proposed:** the production write boundary must require a dispatch receipt for every governed write. The requirement must be enforced at the trusted boundary and fail closed when absent; it must not be a caller-selectable opt-in. An unknown write outcome remains unknown and must be reconciled; it must not be retried as if no effect occurred.

**Scope limit:** do not change the existing synthetic prototype's compatibility behavior or treat its marker as a production trust control. No production writer is currently operational.

**Acceptance evidence before closing R-01:**

1. Inventory every production write entry point, role, and completion path.
2. Show that each path either enforces receipt creation/verification or is denied; prove there is no direct completion bypass.
3. Review the trust boundary, signer identity, key custody, receipt-to-payload binding, replay behavior, and unknown-outcome reconciliation.
4. Add focused negative evidence for missing, invalid, replayed, and persistence-uncertain receipts at the enforcement boundary.
5. Obtain independent security/database review of the exact implementation and deployment plan.

**Status:** OPEN; production-blocking MAJOR in independent static security review at HEAD `8935deda`. This is a design recommendation, not a completed trust-boundary review. The write port remains non-operational, so the review identified a production qualification blocker, not a current production exploit.

## R-03 — legacy verifier keys

**Disposition proposed:** do not register or use `KEYED_HASH_STANDIN` keys for new authorization or new receipts after production cutover. New authorization keys must be Ed25519 with an independently verified owner, purpose, fingerprint, and custody record. Preserve legacy verification only for explicitly read-only historical evidence where required for audit; historical verification must never grant new write authority. Do not delete or rewrite existing keys or signatures as part of this prototype.

**Acceptance evidence before closing R-03:**

1. Inventory legacy key rows and every signature/receipt they verify, without exposing key material.
2. Assign accountable custody and rotation owners for production keys; verify identity and key provenance independently.
3. Define a reversible cutover: prevent legacy keys from authorizing new actions while retaining required historical verification and audit provenance.
4. Demonstrate denial of legacy-key use for new authorization, plus continued correct read-only verification of historical records.
5. Obtain independent key-governance/security review before any production identity qualification.

**Status:** OPEN; production-blocking MAJOR in independent static security review at HEAD `8935deda`. Migration 015's compatibility is unchanged; this proposal authorizes no key mutation or production cutover. The write port remains non-operational, so this is a qualification blocker, not a claim of a current production exploit.

## Gate closure matrix

| Item | Current state | Evidence already in the repository | Remaining acceptance | Dependency / owner |
|---|---|---|---|---|
| G0 — scope and architecture | NOT_PASSED; engineering IN_PROGRESS | `GATE_MANIFEST.json`; scope decisions, threat model, R1 boundary and source inventory; OB-01 decision and OB-15 named deferral reconciled in `S11_EXIT_PACKAGE_2026-10-12.md` | Assemble exact-head G0 evidence index, preserve OB-15 deployment deferrals, and obtain gate review; do not treat the accepted deferral as completed deployment license evidence | Scope/release decision role; no individual is named |
| G1 — database and security | NOT_PASSED; engineering NOT_STARTED in manifest | Reconciled `G1_OPERATOR_BACKLOG.md`; migrations 003–018 and focused disposable runs cover portions of scope; independent static review at `8935deda` found no receipt-migration cross-tenant bypass under the stated owner/superuser boundary | Exact-head G1 run still lacks a kill timed inside COMMIT, restore to another cluster, production-class capacity decision, and complete effective-role/approver evidence | Database/security lane; disposable PostgreSQL runtime evidence and gate-specific review |
| G2 — metadata/domain | NOT_PASSED | S11 feasibility and catalogue documents | Authenticated source observation and source-specific capture permit; confirm operation catalogue and domain rules against real source evidence | OB-10; source access authority, no named individual |
| G3 — accountant attestation | NOT_PASSED | Backlog records the missing native 521.1 report | Native report for 818 HA SRL, account 521.1, 2026-08-01..2026-08-31, independently exported and attested | OB-11; independent accountant, no name recorded |
| G4 — Drive, conditional | NOT_PASSED; `drive_intake_enabled=false` | Manifest disables Drive intake | Keep conditional and unpassed unless scope formally excludes it or required narrow OAuth/folder evidence and the applicable signed waiver are supplied | Drive/account authority; no named individual |
| G5 — UAT | NOT_PASSED | Plan defines UAT after S16/S17 | User and accountant acceptance on the approved UI and workflows with recorded results | UAT participants; no names recorded |
| G6-pre — operational readiness | NOT_PASSED | S9 decision modules are not gate evidence per the plan | Actual workload metrics on target infrastructure, alert delivery, repeatable recovery, and operational ownership | Operations lane and real target environment; no individual named |
| G6 — production canary | NOT_PASSED; authorization NONE | Plan defines a signed, narrowly scoped canary | Only after G3, G5, G6-pre, and G8; requires a signed permission with base, company, operation, limit, expiry, and purpose plus production-class evidence | Release/operator authorization role; not authorized by this GO |
| G7 — release | NOT_PASSED; Release 2 NO-GO | Manifest and release plan | All applicable predecessor gates passed and exact-head `PRODUCTION_GO` approval recorded | Release owner; no individual named |
| G8 — controlled-change acceptance | NOT_PASSED; engineering IN_PROGRESS | Synthetic S12–S14 work is partial/prototype evidence | Complete S12–S18 and active golden scenarios with falsifiable enforcement-boundary evidence; G8 does not pass or replace other gates | Engineering and independent review lanes |
| S13 — ledger and audit anchor | NOT_STARTED in manifest; formal entry NOT APPROVED | Synthetic migration/tests and historical prototype records | Meet formal entry conditions, complete the current ledger/audit-anchor contract and independent evidence; synthetic S13 runs alone do not qualify formal entry | S12 dependency, database/security review, gate decision role; no person named |

## Ordered execution queue

1. Keep the two R-01/R-03 dispositions as proposals until their stated trust/key-governance evidence exists; do not change production defaults or keys in this synthetic slice.
2. Reconciled the historical G1 blocker list; next, complete the missing exact-head disposable-PostgreSQL evidence and gate-specific review listed in `G1_OPERATOR_BACKLOG.md`.
3. Close the G0 scope and inventory evidence package; then advance G1 and G2/S13 evidence in dependency order.
4. Obtain the external accountant and source evidence for G2/G3. Resolve G4 only if Drive intake is enabled; otherwise record the scope decision without pretending the gate passed.
5. Complete S16/S17 before G5; establish G6-pre and G8 evidence before any G6 canary discussion.
6. Keep G7 and Release 2 NO-GO until every applicable gate is actually passed and the release owner records `PRODUCTION_GO`.

No test, migration, key change, real-system access, staging action, production action, or release-gate state change is performed by this documentation packet.
