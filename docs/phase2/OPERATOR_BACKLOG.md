# Phase 2 operator backlog

Date: 2026-10-08. Branch: `phase2/living-model-connectors-reconciliation`. Release 2 status: **NO-GO**.
Only items that engineering cannot close without the operator. G1-specific blockers stay in `G1_OPERATOR_BACKLOG.md`.

## Current reconciliation (2026-10-22)

This section supersedes the 2026-10-17 snapshot below where dates or observations differ;
older gate decisions remain historical and are not changed by this operational update.

- Reconciliation base HEAD was `d82cfa4cd44b105608c294d742c84fa8cdbc950f`. Local commits
  `33f76b7` and `d82cfa4` record the SSH audit and safe document-registry generation. No
  push was performed, and remote-head equality was not rechecked in this run.
- The current checkout is branch `codex/erp-mcp-autonomous-2026-10-21` at
  `d0763b0e74be06e0b5d5ba34c1744e7c357ed0a0`; the worktree contains unstaged
  changes. No branch switch was attempted because that would move the base under those edits.
  The operator clarified on 2026-10-22 that the prohibition is on a staging deployment, not
  Git staging: explicit-path `git add` and local commits are authorized, with GPT-PM approval
  required before each commit and exact-head approval required before push/PR. Earlier wording
  that treated Git staging as forbidden is superseded.
- A read-only history audit of the 10 task-branch commits found a dedicated change-record file
  in every commit. Eight commit messages name that record; commits `ae581ee` and `33f76b7`
  include the files but omit their paths from the messages. Only the first four commits include
  `core/LESSONS_LOG.md`; the last six do not. History was not rewritten; link each record and
  include the required lesson entry in future commits. See
  `docs/commits/2026-10-22-commit-record-audit.md`.
- Release 2 remains **NO-GO**; G0 remains PASSED only for its narrow isolated-prototype
  scope, G1–G8 remain **NOT_PASSED**, formal S13 remains **NOT_STARTED / NOT_APPROVED**,
  and production authorization remains **NONE**. This update changes no gate or manifest.
- **Superseded SSH/host-key observation:** the operator verified Ivan's host key in
  `known_hosts` under `100.88.71.74` and supplied the matching fingerprint. This turn then
  connected using `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74`;
  the read-only stack status returned exit 0 and all nine components `True`. The command also
  listed only names in `D:\1c\mcp`. This establishes strict host-key acceptance and current
  stack status, not the COM writer boundary or deployed PostgreSQL grants. No service was
  restarted. See `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-22.md`.
- Local development PostgreSQL and Redis are currently healthy on loopback ports 5432 and
  6379. The real1c PostgreSQL and Redis containers were also observed healthy on loopback;
  their origin was not independently verified. No migration or business write was run.
- The disposable E2E Compose project requires generated owner/Redis passwords in
  `.e2e/compose.env` (`compose.e2e.yml`). Its documented startup command,
  `scripts/e2e/up.ps1 -Seed baseline`, generates that environment, starts Compose, runs
  schema migrations, verifies and seeds the database, then starts host processes
  (`docs/E2E_ENVIRONMENT.md`, "Commands"; `scripts/e2e/up.ps1`). No separate supported
  database-only startup path was found in those instructions. The command was not run under
  the current no-migrations/no-tests restriction; this continuation started no services.
- **Superseded connector-path observation:** historical `ERP_MCP_REAL1`/`erp-mcp-chatgpt`
  connector errors do not describe the authorized local gateway path; the operator explicitly
  directed this work not to use `ERP_MCP_REAL1`. This turn minted a short-lived `auditor`
  token in process and called `source_health` and `accounting_balance_by_analytics` through
  `http://127.0.0.1:21000/mcp`. Health returned `ok=true`; the read returned 15 rows labeled
  `VALIDATED_MACHINE_RECONCILED` / `PROFILE_VALIDATED_MACHINE` / `MACHINE_TWO_SOURCE`, with
  warning `MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT`. Row values and token were not printed.
  This is runtime read evidence only; it is not a human-signed report or release/canary
  acceptance. A previously recorded Ivan read returned 16 rows, so cross-lane reconciliation
  remains open.
