# Phase 2 operator backlog

Date: 2026-10-08. Branch: `phase2/living-model-connectors-reconciliation`. Release 2 status: **NO-GO**.
Only items that engineering cannot close without the operator. G1-specific blockers stay in `G1_OPERATOR_BACKLOG.md`.

Evidence source: six read-only local reviews of HEAD `9b4fc0c` (database, security, Python, test adequacy, reliability, architecture) on 2026-10-08. Findings are static; nothing was executed on PostgreSQL.

## P0 — block G0/G1 and any merge

| ID | Blocker | Evidence | Minimal operator action | Blocks |
| --- | --- | --- | --- | --- |
| OB-01 | No G0 / scope rebaseline recorded for R2 code inside the R1 repository | `docs/DOCUMENT_INDEX.md` says FROZEN / NO NEW SCOPE; `docs/SCOPE_FREEZE_BASELINE_2026-10-06.md` §7 requires frozen IDs; no `phase2` mention in R1 normative docs | Record a decision: rebaseline, or explicit permission for an isolated prototype until G0 | Any merge to main, G0 |

OB-01 status (2026-10-13): operator decision "accept" (chat, 2026-10-13: "решения по OB-01 и OB-15 (принять)"). The operator did not name an option and did not state the scope limits. The operator's decision is therefore only "accept". The limits below are a RESTRICTION applied by the agent and by GPT-PM review (request 3e9a0f47), not an explicit operator decision: permission for an isolated prototype until G0, only on the disposable clone `818HA_p2diff` with an authenticated base fingerprint, only for the purchase-receipt operations of S12 contract revision 6; no R1 scope rebaseline, no merge to main, no staging, production, real-money operation or deletion. G0 stays NOT_PASSED until its manifest evidence exists, and G0 may still require the operator to name a scope baseline explicitly.
| OB-02 | No dedicated ChatGPT conversation bound to this worktree in PM Bridge | `pm_rosetta_plan` refused: no project to conversation binding for `D:\Repo\ERP_MCP-phase2`; `config/projects.json` has only `erp_mcp-integration-candidate` and `erp_mcp-native-reports` | Provide an exact `https://chatgpt.com/c/<id>` link for a Phase 2 chat (do not reuse the R1 chat) | GPT-PM review, Rosetta governed work, push approval |
| OB-03 | RESOLVED 2026-10-08: operator ordered a disposable instance; docker container `erp-phase2-test-pg` created and used (20/20 integration tests green). Earlier text: No authorized disposable PostgreSQL | No docker/psql/pg_ctl on PATH, no PostgreSQL service on this machine | Authorize/create a disposable R2 test database with separate credentials, isolated from R1; supply DSN via `ERP_PHASE2_TEST_DSN` | G1-08/09, all integration/security/concurrency/backup tests |
| OB-04 | Source registry decision: `living.sources` (own) vs reuse of R1 `bag.sources` | `CONTRACTS_AND_API_RU.md` says existing sources are reused; `001_living_registry.sql` defines its own table | Choose: same DB with FK, or separate DB with sync | Final shape of RLS and FKs |
| OB-05 | ANSWERED 2026-10-08: no CI, R2 not mixed with R1, R1 updates pulled by merge. Earlier text: R1 fingerprint gate and CI include Phase 2 directories | `scripts/engineering_checkpoint.py` hashes `src`, `tests`, `scripts`; `pyproject.toml` `testpaths=["tests"]`; CI runs full `pytest` | Approve excluding `*/phase2` from R1 fingerprint/CI, or moving R2 code out of R1 trees | R1 gate health, merge |
| OB-06 | Earlier remote tool policy refused a hardening-SQL write | Recorded in `G1_IMPLEMENTATION_NOTE_2026-10-08.md`; local authoring path is separate and no bypass was used | Only if the remote route is still needed: resolve policy with the provider | Remote-tool authoring only |

## P1 — external access needed for later sprints

| ID | Blocker | Minimal operator action | Blocks |
| --- | --- | --- | --- |
| OB-10 | Real 1C source access and source-specific capture permit for `onec-818ha-reference` | Provide scoped read access and permit | S3 qualification, S5 |
| OB-11 | Independent accountant attestation for 818 HA SRL, account 521.1, 2026-08-01..2026-08-31 | Accountant exports native report and attests | S5/S6, G3/G4 |
| OB-12 | ERP_MCP-owned Google Drive OAuth client and narrow folder grant | Create OAuth client, grant narrow folder/new-child access | S7 |
| OB-13 | Secret provider and rotation procedure for production | Name provider and owner | S1 secret rotation, S9 |
| OB-14 | R1 shadow-compatibility and production canary approval | Approve canary window and rollback owner | S9/S10 |
| OB-15 | Donor code/license inventory approvals | Review inventory; approve any GPL/AGPL boundary | S0/S1 |

