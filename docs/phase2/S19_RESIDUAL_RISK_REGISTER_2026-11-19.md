# S19 residual-risk register — 2026-11-19

Status: **working snapshot, not final acceptance evidence**. The history below preserves an earlier
snapshot; the current index refresh is recorded at the end of this register. This register reflects
the plan, formal gate manifest, task ledger, committed S19 candidate `e464d135e89eda9ca975231b4f51b43d8d019ab8`
and named sprint-end runs (2026-11-19). At that exact HEAD the two named Python files reported
`45 passed in 1436.42s (0:23:56)` and the E46 fixture runner reported 87/87 asserted fixtures
passed with two separate probes. The refreshed exact-head index was committed as `5f50fbe8`; it
records committed inputs from source HEAD `be938cd008b155fc72f032a0a371e1f83157fa81`, including
those run records and the explicit `NOT_RUN` runtime-boundary set. The fix-only code review is
accepted; exact-head GPT-PM approval remains pending. No exact-head S19 I1-I15 runtime-boundary
results have been adjudicated. G8/C1 are not passed by these synthetic runs.

The final S19 code review raised a MAJOR scope-clarity finding: per-invariant PASS claims could be
read as execution coverage for all scenarios and lanes. The checker change makes the scope
machine-readable (`I1-I15 only`), reports scenario/lane coverage as `NOT_ADJUDICATED`, and sets
`g8_evidence=false`. The assigned functional-test-reviewer ran only
`.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s19_invariant_matrix.py` against the
working tree based on unchanged HEAD `37d094571181912bf5983170ac2e130db2a2dfd6`; exit 0,
`36 passed in 1422.09s (0:23:42)`. The output is retained at
`reports/evidence/sprints/S19_MATRIX_FIX_TEST_ff3779f9.txt`. Fix-only code review accepted
commit `ff3779f9c9dddad883c7e247dec76a8636f094ac` with zero findings. This is a pre-commit
named-file result, not exact-head I1-I15 lane evidence. The finding does not change the formal
G8 state or the exact-head runtime `NOT_RUN` status. GPT-PM approval remains pending.

## Index snapshots

The previous working exact-head index was regenerated from committed source HEAD
`be2cbb32c52e08acd8ea8f2a10fd6a08884fd1e2` after adding the S19-03 scope-fix test output. It binds
that output at `reports/evidence/sprints/S19_MATRIX_FIX_TEST_ff3779f9.txt` (SHA-256
`4850a37b8681282e1104dfd7e9668cb9eb6f442240389b7b0bec48aad589dff0`). The index still records
I1-I15 runtime-boundary results as `NOT_RUN`, assessment `INDEX_ONLY_UNVERIFIED`, and authorization
`NONE`. Artifact hashes are recorded claims awaiting review; they do not adjudicate evidence
contents.

An interim index was generated from committed source HEAD
`1a607529d4f5f25409d2cfa001324a0c7eded415`; it binds the register snapshot from that commit and the
scope-fix output. Its file SHA-256 was
`5d63d8e2a5229fba544b78d7479df35584650d4dd0bbf07441ca355a17b87380`. This register revision is
newer than that selected snapshot, so the index must be rebuilt after this revision is committed.
The indexed runtime status remains `NOT_RUN`, assessment `INDEX_ONLY_UNVERIFIED`, and authorization
`NONE`. Exact-head GPT-PM review is pending; no G8/C1, release, or production status changes.

`NOT_RUN` means the required evidence has not been observed. It is not a pass or a claim that the
system failed. Synthetic checker/fixture tests do not constitute real 1C boundary evidence. A
bounded project-ledger acceptance is not a formal gate pass or production approval.

## Residuals