- WP3 document navigation now has a reviewed `--exclude-local-only` generator mode. The
  earlier snapshot at base HEAD `0fe023db1ec2adcf1820356db1dd1db09d23c3ab` recorded 46
  refs and 426 tracked paths; it is historical. Later generation evidence in
  `docs/commits/2026-10-22-wp3-registry-historical-cyrillic.md` records 46 refs and 436
  tracked paths at branch ref `dd932427fdab2eed625cd320ecbcf5ffdd203ee0`; this is the latest
  generation snapshot evidenced in the repository, not a claim about refs created after it.
  Local-only paths were explicitly **NOT_ENUMERATED**. Functional tests and generator `--check` remain
  **NOT_RUN** under the active no-tests/checks restriction. See
  the dated addendum in `docs/phase2/artifacts/WP4_WP10_DEPENDENCIES_2026-10-21.md`.

The established writer-boundary, signer provisioning, clone qualification, S14–S18,
Drive deletion, and release dependencies below remain open. No source, authorization,
production, or manifest status changed.

- A read-only database review reconciled identified runtime grants and traced their
  helper/trigger effects at source level. `validate` violates the documented
  advisory-before-row order, and within the event-trigger sequence the chain lock is
  requested before the lifecycle row lock. No current deadlock cycle is claimed, but a global
  recovery fence order is unproven; keep recovery refused and lifecycle `NOT_READY`. See
  `docs/phase2/S13_SOURCE_FINAL_GRANT_AND_LOCK_INVENTORY_2026-10-22.md`.
- Disposable-lane ACL review found `bag.record_capability_observation(...)` has effective
  `PUBLIC EXECUTE`; a focused security reviewer rated this MINOR because the ordinary HTTP/MCP
  route remains authenticated, but the SECURITY DEFINER function lacks caller/source
  authorization and can write source-scoped capability claims. A forward-only migration 015
  now revokes PUBLIC and keeps the app-role grant; it is not run or runtime-verified. The
  disposable database lacks the separate `change_ledger` schema, so S13 effective grants remain
  **NOT_VERIFIED**. See `docs/commits/2026-10-22-capability-function-execute-revocation.md`.

## Historical reconciliation (2026-10-17)

The tables and dated notes below preserve historical intake and decision snapshots; they are not a current action list where they conflict with this section. GPT owner ruling `b4e09308-7ae8-4170-92df-81ae67177bc1` authorized local S12 engineering. Request `e16939f8-9a6f-4c82-a75c-feb6a594a909` rejected `7c26c0c` for MAJOR-01; request `41f6d2e2-5710-4c50-9f84-06e23c4b12a7` approved and the exact range through `705076a` was pushed. CR123 records the accepted S12 remediation results: functional 7/7 and E2E 1/1, with no BLOCKER/MAJOR in the reviewed scope. CR154 later supplied focused local S13 evidence through migrations 001–026; CR166 records the limit that PASS covers post-026 behavior and that no safe database-only fence completes S13 without the operational writer/service boundary. The latest `ERP_MCP_REAL1` read-only calls failed with connector error `-32603`, yielding no G1/G2 source observation. G0 remains PASSED for its narrow scope; G1–G8 remain NOT_PASSED; formal S13 remains NOT_STARTED / NOT_APPROVED; Release 2 is NO-GO and production authorization is NONE. No manifest status is changed here.