OB-15 status (2026-10-13): **OPEN**. Status DRAFT_ACKNOWLEDGED: the operator answered "accept" in chat on 2026-10-13 without qualification, and that answer is preserved without expanding its meaning. It is not a formal closure, because the draft states that evidence is still missing for the operator's approval (GPT-PM bounded review b27d5c18, finding B-01). The draft is the donor code/license inventory in `S11_SOURCE_EVIDENCE_INVENTORY_2026-10-12.md` section 9 (a DRAFT for the operator; an earlier record of this decision cited the S11 scope record by mistake, which was wrong). The acknowledgment covers that draft as written; its NOT_VERIFIED items and the "Missing for the operator's approval" list at its end stay open. Closure needs the missing inventory evidence to be completed and explicitly accepted by the operator, or a validly authorized deferral that names what is deferred. INVENTORY_ACCEPTED: NO. LICENSE_BOUNDARY_APPROVED: NO. Nothing here establishes ownership of all donor code, redistribution rights, GPL/AGPL compatibility or separation, approval of later donor additions, or clearance of dependencies missing from the inventory. PDCC is the operator's own code, written for another project (operator statement 2026-10-12). No gate changes; G0 still needs its manifest evidence.

Operator decisions of 2026-10-14 (answers to direct multiple-choice questions in chat; they supersede the OPEN and agent-restriction wording of the OB-01 and OB-15 status paragraphs above, which stay as history):

- OB-01: the operator confirmed the narrow reading as their own decision: isolated prototype until G0, only on the disposable clone `818HA_p2diff`, no rebaseline of the R1 scope. G0 scope baseline: "prototype until G0" (the same narrow line), to be revisited at the G0 review.
- OB-15: the operator chose "accept with a named deferral". Accepted as written: the inventory in sections 9, 9a and 9b of `S11_SOURCE_EVIDENCE_INVENTORY_2026-10-12.md`. Deferred to deployment qualification, by name: an R2 lock file or SBOM; license, pin and checksum facts for the host binaries. The R2 license statement is recorded as "all rights reserved, internal" (the operator's own code). Status: ACCEPTED_WITH_NAMED_DEFERRAL. LICENSE_BOUNDARY_APPROVED: NO. The deferral does not close the deferred items.
- S13: work on migration 007 and batch B is allowed as a non-gating prototype on a disposable database; its results are not gate evidence.
- Tests: focused functional tests of S12 and S13 written and run by the named agents on disposable containers are allowed. CI, lint, full suites and CI mirroring stay forbidden.
- D10, D10b, D9, D4: stay AGENT_SELECTED_TEST_PLACEHOLDER until the first real write to 1C. Real D9 (host, account, Ed25519 signer) and a separate D10b witness are required before that first real write.
- Push: the local R2 commits may be pushed after this decision.

## P2

| ID | Item |
| --- | --- |
| OB-20 | R2-US-047 (FOLLOW_ON/P2): confirm in or out of Release 2 scope |
| OB-21 | Final release-owner approval for `PRODUCTION_GO` (only after G0–G7 actual PASS) |

## Unblock criteria

- OB-03 resolved: `pytest -m integration` with `ERP_PHASE2_REQUIRE_PG=1` runs and is green on the exact head; roles, RLS, immutability, CAS, fencing, outbox crash and backup/restore evidence recorded.
- OB-02 resolved: plan recorded and approved, one broad GPT-PM sweep on the exact head, correlated APPROVE before push.
- OB-01/04/05 resolved: decision recorded in `docs/phase2/DECISION_LOG.md`.
# Simulation lane minor findings (2026-10-15)

- R-01: `require_dispatch_receipt` remains opt-in. Owner: project design lane (no named human recorded). Next action: decide a fail-closed policy only after a production trust-boundary review; do not interpret the prototype marker as a trusted-writer safeguard.
- R-02: migration 009 stores a typed-payload digest while the clone signs received wire bytes. S14 prototype design and migration 018 now keep the typed approval digest separate and bind the clone receipt to the canonical wire-byte digest. State: IMPLEMENTED_UNVERIFIED; migration not run. Owner: ledger/writer design lane (no named human recorded). Next action: focused functional/E2E evidence, database review and exact-range GPT-PM review before claiming prototype closure; real integration remains out of scope.
- R-03: legacy `KEYED_HASH_STANDIN` verifier keys remain accepted. Owner: key-governance lane (no named human recorded). Next action: decide a migration/retirement policy before production identity qualification.
- R-04: addressed in the combined SQL scenario file; independent e2e passed 14/14 and dump/restore passed 6/6. GPT-PM approved exact range `598a7a50bbe131ede43c28f7e1bac39804c70df5..2edc82eab3f2a99a08bc07581ff7a37e08a22e75` as a NON-GATING prototype (request `9e9dc3a4-48f8-405e-a89e-d0903c8d5549`); the approved range is pushed to `origin/main`.
- Migration 017 hardens requirement carry-forward, terminal receipt rejection, and receipt-key role separation. Focused independent tests passed 4/4; manual database review found no BLOCKER/MAJOR.
- R-05 (2026-10-15): code review noted that the tamper test used an arbitrary mismatching digest, not a digest computed from the actual received wire bytes. Updated the test comment to state the narrower assertion and preserve the documented 009 typed-payload versus wire-byte digest gap. This is a documentation-only clarification; no functional claim or gate status changes. No named human owner recorded. Next action: define a canonical wire-digest contract before real integration (same dependency as R-02).