| ID | Area and factual status | Evidence boundary / missing evidence | Owner | Next action |
|---|---|---|---|---|
| R-S17-06 | `PARTIAL`: H3 invoice measurement remains open. | The approved set requires N=30 and the frozen corrected-material-field rule; caller-constructed rows or synthetic calculations do not establish a trusted test-lane receipt. No qualifying N=30 receipt is recorded here. | Codex coordinates the evidence contract; no human accountant/evaluation-set owner is assigned in the project records. | At final acceptance, obtain a frozen, hashed N=30 set and trusted run receipt; apply the frozen H3 rule and retain human review of material fields. Until then keep `PARTIAL`. |
| R-S18-SLO | `NOT_RUN`: all nine measured SLO objectives in the S18 table remain unmeasured. | Contract targets and synthetic state-transition tests are not workload measurements. | Codex maintains the record; no operational workload owner is assigned. | Run each objective only on an approved named lane with exact head, run ID, workload, sample count and calculation; otherwise retain `NOT_RUN`. |
| R-S18-RESTART | `PARTIAL` evidence only: two disposable-PostgreSQL startup-recovery cases passed in their recorded runs; OS process restart, COM/1C continuity and other crash windows remain `NOT_RUN`. | The existing tests cover bounded database state transitions, not a Windows service/process restart or a live 1C session. | Codex and the designated test roles for synthetic lanes; no licensed runtime/host owner is assigned. | Keep forced termination disabled until CT14 qualifies the exact channel/base. Record OS/COM cases `NOT_RUN` until run on that lane. |
| R-S18-ALERT | `NOT_RUN`: independent human alert receipt and operational triage time are unmeasured. | A test sink or local log is not an independently acknowledged human alert. | No target operations owner or real recipient is assigned. | Assign and qualify an independent recipient and test lane before recording receipt or triage evidence. |
| R-S18-RIGHTS | `NOT_RUN`: no authenticated current 1C rights source or deployed periodic reader is evidenced. | The repository contains a comparison contract, not proof of current live rights, authenticated completeness, or scheduled execution. | Codex owns the contract; no human 1C rights-source owner is assigned. | Qualify the read-only source, identity, completeness/provenance and schedule; until then make no current-rights claim. |
| R-CT14 / S14 | `NOT_RUN` for production-class COM writer qualification, marker behavior and least-privilege account. | S14's synthetic SQL dispatch adapter is not an operational COM writer. The actual licensed channel and its owner are not recorded. | No licensed-clone/channel owner is assigned. | Preserve the local protocol boundary; require CT14-qualified licensed-lane evidence before any S14 production-class claim. |
| R-S16-04 | `PARTIAL` in the project ledger: production-class private-network ingress has not been independently established. | Local policy and synthetic tests do not prove deployed routing, proxy/redirect resistance, or production network isolation. | Codex owns implementation evidence; no deployment/network operator is assigned. | Capture exact deployed topology and negative ingress evidence on the authorized lane; otherwise retain `PARTIAL`. |
| R-FORMAL-S12-S13 | Formal gate manifest remains behind bounded project-task records: S12 is `IN_PROGRESS`; S13 is `NOT_STARTED`; neither state is promoted by source or bounded sprint closure alone. | Current `GATE_MANIFEST.json` is authoritative for formal gates and retains missing exact-head evidence. | Codex reconciles evidence; specialist/test owners provide lane evidence as assigned. | Reconcile each required artifact against the manifest contract. Do not change manifest status until exact-head evidence and required approval exist. |
| R-G1-G7 | G1–G7 are `NOT_PASSED`; external evidence is `OPEN`; production authorization is `NONE`. This includes accountant attestation, UAT, operational readiness, canary and release. G4 also remains `NOT_PASSED` even when Drive intake is disabled. | No S19 engineering artifact passes these independent gates. The canary recipe below is preparation only. | Gate-specific human owners are not assigned in the manifest; operator alone owns a production-canary signature and production authorization. | Keep every gate state unchanged until its own evidence and authority are supplied. Never infer G1–G7 from C1. |
| R-S19-VERIFY | At `e464d135`, the sprint-end command `.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s19_exact_head_manifest.py tests/phase2/test_s19_invariant_matrix.py` returned `45 passed in 1436.42s (0:23:56)`, exit 0. At the same HEAD, `node tests/gate_manifest/run_fixtures.mjs` returned `Suite: PASS (87/87 asserted fixtures passed, 2 probes)`, exit 0. After the scope-clarity fix, the assigned functional-test-reviewer ran only `.venv\Scripts\python.exe -m pytest -q tests/phase2/test_s19_invariant_matrix.py` on the working tree based on unchanged HEAD `37d094571181912bf5983170ac2e130db2a2dfd6`: 36 passed in 1422.09s, exit 0; output is retained in `reports/evidence/sprints/S19_MATRIX_FIX_TEST_ff3779f9.txt`. Fix-only code review accepted commit `ff3779f9c9dddad883c7e247dec76a8636f094ac` with zero findings. Full earlier outputs are retained as `reports/evidence/sprints/S19_PYTHON_SPRINT_TESTS_e464d135.txt` and `reports/evidence/sprints/S19_E46_FIXTURE_RUN_e464d135.log`; the refreshed index must bind the current committed inputs and new run record. Exact-head GPT-PM approval remains pending. | These runs prove the named synthetic manifest/checker contract and static schema-2 fixture cases only. They do not provide adjudicated runtime results for I1-I15; every exact-head invariant result remains `NOT_RUN`. The index remains `INDEX_ONLY_UNVERIFIED` and carries no gate or production authority. | Codex prepares; `functional-test-reviewer` and `e2e-runner` own the named runs; code-reviewer accepted the scoped fix; GPT-PM owns the final exact-head approval. | Refresh S19-01's committed index against the candidate containing the final evidence records; request exact-head GPT-PM approval. Preserve all missing lanes as `NOT_RUN`. |
| R-MUTATION | Mutation testing is `NOT_RUN` under the operator's ban on mutation runs. Ordinary positive/negative tests and review are not reported as mutant-kill evidence. | No claim of measured mutation score or full guard mutation coverage is made. | Codex records the boundary; test execution rules are operator-controlled. | Retain this limitation explicitly. Do not run mutation tooling or substitute a test pass label for mutation evidence. |