| Item | Current state | Evidence / completed work | Remaining action and dependency | Owner |
|---|---|---|---|---|
| S12 Contract Freeze v2.0 | Local synthetic code gate approved and pushed; formal qualification remains open | CR121: functional 6/6 and E2E 20/20; CR123: remediation functional 7/7 and E2E 1/1; GPT approved exact range through `705076a`; push succeeded | Formal S12/G8 and deployed PostgreSQL/1C/COM qualification remain open; keep local synthetic evidence distinct | Engineering delegated to GPT/agent workflow; tests: functional-test-reviewer and e2e-runner |
| S13 ledger and audit anchor | Reviewed source tracing complete for the identified repository paths; broader S13 engineering remains in progress. Formal entry remains `NOT_STARTED / NOT_APPROVED`; preflight remains `NOT_READY`. | CR143/145 focused evidence through migrations 001–024; CR154 functional PASS (47 classifier assertions and 14 grouped disposable PostgreSQL scenarios), E2E PASS on PostgreSQL 16.14, plus database/security/reliability reviews of changed source hashes through migrations 001–026. CR166 and the 2026-10-22 static inventory reconcile identified source-final mutation grants, helper/trigger effects, recovery-stage paths and UPSERT conflicts. They find no proven global lock order; `validate` takes a row lock before its advisory lock. The full S13 suite remains `NOT_RUN`. The read-only local PostgreSQL inspection on 18432 found no `change_ledger` schema, so effective local post-migration grants remain `NOT_VERIFIED`. | Keep preparatory migrations unapplied outside disposable evidence. Continue the private service boundary with stable call-ID idempotency, stale-epoch rejection, authoritative outcome lookup and a quiescence barrier; design a viable cross-path fence before migration. Host/connection technical owner: Ivan stack (`ERP_MCP_Ivan_Stack`); accountable task owner: operator; Codex executes local implementation. Complete effective-grant capture on the disposable database after migration qualification, then bounded transaction lifetime, recovery-to-READY, physical writer integration and provider/signer qualification. | Accountable: operator; technical host/connection owner: Ivan stack; executor: Codex; functional/E2E agents own tests; database/security/reliability review roles own independent reviews |
| R-01 | OPEN formally | Local synthetic receipts exist, but migration 016 marker is opt-in and `OneCWritePort` is not an operational writer | Inventory production write boundaries and establish mandatory trusted-boundary receipt enforcement, identity/custody, replay and unknown-outcome evidence | Engineering/key-governance direction; no named person |
| R-03 | OPEN formally; local prototype implementation/evidence complete | Migrations 019/021; CR112, CR115, CR116 and database/security reviews | Obtain deployed non-secret key/use inventory, independent custody/provenance, historic signing-time classification, reversible production cutover, and formal review | Key-governance direction; no named person |
| S13 lock-order MINOR | Deferred to S18 | Reliability review found a possible transient deadlock, not false OFF; CR117 and S13 design record it | Align lock order or separate nonce cleanup and add deterministic contention scenario in S18 | Engineering/S18; no named person |
| G4 / Drive | v2.0 target excludes Drive; manifest unchanged and G4 NOT_PASSED | `drive_intake_enabled=false`; GPT ruling | Record applicable formal scope/waiver authority before any manifest change; do not infer gate passage | Scope/gate authority; no named person |
| CT14 / write scope | Partial clone-only evidence | Existing feasibility report; no production capability claim | Exclude OData writes, contract update, forced session termination, and unrelated work during unresolved calls from v2.0 write scope | S12/CT14 engineering; no named person |
| Authorized ERP source observation (G1/G2 input) | PARTIAL; not gate acceptance | Current turn: local direct MCP `source_health.ok=true` and 521.1 analytical read returned 15 rows with `VALIDATED_MACHINE_RECONCILED` / `MACHINE_TWO_SOURCE`; the values were suppressed. The historical 16-row Ivan result remains unreconciled. The operator identifies Ivan Stack as the technical owner of the existing host/connection boundary; operator is accountable for this delegated project task. | Reconcile the 15-versus-16 row set through the approved read-only comparison after all in-scope code is complete; keep human/native accounting attestation and G1/G2 gate evidence separate. Do not use `ERP_MCP_REAL1`. | Operator accountable; Ivan Stack technical owner of the host/connection boundary; test roles own later mapped comparisons |
| CR164–CR170 local publication snapshot | CR164–CR169 are committed locally through `be33c4f0d529f9afb3f14727ce0557a5fe7f9a24`; CR170 is the current documentation follow-up. `origin/main` remains at base `85a179455365dcfadd01f827feb1304cec7fe006`. | CR164–165 reconcile and correct the registry generator; CR166 reconciles S13 evidence; CR167 updates this backlog; CR168 fixes registry count grammar; CR169 orders S13 work behind the writer boundary. PM Bridge request `826c8867-4d43-40be-8c32-3abdd4435131` requests review of exact HEAD `be33c4f0d529f9afb3f14727ce0557a5fe7f9a24` and is still queued, not sent; no correlated approval exists yet. Earlier requests were for superseded exact heads and cannot approve this range. | Wait for correlated approval of the exact current HEAD; then confirm `origin/main` still equals the reviewed base before the authorized fast-forward push. Any new commit requires a fresh exact-head review. | GPT-PM owns the review decision; GPT/Codex executes an approved push |

Historical R-03 source descriptions below that say migrations 015–018 still allow legacy-signed action use are superseded: migrations 019/021 and CR112/115/116 address the local prototype paths. The formal deployed-key and custody risk remains open. Result semantics: an exit code of zero, `NOT_RUN`, or `SKIP` alone is not PASS; PASS requires explicit terminal PASS evidence correlated to the exact revision and completed harness.

> **Historical intake snapshot.** The P0/P1 tables, dated status paragraphs and original unblock criteria below preserve the 2026-10-08 to 2026-10-14 decision history; do not read their earlier gate states as current. Later dated decisions and reconciliations supersede them. Current gate state is in `S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md` and `governance/GATE_MANIFEST.json`; current G1 evidence is in `G1_OPERATOR_BACKLOG.md`.

Evidence source: six read-only local reviews of HEAD `9b4fc0c` (database, security, Python, test adequacy, reliability, architecture) on 2026-10-08. Findings are static; nothing was executed on PostgreSQL.

## P0 — block G0/G1 and any merge

| ID | Blocker | Evidence | Minimal operator action | Blocks |
| --- | --- | --- | --- | --- |
| OB-01 | No G0 / scope rebaseline recorded for R2 code inside the R1 repository | `docs/DOCUMENT_INDEX.md` says FROZEN / NO NEW SCOPE; `docs/SCOPE_FREEZE_BASELINE_2026-10-06.md` §7 requires frozen IDs; no `phase2` mention in R1 normative docs | Record a decision: rebaseline, or explicit permission for an isolated prototype until G0 | Any merge to main, G0 |

OB-01 status (2026-10-13): operator decision "accept" (translated from the 2026-10-13 chat answer "decisions for OB-01 and OB-15 (accept)"). The operator did not name an option and did not state the scope limits. The operator's decision is therefore only "accept". The limits below are a RESTRICTION applied by the agent and by GPT-PM review (request 3e9a0f47), not an explicit operator decision: permission for an isolated prototype until G0, only on the disposable clone `818HA_p2diff` with an authenticated base fingerprint, only for the purchase-receipt operations of S12 contract revision 6; no R1 scope rebaseline, no merge to main, no staging, production, real-money operation or deletion. G0 stays NOT_PASSED until its manifest evidence exists, and G0 may still require the operator to name a scope baseline explicitly.
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

Current status (2026-10-16): G0 has since been marked `PASSED` for its exact isolated-prototype scope by the separate approval recorded in `CHANGE_RECORD_050.md`. OB-01 no longer blocks G0; the scope remains limited to the approved prototype and does not authorize R1 rebaseline, staging, production, or real 1C writes. OB-15 remains `ACCEPTED_WITH_NAMED_DEFERRAL`; its deployment deferrals remain open and `LICENSE_BOUNDARY_APPROVED` remains `NO`. The historical “revisit at G0 review” and “G0 still needs evidence” language above is superseded by that exact G0 record.

## Current risk dispositions (2026-10-16)

Historical source facts in this section were revalidated at code HEAD `ecd1779673f00209ac540729f420c2b4d5dddbbe`; they are not a current inventory for R-03 after migrations 019/021. Current branch and `origin/main` both resolve to `1ec73879ade35b112c428c9885b55c46452aa7df`. Current R-01/R-03 status and S12 scope are defined in the reconciliation above.

| Risk | Current source finding and state | Remaining acceptance | Lane / owner |
|---|---|---|---|
| R-01 — require a dispatch receipt at every governed production write boundary | OPEN. Migration 016's marker is opt-in; its `APPLIED` trigger checks the receipt only when a generation marker exists, so omitting it preserves legacy completion. Migration 017 carries an existing marker; 018 binds a receipt to canonical wire bytes but does not make the marker mandatory. The located `SyntheticDispatchCoordinator` and `ReferenceWriter` are synthetic; `OneCWritePort` is only a protocol. The repository does not establish production deployment or enumerate all external write paths. | Inventory every actual production write entry point, role and completion path; enforce receipt creation/verification at the trusted boundary and deny bypasses; prove signer identity, custody, payload binding, replay and unknown-outcome handling; add negative missing/invalid/replayed/uncertain-receipt evidence and independent database/security review. No production behavior is claimed implemented. | Project design lane; no named human recorded. |
| R-03 — prevent legacy verifier keys from authorizing new actions | OPEN formally; the migration-015–018 source claim in this historical inventory is superseded. Local migrations 019/021 enforce Ed25519 at new writes and state-changing use of pre-cutover evidence; historical audit reads remain available. No deployed key or exploit is established. | Obtain an independent non-secret deployed inventory and custody/provenance; address signing-time algorithm/fingerprint limitations; plan reversible production cutover; obtain independent DB/security and key-governance review. | Key-governance lane; no named human recorded. |

No live database key rows, secrets, signatures, deployed write paths, or production state were inspected for this source revalidation. No migration or production change is authorized by these findings.

## P2

| ID | Item |
| --- | --- |
| OB-20 | R2-US-047 (FOLLOW_ON/P2): confirm in or out of Release 2 scope |
| OB-21 | Final release-owner approval for `PRODUCTION_GO` (only after G0–G7 actual PASS) |

## Historical unblock criteria (superseded by current workspace workflow)

The following snapshot is retained for audit only. Its pytest/CI directions are superseded by the current workspace rules; required focused tests are owned only by `functional-test-reviewer` and `e2e-runner`, and prohibited checks must be reported as `NOT_RUN`.