## Invariant evidence at the current S19 head

The structural matrix maps all I1–I15 to scenarios, but no exact-head boundary-results artifact
has been adjudicated at the snapshot above. Therefore each invariant is `NOT_RUN` for S19's
exact-head evidence requirement until a passing, digest-bound result is recorded. The S11 design
package identifies the following lane gaps; these are requirements to reconcile, not claims that
old bounded tests never passed:

| Invariant | Remaining lane evidence called out by the canonical test design | S19 exact-head state | Owner / next action |
|---|---|---|---|
| I1 read/write identity | 1C-side least-privilege denial of payment/delete operations is not established by gateway token tests. | `NOT_RUN` | Codex reconcile the approved custom-role/rights artifact; licensed 1C owner is unassigned. |
| I2 typed catalogue | Clone before/after snapshot for the negative data-level control is not attached to S19. | `NOT_RUN` | Codex bind exact clone evidence or retain `NOT_RUN`; lane owner unassigned. |
| I3 approval/version binding | Real database and 1C race windows at claim, pre-effect and while a write is running need exact evidence. | `NOT_RUN` | Codex map only existing exact-head race evidence; qualified lane owner unassigned. |
| I4 separate approver | Direct-call, distinct-person identity and role-revocation-at-effect evidence must be reconciled; absence of a model-facing approve tool alone is insufficient. | `NOT_RUN` | Codex reconcile the exact test-IdP evidence; identity owner unassigned. |
| I5 anchored audit | Independent external checkpoint trust boundary and old-valid-copy/restore behavior are not proved by a database-local chain. | `NOT_RUN` | Codex reconcile anchor-provider and restore evidence; provider/key-custody owner unassigned. |
| I6 draft/post/unpost | Dependent-document and closed-period unpost refusal, plus exact empty-movement controls, need evidence for the supported shape. | `NOT_RUN` | Codex reconcile approved disposable-clone fixtures; licensed clone owner unassigned. |
| I7 idempotent unknown outcome | Fault-after-commit, retry/parallel execution and independent 1C resolution evidence require the qualified writer/read boundary. | `NOT_RUN` | Codex reconcile existing bounded evidence; COM lane owner unassigned. |
| I8 files remain data | Host-level memory/process isolation is not established by parser tests or sandbox observation alone. | `NOT_RUN` | Codex reconcile the exact host-isolation contract; Windows lane owner unassigned. |
| I9 budget and kill switch | Exact-head multi-process database budget races and unknown in-flight COM behavior need their mapped lane evidence. | `NOT_RUN` | Codex reconcile named lane outputs; database/runtime owner unassigned. |
| I10 no excluded effects | Register and payment-document scans establish only the measured purchase-receipt shape; other operation shapes remain outside evidence. | `NOT_RUN` | Keep the catalogue narrow and identify any newly qualified shape before testing; source owner unassigned. |
| I11 verified success | Independent accountant oracle for additional currencies, rounding and movement shapes is not established by structural or six-field matching. | `NOT_RUN` | Codex reconcile exact read-back and accountant evidence; accountant owner unassigned. |
| I12 authenticated target | Production/clone fingerprint and restored-epoch refusal across distinct real bases are not established by labels/configuration. | `NOT_RUN` | Codex reconcile authenticated base evidence; licensed-base owner unassigned. |
| I13 secret handling | Repository scans are only complementary evidence; live rotation/revocation against the actual 1C/IdP service is not attached. | `NOT_RUN` | Codex reconcile protected-store and live rotation receipts; secret-provider owner unassigned. |
| I14 no indirect public route | Deployment-layer host enumeration, proxy/redirect and SSRF denial remain unmeasured in the deployed topology. | `NOT_RUN` | Codex reconcile deployment evidence; network/deployment owner unassigned. |
| I15 immutable scope | The exact two-company/two-base fixture and persisted queue-scope tamper refusal are not attached to S19. | `NOT_RUN` | Codex reconcile the scoped lane evidence; tenant/base fixture owner unassigned. |