- OB-03 resolved: `pytest -m integration` with `ERP_PHASE2_REQUIRE_PG=1` runs and is green on the exact head; roles, RLS, immutability, CAS, fencing, outbox crash and backup/restore evidence recorded.
- OB-02 resolved: plan recorded and approved, one broad GPT-PM sweep on the exact head, correlated APPROVE before push.
- OB-01/04/05 resolved: decision recorded in `docs/phase2/DECISION_LOG.md`.
# Simulation lane minor findings (2026-10-15)

- R-01: `require_dispatch_receipt` remains opt-in. OPEN. Source inventory at code HEAD `450f977`, recorded in `CHANGE_RECORD_058.md` by commit `99b7d4c`: SQL 016 gates completion only when the marker exists; 017 carries it across claims; 018 binds receipt to wire bytes; the only located coordinator is the non-gating `SyntheticDispatchCoordinator`. No production writer/entry-point inventory exists in this repository. Owner: project design lane (no named human recorded). Next: define and inventory the production trusted boundary before implementing mandatory receipt enforcement. Proposed disposition and acceptance evidence: `S14_RISK_AND_GATE_CLOSURE_PACKET_2026-10-15.md`.
- R-02: migration 009 stored a typed-payload digest while the clone signs received wire bytes. S14 migration 018 preserves the typed approval digest and binds the receipt to canonical wire SHA. State: CLOSED for NON-GATING SYNTHETIC PROTOTYPE — focused SQL/dump-restore 9/9, combined E2E 15/15 on disposable PostgreSQL 16, independent database review with no findings, GPT-PM exact-head approval, and verified push to `origin/main`. Migration ran only in disposable test databases. Owner: ledger/writer design lane (no named human recorded). Remaining real 1C/COM integration and production identity qualification stay under their existing gates. See `CHANGE_RECORD_029.md`, `CHANGE_RECORD_031.md`, and `CHANGE_RECORD_033.md`.
- R-03: legacy `KEYED_HASH_STANDIN` verifier keys remain accepted. OPEN. Source inventory at code HEAD `450f977`, recorded in `CHANGE_RECORD_058.md` by commit `99b7d4c`: SQL 015 defaults new registrations to Ed25519 but retains a superuser legacy-registration exception and legacy verification in the shared signature dispatcher; SQL 017's receipt-purpose guard covers Ed25519 rows only; receipt verification still calls the shared dispatcher in 017/018. Source cannot reveal whether legacy rows/signatures exist in a live database. Owner: key-governance lane (no named human recorded). Next: obtain a non-secret inventory of deployed key IDs/algorithms, their signature uses, and independently verified custody owners; define reversible production cutover. No keys are changed by this record.
- R-04: addressed in the combined SQL scenario file; independent e2e passed 14/14 and dump/restore passed 6/6. GPT-PM approved exact range `598a7a50bbe131ede43c28f7e1bac39804c70df5..2edc82eab3f2a99a08bc07581ff7a37e08a22e75` as a NON-GATING prototype (request `9e9dc3a4-48f8-405e-a89e-d0903c8d5549`); the approved range is pushed to `origin/main`.
- Migration 017 hardens requirement carry-forward, terminal receipt rejection, and receipt-key role separation. Focused independent tests passed 4/4; manual database review found no BLOCKER/MAJOR.
- R-05 (2026-10-15): code review noted that the tamper test used an arbitrary mismatching digest, not a digest computed from the actual received wire bytes. Updated the test comment to state the narrower assertion and preserve the documented 009 typed-payload versus wire-byte digest gap. This is a documentation-only clarification; no functional claim or gate status changes. No named human owner recorded. Next action: define a canonical wire-digest contract before real integration (same dependency as R-02).
- S14-R03: reusable synthetic dispatch coordinator over the existing SQL ledger and `ReferenceWriter`. The design is limited to sequencing already-issued IDs, canonical-byte verification, and clone receipt persistence; it does not issue authorization or resolve unknown outcomes. Contract: `S14_SYNTHETIC_DISPATCH_ADAPTER_2026-10-15.md`. State: IMPLEMENTED AND PUSHED as a non-gating prototype; functional 7/7 and PostgreSQL 16 E2E 18/18 on rerun; post-write uncertainty and cancellation propagation are fixed and tested. Independent reviews found no BLOCKER/MAJOR. GPT-PM approved exact HEAD `f13e32026737a02bf1bee5e3b86dd91ba4b167ea` (request `c6f839b8-0a67-4a32-a84b-7b7051034fc1`); push to `origin/main` verified. Real 1C qualification and release gates remain separate and unchanged.