## Formal-state snapshot

At the source snapshot used above, G0 is `PASSED` with production authorization `NONE`. G1 is
`IN_PROGRESS` and `NOT_PASSED`; G2, G3, G4, G5, G6-pre, G6 and G7 are `NOT_STARTED` and
`NOT_PASSED`; G8 is `IN_PROGRESS` and `NOT_PASSED`. External evidence is `OPEN` for G1–G8.
Formal manifest nodes S12 and S13–S19 are not promoted by the bounded task ledger. Re-read the
manifest at final S19 close because this table is a dated snapshot, not a live view.

## Acceptance update rule

After S19 tests and review, append exact run/HEAD/owner evidence to this file. Keep every unavailable
lane `NOT_RUN`, preserve `PARTIAL` where criteria remain unmet, and use `owner not assigned` where
the records contain no human owner. Only update the formal manifest through its validated,
authorized process; this residual register itself changes no gate or production state.

## Sources

- `governance/GATE_MANIFEST.json` — formal gate/node states and production authorization.
- `.harness/ledger.json` and `PROJECT_PLAN.md` — bounded project-task states.
- `docs/sdlc/next-sprint-preparation.md` — S17–S19 acceptance and residual contract.
- `docs/phase2/S14-S19_SPRINT_PLANS_AND_ACCEPTANCE_MAP_2026-10-17.md` — sprint boundaries and owners.
- `docs/phase2/S18_SLO_AND_FAILURE_TABLE.md` — measured-vs-`NOT_RUN` S18 evidence.
- `docs/phase2/S11_SCOPE_DECISIONS_AND_GATE_MANIFEST_2026-10-12.md` — frozen H3 criteria.
