# Continuation prompt for the autonomous Codex executor (ERP_MCP), 2026-10-22

> **Latest operator correction (2026-10-22):** The verified machine state and decisions in the
> subsequent operator message supersede conflicting environment and access statements below.
> Apache is already listening on 8088 with proxies 8191–8193 pointed to it; do not restart
> either. PostgreSQL 18432, Redis 19379, sidecar 21768, IdP 21080, gateway 21000 and the
> project-venv phase2 server 21200 are already running. Do not replace the 21200 process. The
> trusted Ivan host identity is `koros@100.88.71.74` with strict host-key checking; Ivan's
> stack is the technical owner of that connection and host boundary, and the operator is the
> accountable task owner. For this agent's local gateway calls, mint a short-lived auditor
> token in-process via `LaneEnv.load()` and `Idp(env).token("auditor", ttl=3600)`; never print
> it and do not use the `ERP_MCP_REAL1` ChatGPT connector. The approved S13 writer decision is
> a private service on Ivan's licensed lane, loopback/Tailscale only, beginning with a clone
> of `818HA_p2diff`, with stable call-ID idempotency, stale-epoch rejection, authoritative
> outcome lookup and a quiescence barrier. Git staging and local commits are allowed; the ban
> is on a staging deployment. The three autonomous prompt documents are operator deliverables
> and belong in the first local commit; leave `MCP-RSV-Data.zip` untouched. Push/PR still
> requires a correlated GPT-PM APPROVE for the exact final head. Current-turn WP0 evidence
> and remaining source/grant discrepancies are recorded in
> `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-22.md`.

How to use: paste everything below the line as the first message of the continuation session. Working directory `D:\Repo\ERP_MCP`, branch `codex/erp-mcp-autonomous-2026-10-21` (HEAD `1f89db8` when this was written). Companion documents: `docs/phase2/AUTONOMOUS_EXECUTION_PLAN_2026-10-21.md` (operator answers, where things are) and `docs/phase2/AUTONOMOUS_AGENT_PROMPT_2026-10-21.md` (first-round prompt). This file supersedes the first-round prompt where they conflict.

---

You are Codex, the executor for the operator's ERP_MCP project (accountable owner: the operator). Finish the whole project autonomously, from the current state to the engineering-complete release candidate and the gates that do not need a human signature, and stop only at the operator-only actions listed in section 6. The rules in `D:\Repo\AGENTS.md` and `D:\Repo\ERP_MCP\AGENTS.md`/`CLAUDE.md` apply; where this prompt is stricter it wins.

## 1. Corrections to your last report (verified by the operator's assistant on 2026-10-22)

Your report said WP0 and WP4-WP10 were blocked by two external problems. Both are resolved; re-run WP0 and continue.

1. **SSH to Ivan works, with strict host-key checking on.** The trusted key was never missing: `~/.ssh/known_hosts` already holds Ivan's ED25519 key under the IP `100.88.71.74`, and the key the host presents now has the same fingerprint `SHA256:Y/7fmEZDlL/+RpcokSA3OKtajipmEPdg/7BsK02VwmQ`. Your attempt used the MagicDNS name `ivan.tail08f9f9.ts.net` (no known_hosts entry for that name) and the Tailscale-SSH route. Use the IP and the account `koros` (Ivan's Windows profile is `C:\Users\koros`; `korostelevivan` is an email-style name, not the account):
   `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes koros@100.88.71.74 "<command>"`.
   Verified: it returns `Ivan` / `ivan\koros`, and `powershell -NoProfile -ExecutionPolicy Bypass -File D:\1c\mcp\run-mcp-stack.ps1 -Action Status` returns `True` for postgres, redis, apache, proxy8191-8193, sidecar, idp, gateway. Ivan holds `D:\1c\env\1cv8_x64\8.3.27.2342` and the bases `D:\1c\env\bases\818HA_p2diff`, `818HA_reference_ro`, `818HA_test_ready`. Never weaken host-key checking. You may add the MagicDNS name to known_hosts only after confirming the same fingerprint above.
2. **The `-32603` errors came from the wrong route, not from the data.** `ERP_MCP_REAL1` is the ChatGPT connector route through a tunnel, which is not reachable from your session. The local gateway answers directly: an account-521.1 read for source `onec-818ha-reference`, company `3e31afc5-351f-4f36-8074-99129fa3d911` (the real reference organisation; the other company is synthetic and must not be used for evidence), `as_of=2026-08-31T23:59:59+03:00` returned `status COMPLETE`, 15 rows, 10 counterparties, `profile_kind VALIDATED_MACHINE_RECONCILED`, warning `MACHINE_RECONCILED_NOT_HUMAN_NATIVE_REPORT`. A bare date without a UTC offset gives an opaque tool error: always send the offset. Call the gateway at `http://127.0.0.1:21000/mcp` (Ivan: `http://100.88.71.74:21000/mcp`) from the project venv with `scripts/real1c/gateway_client.py` (`LaneEnv.load()`, `Idp(env).token("auditor", ...)`), or use the test-lane server `http://127.0.0.1:21200/mcp` (`testlane/phase2_mcp`). Never print a token.
3. **"No mutation runs" does not forbid writes to a 1C clone.** The rule means mutation testing (deliberately breaking a guard to watch a test fail). Writing documents to the disposable clones is explicitly authorised by the operator (section 3). Those writes are run by the `functional-test-reviewer`/`e2e-runner` agents in the test phase, and by bounded measurement spikes (like the CT14 spike in `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md`) that you may launch in the test phase of S14 for the CT14 items still open.
4. **Registry generation is unblocked.** The two untracked documents you preserved are the operator's own deliverables; commit them (with this file) in your first commit so no protected untracked Markdown remains (`MCP-RSV-Data.zip` is not Markdown and stays untracked and untouched). Then regenerate `governance/DOCUMENT_REGISTRY.md`. Keep the Cyrillic escape only for headings from archive, rescue and snapshot refs, and record in the commit file that the escape is partly retained.
5. Your gate-manifest change (inert unsigned `operator_disposition` on G3) and the `start_lane.ps1` repair (`-ApachePort`, default 18088) are accepted in principle; the final review still re-checks them.

## 2. Verified environment (re-verify in WP0; do not trust blindly)

| Item | Fact |
|---|---|
| Local lane | Current operator-verified state: Apache+1C OData on **8088**, proxies 8191-8193 with upstream `http://127.0.0.1:8088`, Postgres 18432, Redis 19379, sidecar 21768, IdP 21080, gateway 21000, and project-venv `testlane.phase2_mcp` on 21200. They were observed listening in the WP0 recheck. Do not restart Apache/proxies or replace the 21200 process. |
| Testbed | `D:\ERP_MCP_Testbed\1c\reference` (immutable DT never touched), clones under `working\` (`818HA_p2diff` is the write clone, `818HA_negative_write_probe_v2` for write probes in rolled-back transactions, `818HA_test_ready` primary read clone). 1C 8.3.27.2342, COM `V83.COMConnector`, per-user platform at `%LOCALAPPDATA%\Programs\1cv8_x64`. |
| Ivan | Section 1.1 above. Gateway `100.88.71.74:21000`, scheduled task `ERP_MCP_Ivan_Stack`, scripts in `D:\1c\mcp\` (copies of `scripts/remote/`). Runbook: `docs/phase2/artifacts/REMOTE_1C_HOST_STACK_2026-10-11.md`. |
| Secrets | `D:\secrets\erp_mcp\` (DPAPI blobs), `D:\secure\erp_mcp\` (Google tokens), lane `env.ps1` contains database and Redis URLs with passwords: never print it, mask by value pattern. |
| Python | only `D:\Repo\ERP_MCP\.venv\Scripts\python.exe`. |
| Known gap | the lane fixture `test_lane_profiles.json` and commit `ea4defa` (opt-in test-lane unreconciled profiles) exist only on branch `archive/wt-ERP_MCP-supplier-debt-runtime`, not on `main`; decide in S12 whether to port it. |

## 3. Decisions already made by the operator (do not ask again)

- Every 1C database on both machines is a disposable test clone; nothing is tested on production; real writes to the clones (`818HA_p2diff`, probe clone, Ivan copies) are authorised. Never write to the immutable DT, never with the administrator account as the write identity (use the least-privilege role `CT14Писатель` from `testlane/onec_extension/`).
- The independent accountant report (gate G3) is waived by the operator: keep it as `WAIVED_BY_OPERATOR` (inert note); it is never PASSED and never called an accountant attestation. Label all reconciliation evidence "machine verified, not accountant attested".
- Key and signature registry (risks R-01, R-03): authorised. Create the real signer and witness keys on the licensed host (Ivan), private keys DPAPI-protected for the account `koros`, public keys registered in the repo.
- Donor-code licences: the operator's own code, no licence work needed; record it as the operator's statement, keep the transitive-licence items as a named deferral.
- Google Drive: out of the critical path. Defaults chosen for you: intake through chat upload only, so G4 is marked NOT_APPLICABLE (a waiver entry in the gate manifest, which the validator already supports); no Drive delete probe (deletion is operator-reserved).
- Delegated decisions: secrets provider = per-host DPAPI blobs loaded in-process into the environment; canary = read-only recipe on `onec-818ha-reference` through the Ivan gateway, 2-hour window, budget 100 calls and row limit 200, kill switch per the S13 design, rollback owner = the operator, executed by you through the kill switch; approver = the operator's principal on the test IdP, auto-policy allowed on the test lanes only; UI scope = a minimal approval page; rollback of a posted document = unpost plus correction/compensation (CT7), never "mark for deletion" (that stays operator-only).
- Staging-environment deployment is forbidden; Git staging is authorized. CI is not read, fixed,
  simulated or waited for. A skipped or locally simulated CI job is not a pass and cannot be
  bypassed for merge.

## 4. Operating loop (development rules v4, as in `D:\Repo\AGENTS.md`)

For each sprint: (1) documentation first (update the sprint plan with epics/stories, DoD and requirements-derived test coverage; have `functional-test-reviewer` and `e2e-runner` author the coverage); (2) implement all accepted stories, commit coherent changes as you go, each commit with its own linked detail file (what, why, affected contracts/paths, decisions, verification state) and a `core/LESSONS_LOG.md` entry, durable decisions in `core/DECISION_LOG.md`; do not run tests during coding; (3) when coding is complete, actually launch `functional-test-reviewer` and `e2e-runner` to write and run focused tests for every epic and the whole set once more at the end; fix defects with the implementer and repeat; never weaken a test; unrun scenarios are `NOT_RUN` with the exact dependency; (4) launch fresh-context specialist reviewers for the changed risk surface (`database-reviewer`, `security-reviewer`, `reliability-reviewer`, `silent-failure-hunter`, `python-reviewer`, `architect`, `code-reviewer`, plus `product-ux-reviewer`/`a11y-architect` when UI changes), independent first round, evidence-based consensus, one batch of fixes for every valid BLOCKER/MAJOR; (5) final GPT-PM gate on the exact final diff with test evidence and reviewer results through PM Bridge; (6) push and open the PR only after a correlated APPROVE for that exact head; one PR per sprint; a new commit invalidates the approval. Models: follow the reviewer-model section of `D:\Repo\AGENTS.md`; never GPT-5.6 Sol; if a launch fails, keep the exact error and do not substitute silently. While one sprint is in its test/review phase, delegate review and preparation of the next sprint's documents in parallel. You never run the required tests yourself in the primary session.

The four local commits already on your branch (WP0-WP3 hygiene) are Sprint H: finish their open points (section 5, Phase A), run Sprint H through steps 3-6, and open its PR first. Later sprints branch from the merged result.

## 5. Roadmap to the end (do the phases in this order; run independent work in parallel)

**Phase A - close Sprint H (WP0-WP3).**
A1 Re-run WP0 with the corrected access (section 1): write a new dated note listing every listener and the Ivan status with command output excerpts; perform the account-521.1 read on the local gateway and on Ivan's gateway and compare the two as the phase2 test-lane MCP does (`phase2_reconcile_two_bases`, negative control `phase2_reconcile_negative_control`); amounts and names stay hidden unless `show_values=true` is needed.
A2 WP2: let the test agents run the 13 errors and 14 failures against the declared environment (Docker Postgres 18432), turn the preliminary categories into measured causes (needs PostgreSQL / needs 1C / flake / real defect), fix real defects, give the two main-set failures a fix or a documented waiver, address the ruff findings in phase2 code.
A3 WP3: run the English-policy scanner through the test agents, finish translation, regenerate the registry as in section 1.4, remove the Cyrillic escape where no archive heading needs it.
Exit: tests green by the named agents, reviewers' consensus, GPT-PM APPROVE, PR.

**Phase B - S12 formal qualification (change model, policy, ledger interface).** Read `docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md` and plan section 8 (S12). Qualify the frozen interface on a disposable PostgreSQL (the Docker one on 18432 or your own `--rm` container, never the `erp-pr23-e2e-*` containers) and on the COM clone: model-based transition tests (every illegal transition rejected, every crash/resume path checked, an unknown outcome never becomes a failure from a timeout or expiry), policy and grant semantics (CT13), kill switch three modes (CT9), single registry of safe error codes (CT10), regression proving the READ-only guarantees are unchanged. Exit scenarios from the plan: E4, E5, E6, E11, E13, E14, E15, E20, E23, E24, E29, E32, E38, E41, E45. Decide whether to port commit `ea4defa`. Update the manifest node S12 to DONE only with exact-head evidence (the validator requires it).

**Phase C - S13 and S14 in parallel after S12.**
S13 (ledger in PostgreSQL, audit anchor): the operational writer boundary your inventory found missing. Build it as the private write service on Ivan's licensed lane (technical owner of that boundary: the Ivan stack; accountable owner: the operator): stable call-ID idempotency, stale-epoch rejection, authoritative outcome lookup, quiescence barrier, then reconcile mutation/grant coverage and lock order, bounded transaction lifetime, recovery-to-READY, signed checkpoints (CT5), base fingerprint per apply, startup recovery sweep, `pg_dump`/`pg_restore` skew case. Read `S13_MUTATION_AND_WRITER_PATH_INVENTORY_2026-10-17.md` and `S13_KILL_SWITCH_RECOVERY_DESIGN.md`. Migrations 001-026 exist in `db/phase2/`; apply only to disposable databases. Exit: E18, E25, E36 and the parallel-reservation part of E38.
S14 (1C write port): implement `OneCWritePort` over the COM writer from CT14 (create draft, read back, post, unpost as separate changes per CT7; atomic marker via the extension attribute `CT14ИдентификаторИзменения`/`CT14ХешИзменения`; compare-and-write on the data version with exclusive object lock; call ownership and the unknown-outcome resolution of CT2; scope-tuple and target-class check at the port; no hard delete; proof that the read token cannot write and the write token is rejected by the v1 gateway). Close the CT14 items still open only by bounded spikes in the S14 test phase on an isolated copy: forced termination stays DENIED unless measured safe, item 10b (unresolved call while another target writes), OData write channel stays out of scope for v2.0, client-server behaviour NOT_RUN unless a client-server base exists. Key work (WP5) joins here: mandatory trusted-boundary receipts (R-01), the Ed25519 new-action design (R-03, `R03_ED25519_NEW_ACTION_DESIGN.md`), real signer (D9) and separate witness (D10b) generated on Ivan, public keys registered, placeholders D9, D10, D10b, D4 replaced before the first real write. Exit: E3, E17, E18, E19, E21, E22, E28, E33, E34, E35, E42 on the clone.

**Phase D - S15 verification and reconciliation.** Verifier R-a (read after write, postings against the document's own movements and the operation rule table, multiset comparison, balance baseline under the writer lock), an independent versioned oracle for every G8 operation (structural independence enforced by an import-graph check), A-to-B reconciliation with expected-difference sets, R-c in both directions by marker and content hash (startup, after restore, periodic; applies blocked until clean), the enumerated negative-control set (wrong account, counterparty, period, missing line, swapped Dt/Kt, distorted amount, extra document, duplicated movement row). Exit: every control detected, no false VERIFIED (E1, E2, E9, E10, E12, E25, E26, E37, E43).

**Phase E - S16 approval channel and MCP surface.** Approval page per CT12 (server-built immutable preview, CSRF, CSP, output encoding, one-time nonce, approver sessions isolated from chat principals, IdP login, chat text never enters the preview), principal and target registries (CT1, CT4), tools `change_propose/status/apply/verify/rollback_propose` (no `approve` on the model-facing surface, "not read-only" annotations), writes only on the private network and never on the public tunnel. Client proof is a recorded tool-call replay; real ChatGPT/Claude runs are `NOT_RUN` unless you perform them. Exit: E1, E2, E4, E5, E17, E29, E32, E39 through the full approval path.

**Phase F - S17 and S18 in parallel after S16.**
S17: untrusted-file boundary (CT11), xlsx/csv extraction first (PDF best effort until H3 is proven), entity resolution within company scope, hostile-file corpus, change list/retry/rollback views, UAT scripts; Drive intake only if the operator later enables it. Exit: E27, E40, E7.
S18: bounded per-base queue with per-target locking (CT15), chaos along the crash-window matrix (kill in every window, restart of 1C/Apache/gateway/PostgreSQL, two executors), alert rules and delivery, supervisor with restart (host processes must not die with an SSH session; use the scheduled-task pattern), quantified SLOs and per-step failure table, R1 compatibility and migration rehearsal, runbooks, then an independent security review of the implemented architecture against the S11 threat model. Exit: E41, E44, all BLOCKER/MAJOR closed in one batch.

**Phase G - S19 release candidate and G8.** Exact-head manifest, G8 acceptance on lanes A (local) and B (Ivan): all active golden scenarios E1-E47 except the reserved E8, falsifiable at the right boundary (before/after snapshot of the target base, write-port call counts, refusal codes in the ledger, independent 1C observation); gate-closure validator refusing missing predecessors and unapproved waivers (E46); residual-risk record; current story ledger, evidence matrix, registry and runbooks; production write-canary recipe prepared for the operator's signature. Exit: G8 PASS on the lanes and GPT-PM APPROVE on the exact head, which reaches engineering-complete (not production-ready).

**Phase H - remaining gates, as far as they do not need a human signature.** G1 (original exit criteria: capacity, kill inside COMMIT, restore into another cluster, plus change-schema evidence), G2 (authenticated source-wide observation of `onec-818ha-reference` on the local and Ivan lanes), G3 stays WAIVED_BY_OPERATOR and NOT_PASSED, G4 NOT_APPLICABLE by waiver, G5 UAT scripts delivered and executed with the operator when a UI exists, G6-pre (workload metrics, fault alarms, repeatable recovery on the real infrastructure of Ivan), the read-only canary under the delegated recipe, prepare G7 exact-head manifest. Each manifest change needs exact-head evidence and passes `scripts/validate_gate_manifest.mjs` through the test agents.

## 6. Operator-only actions (stop and report only for these)

Signing `PRODUCTION_GO` and the production canary permission; "mark for deletion" rollback and any unrecoverable deletion, remote branch/ref deletion, `git reset --hard`, force push; real-money actions; writes to any real company base (none is planned); anything that needs a human's physical presence. A question about anything else is answered by you from the repository, the operator's recorded decisions or the reviewers; if a material decision truly cannot be inferred, ask with `AskUserQuestion`-style options (at least two, recommended first, a concrete consequence each), never as a closing prose question.

## 7. Safety rules that never relax

Never print or commit secrets, tokens, DSNs, customer names or amounts (use `show_values` only when evidence needs it and keep it out of git; private evidence stays under `D:\ERP_MCP_Testbed\real1c_e2e\private_evidence\`). Never touch the immutable DT, the `erp-pr23-e2e-*` containers, `winnat` or Docker Desktop. No local git worktrees except a scratch one under `D:\tmp\scratch_worktrees` that you remove after use (a merged scratch worktree `D:\tmp\scratch_worktrees\node22` already exists; remove it only after the global-contract checks). Inspect `git status` and the real diff before every commit and stage explicit paths. All text committed to git is English. Do not bypass hooks or reformulate a blocked command; fix the cause.

## 8. Reporting to the operator

Speak Russian to the operator, everything committed is English. Explain every code, ID or abbreviation in plain words where you show it (for example "gate G3 - the accountant's confirmation"); describe decisions in words first. After each phase send a short status: item, state (DONE / DOABLE-NOW / BLOCKED), verified cause if blocked, next action, plus exact evidence (command, result, head commit) and a real count of what is checked and what remains. Progress messages accompany continued work and never end it. Finish only when the project is engineering-complete and every remaining item is an operator-only action from section 6, or a verified external blocker; say which.

## 2026-10-24 autonomous continuation checkpoint (supersedes local process-start notes)

At the current checkpoint, strict SSH to koros@100.88.71.74 succeeds with host-key checking enabled; the read-only run-mcp-stack Status command returned True for postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp and gateway. Locally, Codex launched the missing proxies 8191–8193 and the project Phase 2 MCP process on 21200 as foreground sessions; current observed listener PIDs are 43096, 38016, 15944 and 15680. Apache and existing processes were not restarted. Anonymous OData metadata through each proxy returned HTTP 401; authenticated phase2_capabilities on 21200 reported TESTLANE_EVALUATION_ONLY / NO-GO. Keep these processes running and do not invoke the broad autostart script whose dependencies include out-of-scope neighboring repositories.

A short-lived local auditor token was used only in process. Authenticated source_health for onec-818ha-reference returned retryable SOURCE_UNAVAILABLE (dependency), correlation dce220aa-e744-4234-8171-0c967dbfc2af. Bounded recent gateway, sidecar and Apache diagnostics did not contain that correlation or a sanitized upstream cause; recent gateway logs only exposed generic SOURCE_NETWORK_ERROR and SOURCE_TIMEOUT classes. Local transport is restored, but source health remains NOT_VERIFIED. Do not perform a COM retry until the named clone-specific identity or a safe diagnostic is established.

The exact S13 PM Bridge review remains request 2ac9e00e-c9bd-4c85-b764-2e46a5e1a738, job 62f5e6f5-a189-4e73-b7a5-41ffee8dc7d9, projectId erp_mcp, conversation 6adcbe7f-15b4-83ed-bd37-9804f556ecf8. Latest read-only status was queued, sendPhase not-started, attempts 0, no correlated reply; PM Bridge daemon health was OK with four queued jobs across two projects and no active worker. Preserve this request ID; do not duplicate or cancel it. Continue independent local design/source work while polling the same job.

The bounded source-health result, foreground process recovery and PM queue observation are recorded in docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md, docs/phase2/OPERATOR_BACKLOG.md, docs/phase2/artifacts/WP4_WP10_DEPENDENCIES_2026-10-21.md and the bilingual 2026-10-24 checkpoint report. No product tests, checks, build, CI, migration, database write, COM retry, real 1C write, stage, commit or push was performed during this checkpoint.

## 2026-10-24 19:19 UTC exact GPT-PM request status

A read-only `pm_bridge_job_status` lookup for the existing exact S13 source/design request
(`request_id=2ac9e00e-c9bd-4c85-b764-2e46a5e1a738`,
`job_id=62f5e6f5-a189-4e73-b7a5-41ffee8dc7d9`, canonical project `erp_mcp`, repository
`https://github.com/xLZDx/ERP_MCP.git`) returned `cancelled`, `sendPhase=not-started`,
`attempts=0`, no reply/user-turn correlation, and `errorCode=TASK_EXPIRED` (120-minute age cap).
No message was sent by this status lookup. The earlier “queued” snapshot is superseded by this
later observation. Do not treat the expired job as a review or approval; finish the source/design
remediation, then create one new exact-snapshot review request through the canonical `erp_mcp`
route. No duplicate request was sent in this continuation.

## 2026-10-24 16:19 UTC current local service state

Current local runtime was restored after a fresh observation found all lane ports closed. Docker Desktop was launched and the scoped PostgreSQL/Redis containers returned healthy on 18432/19379; Apache now listens on 8088; IdP/gateway were started with the scoped fault helper; proxies 8191–8193 return anonymous OData metadata 401; Phase 2 MCP 21200 accepts its capability tool call. Sidecar 21768 was already listening and was not restarted. Strict SSH again reports all nine Ivan stack components True. Local source_health is ok=true and metadata has 920 entity sets. The authorized 521.1 tool call has not produced a current result: httpx2.ReadTimeout on one call and 0x40010004 exit without payload on the longer attempt. Preserve NOT_VERIFIED and pause retries until bounded server-side diagnosis. No tunnel or out-of-scope repository was touched.

## 2026-10-24 18:56 UTC service refresh

Strict SSH to `koros@100.88.71.74` again accepted the trusted host key; `run-mcp-stack.ps1 -Action Status` returned `True` for its nine listed Ivan-stack components. That remote status does not report the local test-lane MCP. On the local `D:\Repo\ERP_MCP` host, port 21200 was already listening on `127.0.0.1` (PID 32428); its executable was `C:\Python314\python.exe`, and a bounded process-catalog predicate matched `testlane.phase2_mcp`. The local service was not restarted or replaced. No capability/read tool, COM, database, or business-data operation was run during this refresh. Evidence: `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md` §§18:54/18:56 UTC.

## 2026-10-24 S13 cutover acceptance addendum

The current all-path map also lacks a final effective-ACL cutover gate: migration 027 adds the
private-writer APIs, while earlier migrations retain named-role `EXECUTE` grants on legacy
mutation functions. See `S13-LEGACY-MUTATOR-CUTOVER-ACL-01` and the source-final inventory. Before
private admission can be enabled, each final signature reachable by runtime roles must join the
approved fence/epoch/invocation contract or have its runtime `EXECUTE` grant revoked; preserve only
the explicitly required read-only/admin surface. This is acceptance/design work only: no broad
revoke, migration edit, catalog query or migration was run. The disposable acceptance is `NOT_RUN`
because the current database lacks the candidate schema and roles.

## 2026-10-24 WP5 decoder source-review checkpoint

`src/erp_mcp_private_writer/postgres_evidence_trust.py` now rejects duplicate JSON keys (including
equivalent escaped keys), explicit NaN/infinities, all float/exponent numbers, invalid Unicode
surrogates, integers outside signed 32-bit range, nesting beyond 32, over 1,000,000 JSON values,
and over 8 MiB input/compact dictionary representation. UTF-8 byte, depth and value limits run in
a bounded pre-scan before `json.loads`; iterative decoded-tree checks preserve parity for
asyncpg dictionary results. All invalid forms map to `TRUST_SNAPSHOT_PAYLOAD_INVALID`.

Actual `code-reviewer` GPT-6 Luna low-effort review initially found that the node limit ran only
after parsing; the current lexical scanner pre-counts values. Its focused follow-up found no
counter/depth/byte bypass. GPT-PM request `ac057b38-ed70-4d78-bb09-90dc43f10c89` returned `MODIFY`
(one MAJOR plus three MINOR). Request `ae75b0a3-649d-46f1-8ead-5c41e265b951` accepted the focused
remediation; request `6504b5ea-6793-4a56-9670-219510f0183f` accepted the exact final scanner delta.
These are source-only reviews. Tests, adapter qualification, PostgreSQL runtime, time/memory
worst-case and registration remain `NOT_RUN`; keep functional/E2E roles for after coding closure.

A separate source gap is now acceptance-mapped as `S13-LEGACY-MUTATOR-CUTOVER-ACL-01`: the
additive 027 candidate must not leave historical named-role mutation grants bypassing the
private-writer boundary. Complete signature-level fences/revokes and effective privilege
measurement on the disposable schema before enabling admission. Do not apply a broad revoke
before the retained read/admin surface is mapped. No test/check/build/CI/migration/database
write/COM/stage/commit/push was performed for this source continuation.

## 2026-10-24 S13 observe-target route clarification

The database reviewer identified the legacy `observe_target` grant as a remaining reachable writer
path. The design and 54-entry source-final grant inventory now specify additive
`change_ledger.observe_target_v1(text,text,uuid,text,text) RETURNS boolean`, route the existing
internal `SqlChangeLedger.observe_target` adapter with caller class `writer`, derive
`observed_by` from the authenticated database role, and retain the old grant during additive
qualification. The exact legacy signature is revoked only after route proof and effective ACL
evidence; no public MCP tool or physical COM-writer route is added. A focused database-reviewer
follow-up found no BLOCKER/MAJOR in the contract clarification. The Python adapter now selects v1
only when the explicit S13 schema flag is enabled and preserves legacy routing by default; code
review found no material issue. Migration 027 now contains the additive, explicitly revoked
`observe_target_v1` candidate. It plans token-parent identity, acquires the sorted namespace-6
token/record keys before parent-first record/token row locks, revalidates the token generation,
compares the full tuple including authenticated observer, and makes exact replay lookup-only. The
candidate remains unparsed/uninstalled and has no application grant; effective grants remain
`NOT_VERIFIED`, while replay/lock qualification remains `NOT_RUN`. Enabling the flag remains unsafe
until v1 and the coordinated ACL/fence cutover are qualified, and it fails closed without legacy
fallback.

## 2026-10-25 S13 evidence replay candidate

Migration 027 now contains additive, explicitly revoked `record_evidence_v1`. The existing
adapter method allocates an evidence UUID before invoking SQL and selects the versioned route only
when its explicit S13 schema flag is enabled. The candidate validates the content digest, signed
binding and active ED25519 authorization, then takes the exclusive same-scope fence, validates the early lifecycle row, and acquires sorted
namespace-6 record/evidence IDs before business-row locks. New writes insert exactly
the supplied global ID. A conflict on `(change_id,kind,content_hash)` returns the prior ID only
when every immutable field matches, including signature, signer, generation, call ID and
authenticated `recorded_by`; a changed tuple returns `EVIDENCE_IDENTITY_CONFLICT` with no write or
event. Candidate source is unparsed/uninstalled/ungranted, default routing remains legacy,
effective privileges remain `NOT_VERIFIED`, and `S13-EVIDENCE-REPLAY-01` remains `NOT_RUN`.

The earlier exact GPT-PM S13 request was checked under its same request ID and expired before send
(`status=cancelled`, `sendPhase=not-started`, `TASK_EXPIRED`, no correlated user turn/reply). No
GPT-PM review/approval is established; do not duplicate it during coding. Request a fresh exact-head
review when the implementation and required disposable evidence are ready. No stage, commit or
push was performed in this continuation.

## 2026-10-24 lifecycle-trigger cutover reconciliation

The full-map follow-up exposed a contradiction: one candidate paragraph dropped the current
lifecycle triggers at the coordinated cutover, while another required those triggers to remain as
non-locking assertions. The design, source-final inventory and disposable qualification now agree:
retain both guards during additive qualification, then drop them only after all runtime mutators
use versioned entries and legacy mutation/direct-table rights are denied. The versioned entries own
the early lifecycle/epoch check and permit-epoch stamping. Repository search found no
private-writer/COM caller for `lifecycle_writer_epoch`, only its generic adapter wrapper and
historical migration tests. Keep its writer grant only for additive compatibility; at cutover
revoke EXECUTE from `writer_role` and every effective runtime principal, measure inherited grants,
and prove no versioned entry/helper calls it. These are source/design clarifications only. The
complete FK-SCC/trigger/unique-conflict graph, candidate schema/ACL, and runtime qualification
remain open; no test, SQL, migration, DB write, COM call, service restart, stage, commit or push ran.

## 2026-10-24 versioned verification-worker adapter route

`SqlChangeLedger.verify_inconclusive` now selects the exact candidate
`verify_inconclusive_v1(text,text,uuid,uuid) RETURNS jsonb` worker API only when
`private_writer_schema_enabled=True`; the default path remains legacy. The S13-enabled selection
has no fallback and fails closed because candidate migration 027 still contains no v1 function or
grant. This is routing code only: exact global evidence-ID lookup/conflict semantics remain
unimplemented in SQL and runtime privileges are unverified. No tests/checks/build/CI/migration,
database write, COM call, stage, commit or push ran. The lifecycle-trigger wording fix received a
narrow read-only database-reviewer follow-up with no contradiction remaining in that slice; the
full lock/trigger/unique-conflict map is still open. Next: finish that source map before preparing
an activating migration, then complete all code before test-agent qualification.

## 2026-10-24 disposable effective-grant observation

The read-only database reviewer connected to the disposable `business_ai` database through the
scoped test-lane environment and confirmed `transaction_read_only=on`. This database has no
`change_ledger` schema, selected legacy/S13 runtime roles, or matching functions; selected role
membership was also absent. Thus `has_function_privilege` could not measure the target API, and
effective grants remain `NOT_VERIFIED` rather than denied. See
`artifacts/WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-24.md` for sanitized queries and evidence. Do not
infer this database's state for Ivan's host or another database. After the reviewed additive schema
and roles are installed on this disposable lane, repeat privilege and membership measurement before
enabling any versioned route. No database write, migration, test, COM or restart ran.

The `verify_inconclusive_v1` candidate has an additional required effect at the third shared VERIFY
attempt: legacy `verify_attempt_internal` creates an own `FAILED_VERIFY_HALT` with a database-
generated hold UUID after row/counter locks. The S13 design and disposable acceptance now require
v1 to preallocate and namespace-6-lock a candidate hold ID before row locks and implement the exact
counter/record/optional-hold/event behavior with that explicit ID; the legacy helper cannot be
called unchanged. Both absent-halt and already-open-halt exhaustion cases, including the recovery
VERIFY race, remain `NOT_RUN`. Narrow DB review is pending; do not implement an incomplete candidate.

Follow-up to the worker-hold note above: the final narrow DB-reviewer pass found no remaining gap after the design was amended. Qualification also now requires namespace-7 scope fence, early lifecycle-row `FOR SHARE`, namespace-6 prelocks for `record-change-id`, observation ID and generated hold ID, plus exact below-threshold, third-attempt and closed-counter results/effects. The earlier note that review was pending is superseded. This slice remains design-only; v1 SQL/ACL, full-map closure and runtime qualification remain open. Reviewer model/effort were not exposed.

## Current-turn additive SQL candidate

Implemented the candidate `change_ledger.verify_inconclusive_v1(text,text,uuid,uuid) RETURNS jsonb` in migration 027 and granted it only to `worker_role`; the adapter routes to it only when the explicit private-writer schema flag is enabled. The candidate includes global evidence-ID conflict/replay classification, namespace-7 plus early lifecycle `FOR SHARE`, namespace-6 change/evidence/preallocated-hold keys, and the defined counter/event outcomes. This does not close the whole lock map or activate the routine. Read-only code/database review is pending. No SQL parse, tests, migration, database operation, staging, commit or push ran; effective grants and runtime behavior remain unverified.

## 2026-10-24 verification candidate review corrections

Read-only reviews found three source issues in the candidate. The global owner conflict check now
precedes business-row locks; same-owner replay locks the scoped record and rechecks scope before
validating its evidence row and returning the current counter snapshot. A NULL observation now
preserves legacy error precedence (`EVIDENCE_UNSIGNED` after record/state checks). The shared
transaction helper checks `pg_locks` before ranked locks and rejects every already-held advisory
lock and every `change_ledger` relation lock except `AccessShareLock`, with the stable
`P0001/MUTATION_TRANSACTION_INVALID` refusal. Qualification was extended for lock-state refusal,
replay/scope ordering and NULL precedence. A lock-map follow-up also clarified that legacy
`recover_sweep` serializes with v1 on the same record row before the shared counter; legacy recovery
does not take namespace 7. These are source-only changes; SQL parse, tests, migration, database
operation, staging, commit and push remain unrun. Full-map review and disposable qualification
remain open.

The follow-up `code-reviewer` pass identified and the source fixed one more replay invariant:
`prior.generation` must equal the locked record's current `claim_generation`. A stale-generation
observation now refuses as `VERIFY_EVIDENCE_ID_CONFLICT/P0001` before evidence/counter lookup. The
reviewer found no remaining issue in the requested SQL/design/qualification slice; this is only
source review, with SQL parsing, installation and runtime behavior still unverified. Reviewer
model/effort were not exposed.

## 2026-10-24 20:50 UTC strict-SSH directory inventory

Read-only strict-SSH `cmd.exe /c dir D:\1c\mcp` completed with exit 0 and listed the expected
Ivan stack folders/scripts. No file contents or credentials were read. This confirms only trusted
SSH access and directory visibility, not clone identity, effective grants, COM reachability or the
writer transaction boundary. Evidence is in `artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`.

## 2026-10-24 S13 `add_epoch_dependency_v1` candidate

Added the additive entry and opt-in adapter selector. Independent read-only code/database reviews
found that its epoch snapshot could race legacy `bump_epoch`, direct principal/target registration,
and `approve_registry_change` applying those cores. The candidate therefore has no application
`EXECUTE` grant (including `requester_role`) until those epoch writers are fenced; flag-on now fails
closed at the SQL ACL. Disposable prerequisites require races against the same-scope bump and
registry principal/target application after that prerequisite is met. This is source-only; no SQL
parse, tests, migration, database write, staging or commit ran. Effective grants remain
`NOT_VERIFIED`; runtime qualification remains `NOT_RUN`.

## 2026-10-25 S13 fenced epoch-writer candidates

Migration 027 now defines `bump_epoch_v1`, `register_principal_v1`, `register_target_v1`, and `approve_registry_change_v1` with the candidate common scope/lifecycle fence; adapter flag-on selects all four. All new entries are revoked from every named application/private role and have no application grant. This addresses the source-defined epoch conflict graph only as an ungranted candidate: legacy routes remain reachable and all-path cutover is not accepted. Focused read-only code review found no material source issue in the four candidates/routes, and ACL source review confirmed no application grants. No tests, SQL parsing, migration, database operation, staging, commit or push ran. The static repository epoch-writer scan now identifies the four epoch-changing runtime entry families and shows their underlying `epoch_row_bump`/`bump_epoch_internal` implementations in migrations 005/008, with wrappers/approval application in 010. Continue the full S13 entry/lock/ACL closure. Do not enable the adapter flag.

## 2026-10-25 S13 direct registry mutation candidates

Migration 027 now defines `register_verifier_key_v1`, `revoke_verifier_key_v1`, and `enforce_registry_v1`; the existing adapter methods select these only when the explicit S13 flag is enabled, without legacy fallback. All three have no application grants and are explicitly revoked from every named application/private role. Key registration pre-acquires the exact verifier-material lock used by the legacy trigger before verifier row/index work. Revocation preserves the source status-only change and no-op behavior. Registry enforcement preserves its one-way exact replay without a duplicate event. The ACL reviewer confirmed the exact revokes/no-grants; read-only code review is pending. No tests, SQL parsing, migration, DB operation, stage, commit or push ran. Effective grants/race outcomes remain NOT_VERIFIED/NOT_RUN. Next: resolve code review findings and implement the fenced proposal entry/call path; keep the feature flag disabled and do not grant candidate EXECUTE.

**2026-10-25 verifier-key serialization correction:** manual lock-order inspection found direct key registration took the verifier-material advisory lock after the lifecycle row, and direct revocation did not share that material lock. Migration 027 now follows the design's one early lifecycle-row exception after namespace 7, then takes the exact verifier-material advisory lock and sorted namespace-6 `verifier-key-id:v1:` fence before verifier row/index work. Direct/approved registration and revocation share that identity order. Revocation resolves immutable material without a row lock and only updates that observed identity, preserving missing-key no-op behavior under concurrent registration. This remains manual source evidence only; no SQL parse, tests, migration or database operation ran. Candidate grants and the S13 flag remain off; key-registration/revocation race qualification is NOT_RUN.

## 2026-10-25 S13 evidence and barrier lock-order correction

Manual lock-order review found four private-writer paths whose lifecycle ordering had diverged from the accepted design. Migration 027 now takes namespace 2 when required, namespace 8 for private-base paths, namespace 7, the early lifecycle row, signer-material locks and namespace-6 identities before remaining relation rows. `close_and_advance` retains its frozen call-ID snapshot and revalidation under the base fence. The prerequisite matrix captures this sequence. These are ungranted source candidates only. No SQL parse, tests, migration or database operation ran; signer/revocation, barrier-snapshot and finalization races remain `NOT_RUN`.

**Registry proposal entry — 2026-10-25:** migration 027 defines ungranted `propose_registry_change_v1(text,text,uuid,text,jsonb)`. The adapter creates the candidate UUID before `invoke` opens its transaction; flag-off preserves legacy database-generated ID, flag-on selects v1 without fallback. The candidate keeps exact open replay lookup under namespace 2/7/lifecycle, then namespace-6 locks the preallocated global ID, refuses cross-scope reuse before INSERT, stores that ID explicitly and appends one event. Source ACL review confirmed explicit revoke/no application grant; focused read-only code review found no material issue in the registry candidate slice. No SQL parse, tests, migration, DB or commit ran. Effective ACL/runtime remain NOT_VERIFIED/NOT_RUN.

## 2026-10-25 S13 dispatch-receipt requirement candidate

Migration 027 now defines source-only `require_dispatch_receipt_v1`; the adapter preserves the legacy default and selects this entry only when the explicit private-writer schema flag is enabled, with no fallback. The candidate takes the scope fence and lifecycle row before the global `record-change-id` fence, then locks the parent record and inserts the generation requirement with `ON CONFLICT DO NOTHING`, preserving the original requester/writer entitlement, generation and APPLYING/DISPATCHED checks and first-writer attribution. It is explicitly revoked from PUBLIC and all named application/private roles. This does not qualify the claim-generation carry trigger or record/receipt writer pairs. No SQL parse, tests, migration, DB operation, staging, commit or push ran; effective grants remain NOT_VERIFIED and runtime qualification NOT_RUN. Continue the full S13 writer/trigger/ACL map before granting or enabling the selector.

## 2026-10-25 S13 dispatch receipt writer candidate

Migration 027 now defines ungranted `record_dispatch_receipt_v1`; `SqlChangeLedger.record_dispatch_receipt` allocates the receipt UUID before the invoke transaction and routes the v1 signature only when the explicit private-writer schema flag is enabled, with no fallback. Candidate replay equality includes dispatch ID, digest, new version, signer key ID and signature; changed identity refuses with `RECEIPT_IDENTITY_CONFLICT` (`P0001`), while exact replay returns the stored ID and preserves first-writer `recorded_by`. New rows use the allocated ID and append one event. The candidate has explicit revokes and no application grant. Source review, SQL parse and disposable qualification remain outstanding; no tests, migration or DB operation ran. Keep runtime grants and the feature flag disabled until the full writer/trigger map and tests qualify.

## 2026-10-25 S13 dispatch payload verifier candidate

Migration 027 now also defines ungranted `verify_dispatch_payload_v1`; the adapter preallocates `verification_id` before transaction invocation and selects the candidate only under the explicit schema flag, without fallback. It preserves canonical JSON and approval checks, exact lookup-only wire-digest replay, `DIGEST_MISMATCH`, and the event only for a new row; new inserts use the supplied ID. The source has explicit revokes and no application grant. No SQL parse, tests, migration or DB operation ran; source review and `S13-VERIFY-PAYLOAD-ID-01` qualification remain outstanding. Keep the flag off and legacy grants intact pending complete all-path closure.

## 2026-10-25 S13 sweep policy writer candidate

Migration 027 defines ungranted `set_sweep_policy_v1`, and `SqlChangeLedger.set_sweep_policy` routes to it only when the explicit candidate flag is enabled. Operator authorization and the latest legacy numeric/key bounds are preserved; the candidate takes namespace 7 and lifecycle before policy-row locking/merge/upsert, then appends the event. Legacy routing remains the default. No SQL parse, tests, migration or database operation ran. Effective grants are `NOT_VERIFIED`, source review is pending, and `S13-SWEEP-POLICY-RANK-01` remains `NOT_RUN`.

## 2026-10-25 S13 duplicate override binding candidate

Migration 027 defines ungranted `bind_duplicate_override_v1`; the adapter selects it only under the explicit candidate flag and has no fallback. It preserves switch-off, approver capability/independence and current validated-record/digest requirements, while taking namespace 2/7/lifecycle and the global record ID before row access. Exact binding replay is lookup-only with no second event; a changed digest for that approver refuses with `OVERRIDE_BINDING_CONFLICT`. New independent approvers append one event. The legacy default remains and retains its duplicate-event defect. No SQL parse, tests, migration or database operation ran; source review and qualification `S13-OVERRIDE-REPLAY-01` are pending/NOT_RUN.

## 2026-10-25 S13 target-class writer candidate

Migration 027 adds ungranted `declare_target_class_v1`; its existing adapter method routes only under the explicit S13 flag, without fallback. The candidate takes namespace 7/lifecycle and namespace-6 record identity before record update, preserves requester/state/target checks, then appends the event. Legacy remains default. No SQL parse, tests, migration or DB operation ran; source review and the mapped fence-entry qualification remain outstanding.

## 2026-10-25 S13 business-key writer candidate

Migration 027 now adds explicitly revoked `declare_business_key_v1`; `SqlChangeLedger.declare_business_key` selects it only with the explicit S13 flag, preserving the legacy default and failing closed without fallback. The candidate retains the exact namespace-4 duplicate-validation key identity and takes namespace 2, namespace 7, lifecycle, the global record ID and namespace 4 before business rows. It preserves the source digest, exact replay, `key_changed`, validated-to-proposed reset, return value and single event. The candidate remains uninstalled/ungranted; no SQL parse, test or database operation ran, effective privileges remain `NOT_VERIFIED`, and `S13-DECLARE-BUSINESS-KEY-01` remains `NOT_RUN`.

## 2026-10-25 S13 claim and release-claim candidates

Migration 027 now contains ungranted `claim_v1` and `release_claim_v1` candidates with opt-in,
no-fallback adapter routes. Claim preallocates its token ID, freezes the grant/target/resource plan,
acquires sorted global and target/key identities, then locks parents before the records SCC and
children. It preserves live-token replay before readiness and budget checks. Release-claim plans
its token, record/parent and all affected resource rows, serializes token/record IDs and target/key
conflict identities, then locks records before the token/resource children; it preserves requester
or worker authorization, non-issued replay, repair handoff and release-zero-effect behavior.
Both signatures have explicit revokes from every named application/private role. These are source
candidates only: no SQL parse, tests, migration or DB operation ran; effective grants are
`NOT_VERIFIED`, candidate routes are not a cutover, and `S13-CLAIM-PARENT-RANK-01` plus
`S13-RELEASE-CLAIM-RANK-01` are `NOT_RUN`. Continue the remaining S13 mutator/helper/trigger work;
perform independent review and disposable qualification only after coding closes.

## 2026-10-25 S13 release and lease candidates

Migration 027 now also contains ungranted `release_claim_v1` and `renew_writer_lease_v1` with
explicit flag-on/no-fallback adapter routes. Release plans the token, record/parent and affected
resource rows, locks parents before token/resource children, and preserves requester/worker,
non-issued replay, repair handoff and zero-effect release behavior. Lease renewal plans record,
permit and lease, locks them parent-first, revalidates, and preserves TTL/generation/permit/expiry
outcomes. Exact signatures are explicitly revoked from named application/private roles. The new
source slices are not reviewed or runtime-qualified; no SQL parse, test, migration or DB operation
ran, effective rights remain `NOT_VERIFIED`, and `S13-RELEASE-CLAIM-RANK-01`/
`S13-LEASE-RENEW-RANK-01` remain `NOT_RUN`. Continue the remaining S13 mutation/helper/trigger
work before the test phase.

## 2026-10-25 S13 lease and hold candidates

Migration 027 now contains ungranted candidates for writer-lease renewal and scoped anchor-gap /
unclean-restart hold opening. Lease renewal plans the record, permit and lease, then locks parent
before child rows and revalidates. Hold opening uses one bounded planner, preallocates every hold
UUID, takes namespace 6 before the legacy namespace-3 identity, locks targets before holds, and
refuses plans above 200 target/open-hold rows before DML. Existing API methods route only when the
explicit schema flag is enabled, with no fallback. Exact signatures are explicitly revoked from
application/private roles. These remain source-only and unreviewed: no SQL parse, test, migration
or DB operation ran; effective grants are `NOT_VERIFIED`, and
`S13-LEASE-RENEW-RANK-01`/`S13-OPEN-HOLD-RANK-01` are `NOT_RUN`. Continue all remaining S13
mutation/helper/trigger coding before the test/review phase.

## 2026-10-25 S13 anchor-check candidate

Migration 027 now contains ungranted `check_anchor_v1` and an opt-in no-fallback worker route. It
preserves valid-head no-op and mismatch update/insert/event semantics, preallocates global hold
IDs, caps the combined target/open-hold plan at 200 rows, and takes namespace 6, the legacy
namespace-3 hold identity, parent/hold rows, then the namespace-1 chain identity last before
rechecking the anchor and writing. The exact signature has explicit application/private revokes.
This is source-only and unreviewed: no SQL parse/test/migration/DB operation ran; effective rights
are `NOT_VERIFIED` and `S13-ANCHOR-CHECK-RANK-01` is `NOT_RUN`. Continue S13 code and full
writer/trigger/ACL closure before qualification.

## 2026-10-25 S13 permit-cancel candidate

Migration 027 now contains ungranted `cancel_permit_v1` with an explicit flag-on/no-fallback route.
It freezes a bounded record/token/permit/resource plan, takes sorted global and target/key IDs,
then locks record parents before token, permit and resource children. A losing dispatch CAS is a
no-op; a winner retains token supersede, release-zero-effect, record state and single-event behavior.
The exact signature has explicit application/private revokes. This is source-only/unreviewed: no
SQL parse, test, migration or DB operation ran; effective rights remain `NOT_VERIFIED` and
`S13-CANCEL-PERMIT-RANK-01` is `NOT_RUN`. Continue remaining S13 code before test/review phases.

## 2026-10-25 S13 hold-release candidate continuation

Migration 027 and `SqlChangeLedger` now contain an ungranted, opt-in `release_hold_v1` candidate. It freezes the selected hold and optional canonical two-person cosign identity, then follows namespace 2 → 7 → lifecycle → namespace-6 IDs → exact namespace-3 hold identity → optional record parent → hold → cosign. It revalidates the planned rows and preserves cause-specific proof, replay, and event semantics. `S13-RELEASE-HOLD-RANK-01` is `NOT_RUN`; effective privileges remain `NOT_VERIFIED`. No SQL parse, tests, migration, or database operation ran. Continue remaining recovery/helper/trigger source coding and full lock-map closure before entering the test/review phase.

## 2026-10-25 S13 direct-revocation candidate continuation

Migration 027 and the adapter now contain an ungranted `revoke_change_v1` candidate selected only in candidate mode, with operator-only direct execution. It bounds and freezes the selected record/token/resource plan, fences global record/token IDs and target/key lock identities, locks target/record parents before token/resource rows, revalidates, and then uses the existing cause/state core. Candidate mode now fails closed for other registered legacy mutators instead of falling back. `S13-REVOKE-CHANGE-PARENT-RANK-01` is `NOT_RUN`; effective grants are `NOT_VERIFIED`. No SQL parse, tests, migration, or DB operation ran. Continue full bounded recovery, source/trigger coverage, and the rest of the versioned lock map before qualification.

## 2026-10-25 S13 recovery continuation

The additive candidate now includes `revoke_stale_v1`, `kill_switch_v1`, and `retry_verify_v1`, each with an explicit adapter route selected only under the private-writer schema flag and no legacy fallback. Stale revocation plans fair batches of at most 20 under the accepted namespace 2 → 7 → lifecycle-row → namespace 5 order, then fences and revalidates record/token/resource/failure identities. The kill-switch candidate keeps STOP_ADMIT/STOP_EFFECTS/REVOKE available and refuses reopening a stopped scope until full recovery is qualified. Retry verification freezes its evidence IDs, record, hold, counter, target and zero-effect locks before applying the source state machine. Exact qualification scenarios are in `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`; they all remain `NOT_RUN`, candidates are uninstalled/ungranted, and effective grants are `NOT_VERIFIED`. No SQL parse, test, check, migration, DB operation, COM call, commit or push ran. Next coding: complete the bounded `recover_sweep` affected-row plan, including all stage counters/failures/nonces and explicit run-ID handling, then finish the helper/trigger/conflict lock map before tests and reviews.

## 2026-10-25 S13 bounded recovery continuation

Source comparison found that `retry_verify_v1` removes every target lock owned by the change within its base. The plan now freezes and revalidates that full delete set, narrows key locks to the exact base-scoped delete predicate, and includes all target identities in namespace 4; `S13-RETRY-VERIFY-RANK-01` adds the multiple-target-reference case and remains `NOT_RUN`. The opt-in `recover_sweep_v1` route checks all current eligibility families, including expired approval nonces. When no stage is eligible it fences the adapter-preallocated run ID and writes a zero-work run report, preserving unresolved and existing failure counts. It now processes one eligible current-generation T5x claim per run and one eligible T6c/T6r permit recovery per run through a shared bounded resource plan. T6c freezes all permit, token, record/resource, parent and failure rows, runs the `PERMITTED` CAS after revalidation, and accounts for token/key-release effects; T6r additionally freezes and revalidates the latest `APPLYING` event and permit deadline before the `NOT_PERMITTED` CAS. Both retain repair handoff and event/failure semantics. The bounded path also processes selected T3 expiry, REVOKE-only VOID approval cleanup, expired approval-nonce transitions, and T9 deadline recovery under a combined 66-item ceiling. It fences deduplicated records and every failure, nonce, permit and planned existing/preallocated hold identity; takes namespace 3 after namespace 6 and before selected row locks; repeats the related-hold ambiguity guard after namespace 3; and revalidates the full hold, row, permit and deadline plans before effects. Item events are appended in queue order after the run row. `S13-RECOVERY-QUIESCENT-RUN-01`, `S13-RECOVERY-T3-RANK-01`, `S13-RECOVERY-T5X-RANK-01`, new `S13-RECOVERY-T6C-RANK-01`, new `S13-RECOVERY-T6R-RANK-01`, `S13-RECOVERY-VOID-RANK-01`, `S13-NONCE-RANK-01` and `S13-RECOVERY-T9-RANK-01` remain `NOT_RUN`; T12, anchor-gap and verify stages still refuse with `RECOVERY_NOT_READY`. Full remaining permit, resource, counter, failure, trigger and stage planning/implementation is still open. No SQL parse, test, check, migration, database operation, COM call, commit or push ran in this continuation. Effective grants remain `NOT_VERIFIED`; the candidate is uninstalled/ungranted.

## 2026-10-25 bounded recovery source continuation

The source-only `recover_sweep_v1` candidate now has isolated T12, GAP_BOUND, GAP and VERIFY routes alongside T5x/T6c/T6r, plus the previously bounded T3, REVOKE-only VOID, nonce-expiry and T9 path. The new routes each select one ranked item, snapshot/revalidate relevant event, record, hold, counter and failure state, and append their queued stage event after the adapter-preallocated sweep-run row. The disposable matrix now defines `S13-RECOVERY-T12-RANK-01`, `S13-RECOVERY-GAP-BOUND-RANK-01`, `S13-RECOVERY-GAP-RANK-01`, and `S13-RECOVERY-VERIFY-RANK-01`.

This is manual source work only. The candidate remains uninstalled and ungranted; effective PostgreSQL grants are `NOT_VERIFIED`; all new and prior recovery scenarios are `NOT_RUN`. No SQL parse, test/check, migration, database operation or COM call ran. The remaining in-scope code work is the aggregate source lock/trigger/FK/effect closure and correction of any source-review findings. Functional and E2E roles execute the disposable qualification only after coding closes.

Manual source continuation then corrected two local report-state cases in `recover_sweep_v1`: the bulk T3/VOID/T9 handlers restore queued-event prefix and changed count after item subtransaction rollback, and the one-item T5x handler now replaces its retained local success queue with exactly one `SWEEP_ITEM_FAILED` event. The T5x disposable fault criterion now injects after the success ID/event are queued but before the item savepoint exits. Both remain source-only; qualification is `NOT_RUN`, candidate is uninstalled/ungranted, and no parser/check/test/database/COM operation ran. Continue the aggregate effect/trigger/FK closure and inspect all remaining exception paths before handing work to the test roles.

Manual routing review then aligned the candidate order with that checkpoint: `recover_sweep_v1` selects T5x → T6c → T6r → T12 → GAP_BOUND → GAP → VERIFY before selecting the combined T3/VOID/expired-nonce/T9 batch. The one-item routes return first and report lower-priority eligible work for a later invocation. A simultaneous-eligibility precedence case was added to the disposable matrix; it is `NOT_RUN`. The code reviewer found no routing defect in this change. No parser/check/test/database/COM operation ran.

Manual eligibility review found and removed a duplicate unconditional `APPLYING`/`NOT_PERMITTED` branch in `private_writer_recovery_has_eligible_v1`; it had marked T6r due before its latest `APPLYING` event plus permit TTL. The separately computed `has_unresolved` remains true, preserving the fail-closed signal. A not-yet-due T6r qualification boundary now expects `has_more_eligible=false` and `has_unresolved=true`, then eligibility after the frozen deadline. This is source-only; qualification is `NOT_RUN`, grants `NOT_VERIFIED`, and candidate uninstalled/ungranted. Continue aggregate trigger/FK/effect closure; no SQL parse, tests/checks, migration or database operation ran.

## 2026-10-25 recovery item-savepoint report state

In the combined T3/VOID/T9 source path, the per-item exception blocks now snapshot and restore the queued-event prefix and `changed` total. This accounts for PL/pgSQL local state surviving SQL subtransaction rollback. The related injected-failure criterion remains `NOT_RUN`; the change is not runtime evidence. Continue source review of the complete mutation/trigger/FK/effect graph before handing tests to the functional and E2E roles.

## 2026-10-25 source continuation after recovery-plan reviews

Candidate migration 027 remains uninstalled; its source-level grants (including the worker-only `verify_inconclusive_v1` grant) are not effective-grant evidence and remain `NOT_VERIFIED`. No SQL parse, test/check, migration, database action, COM call, stage, commit or push was run this turn. The `revoke_stale_v1` plan now includes selected `parent_change_id`/`repair_for` record parents in namespace-6 identity and canonical record locks, validates same-scope/existence, revalidates the parent snapshot before DML, and follows the candidate FK-SCC child order. A focused database-reviewer pass found no parent/lock-plan blocker; it identified and reviewed the cap correction that removes duplicate existing-failure-row counting while reserving one failure-row effect per selected item. A separate predicate-parity review corrected T5x `has_eligible` to match current-generation/CLAIMED/NOT_STARTED selector conditions, then found and corrected a MAJOR T6c stale-generation issue: both selection and `has_eligible` now require the permit generation to match `records.claim_generation`, and the shared T6c/T6r helper rechecks it against its planned and locked record before cancellation/reset. The same reviewer rechecked the final T6c path and found no remaining concrete mismatch; no other eligibility-selector mismatch was found in that source comparison. Focused disposable scenarios for parent revalidation, failure-row cap accounting, stale T5x tokens and stale T6c permits are specified in `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, and remain `NOT_RUN`.

Current evidence snapshot: base HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`, candidate migration SHA-256 `c819f75bb2fb85acd7cfaafeebee8471a0b3e143f1a2f98db9dd65845d7637d4`. Reviewer model/effort metadata was not exposed (`UNKNOWN`). Current local authenticated MCP `source_health` for `onec-818ha-reference` returned `ok=true`; strict SSH to `koros@100.88.71.74` using the trusted host key reported all nine stack components true. Neither fact qualifies business reads, effective grants, the COM clone, or S12/S13 behavior. Do not retry the timed-out 521.1 read until bounded diagnostics. Accountable owner: operator; executor: Codex; Ivan stack is the technical owner of its SSH/host boundary; functional/E2E roles own disposable qualification after code closure.

## 2026-10-25 recovery lock-order continuation

The pre-turn candidate already contains GAP parent closure: it snapshots all matching overdue holds, includes every referenced non-null `holds.change_id` record in the namespace-6 and canonical parent-lock sets, validates same-scope/base edges, and revalidates the parent/hold snapshots before DML. This turn changed VERIFY acquisition to records → existing holds by `hold_id` → optional counter → failure row; `retry_verify_v1` to target parent → record → holds by PK → key locks → retry counter → target locks, while preserving the counter-presence bit; and the shared T5x/T6c/T6r helpers to acquire stage failure rows before target-lock and writer-lease siblings. The corresponding GAP, VERIFY, retry, T5x, T6c and T6r scenarios are specified in `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`; they remain `NOT_RUN`. Candidate migration remains uninstalled/ungranted, effective grants `NOT_VERIFIED`. No SQL parse/check, tests, migration, database operation, stage, commit or push ran. Next: continue source-level lock/trigger/FK/effect closure; run the focused database-reviewer pass only after that coding slice closes, then hand qualification to functional-test-reviewer and e2e-runner. Accountable owner: operator; executor: Codex.

Current candidate source snapshot: SHA-256 `85527997a501ffdaa7b4db1888453dd199b39c1448016c4f5f663b9a927349c3`. Recovery lock-order edits are in `private_writer_recovery_gap_v1` (`027:6124-6269`), `private_writer_recovery_verify_v1` (`027:6273-6430`), shared T6c/T6r permit (`027:6433-6671`), and T5x (`027:6854-7087`); ordinary worker `retry_verify_v1` is `027:5739-5895`. The disposable prerequisites specify every changed path as `NOT_RUN`. Source-only evidence; no SQL parse/check, tests, migration, database operation, stage, commit or push. Effective grants remain `NOT_VERIFIED`; candidate uninstalled/ungranted. Continue remaining source lock/trigger/FK/effect closure before reviewer and functional/E2E handoff.

2026-10-25 T9 same-base batch guard: `recover_sweep_v1` now refuses `LOCK_PLAN_STALE` before row locking when two selected T9 records share a base, including when the frozen plan contains no existing CALL_OWNERSHIP hold. Qualification `S13-RECOVERY-T9-RANK-01` covers this case and remains `NOT_RUN`. Candidate migration SHA-256 `4663bd0493ebc87933bbbd1257a0ccbe5d12dd70b293d5241bb3c5f5e58d2f60`; source guard `027:7278-7282`. This is source-only; no parser/check/test/migration/DB/COM/staging/commit/push. Continue recovery and source lock/trigger/FK/effect closure.

2026-10-25 candidate ACL review: `SqlChangeLedger._PRIVATE_WRITER_SPEC` maps versioned operation names to runtime roles, but migration 027 intentionally revokes many of those candidate signatures until the complete all-path fence cutover is reviewed. This is confirmed by the function-level source comments for receipt requirements and target observation and by the registry/epoch closure notes; do not add grants or enable the candidate flag ahead of that gate. Added `S13-ACL-SOURCE-ROLE-MAP-01` to distinguish intentional source revokes from missing effective-grant evidence and to require exact role/signature `has_function_privilege` measurements only after the source closure and disposable install. The candidate migration is unchanged by this ACL investigation and remains SHA-256 `4663bd0493ebc87933bbbd1257a0ccbe5d12dd70b293d5241bb3c5f5e58d2f60`; it remains unapplied, so effective grants are `NOT_VERIFIED`. No parser/check/test/database operation ran.

2026-10-25 trigger ACL hardening: a source-only database-reviewer audit found that `private_writer_bump_trust_revision_v1()` was the sole function among 82 migration-created functions without an explicit PUBLIC revoke; the migration has no `SET ROLE`, so reliance on `ALTER DEFAULT PRIVILEGES FOR ROLE ledger_owner` did not prove protection for this ownership-transferred trigger helper. Added an explicit revoke from PUBLIC and both private-writer principals at `027:8479`. Candidate SHA-256 is now `f89d459c1c02b538f4d57cff6c98c6e0d08c7fcd010246860badd519c2f6e62d`. The reviewer also confirmed ordinary adapter candidate routes remain deliberately revoked until all-path cutover; their selector flag must stay off. This remains source-only; no SQL, install, tests, checks or effective-privilege query ran.

2026-10-25 combined recovery source re-review: the read-only `database-reviewer` review found no concrete issue in the combined T3/VOID/nonce/T9 recovery path. It confirmed the T9 duplicate-base guard rejects before selected-row locks (`027:7278-7281`, locks begin at `027:7400`), planned live-hold membership is locked and revalidated (`027:7283-7290`, `7351-7364`, `7409-7412`, `7431-7438`), and pre-lock/final effect bounds plus local queue restoration cover the reviewed paths (`027:7314-7319`, `7376-7398`, `7495-7511`, `7530-7546`, `7579-7598`). Model/effort metadata was not exposed (`UNKNOWN`). This is source review only; recovery qualification remains `NOT_RUN`, and the candidate remains unapplied. No SQL, parser, tests/checks, migration or database action ran.

2026-10-25 exact evidence-attempt context source: added a candidate one-row SQL lookup keyed by exact dispatch-CAS ID, call ID, tenant/company, organization and base fingerprint, returning only fixed-shape immutable attempt context. It returns `NULL` for a miss and requires the evidence-ingest `SESSION_USER`; SQL function execution and composite-type usage remain revoked pending independent database/security review of enumeration and cross-scope exposure. Added `PostgresEvidenceAttemptSource`, which calls only that exact selector in a bounded read-only transaction and rejects mismatched record/context, duplicate-key or wrong-shape JSON, and noncanonical UUIDs. Candidate migration SHA-256 `661D71F81D1B3E5AF70E9F11C185D6D0ECB5542FDD5BED20F96B7BEB4666EEF0`. The registrar remains uncomposed pending validator-build provenance. Qualification `S13-ATTEMPT-CONTEXT-LOOKUP-01` is `NOT_RUN`; no SQL parsing, test/check, migration, database operation, staging, commit or push ran. Accountable owner: operator; executor: Codex; next: continue source closure, then review the lookup before granting its ACL.

2026-10-25 lookup-result bound refinement: set the Python JSON text ceiling to 128 KiB. The candidate SQL bounds nine returned text fields to 2,048 UTF-8 bytes each; worst-case sixfold JSON escaping plus the fixed 23-field object fits under that ceiling. The adapter rejects non-string JSONB decoder results to keep byte bounding and duplicate-key policy explicit. Adapter SHA-256 `C87E76B17E1A384A4720771E744D82082C6B833B2A68FF86D8430EAFDA115A75`. Source-only; no product tests, SQL parsing, installation, grants, or database operation ran. One accidental `git diff --check` was executed before the final decoder refinement and emitted only an LF/CRLF warning; it is not acceptance evidence. `S13-ATTEMPT-CONTEXT-LOOKUP-01` remains `NOT_RUN` pending exact boundary and driver qualification.
2026-10-26 bounded decoder allocation correction: `PostgresEvidenceAttemptSource._decode()` no longer encodes the complete driver-returned JSON string merely to measure its 128 KiB UTF-8 size. It pre-rejects when character count alone exceeds the byte ceiling, then encodes at most 16 KiB of characters per sizing step and stops on the first byte overflow before `json.loads()`. Source SHA-256 `D0C7183B2A9AB267936C368C18E863597F35464C52EB56464E511C881E667575`. Added `S13-ATTEMPT-CONTEXT-JSON-BOUND-01` for exact ASCII/multibyte boundaries, malformed surrogates, oversized ASCII, stable refusal, and proving JSON parsing is skipped on rejection. Change record 313. No test/check, SQL parse, migration, DB/runtime action, staging, commit, or push ran; functional-test reviewer owns these cases after source coding closes.
2026-10-26 COM identity preflight: `windows_com_lane` now rejects a returned `CurrentUser().Name` longer than 256 characters before printable scanning and UTF-8 encoding, matching the already configured expected-name ceiling. Source SHA-256 `CAC4E5591B5A9DC51AC74E6806D2D95517A2A0748295D15A36465599B056609C`. Qualification `S13-COM-USER-BINDING-01` adds the overlong actual-name refusal before the base-fingerprint callback. Change record 314. Source-only; no COM action, test/check, staging, commit, or push ran; current Ivan identity/grants remain unverified by this change.
2026-10-26 private Authorization header cap: `PrivateWriterAuthenticator._authorization_value()` rejects strings and bytes above the maximum supported `Bearer ` grammar length before bytes decoding or regex matching. Source SHA-256 `B5B2A4C51061AB4FC695FE5A39A1BB4431EBE74B29FBD9BF1B2C4BA1C8FE0B38`. Acceptance `S13-PRIVATE-AUTH-HEADER-BOUND-01` covers exact maximum, plus-one, very large bytes, and zero verifier calls on refusal. Change record 315. Source-only; no test, check, service or auth request ran. Functional-test reviewer owns later boundary qualification.

2026-10-25 effective-grants evidence: the database-reviewer role executed read-only catalog checks on the local disposable PostgreSQL lane. `business_ai`/PostgreSQL 16.15 has no `change_ledger` schema, sampled candidate roles or sampled candidate functions; candidate table grants returned 0 rows and function grants are `NOT_MEASURABLE` because signatures are absent. No schema was installed. The prior artifact claim that `CT14_FEASIBILITY_SPIKE_2026-10-12.md` was absent was corrected; it exists and records historical 818HA_p2diff clone rights only, not Ivan-host rights. Full sanitized evidence: `artifacts/WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-24.md`. Next: finish code, then authorized disposable install/grants recheck; separately verify current Ivan clone identity before attributing 1C rights.

2026-10-25 one-revision evidence verifier: added `ProductionEvidenceVerifier.verify_set` to parse/bind up to five unique causal record roles before one trust-source call, then independently verify each included envelope against the same snapshot, revision and trusted validation time. Candidate SHA-256 `C5449DB80783D0A81211E3223E4FDA883BB3661E0748BCFF351BCE90580FF44C`. An actual read-only `code-reviewer` pass found no concrete issue; model/effort `UNKNOWN`. `S13-PRODUCTION-EVIDENCE-VERIFY-01` remains `NOT_RUN`; no tests, SQL parse, migration, DB or COM action ran.

2026-10-25 legacy S13 cutover source: migration 027 now explicitly revokes runtime execution from legacy direct dispatch, terminal/recovery, and operator-resolution functions enumerated in `S13_EVIDENCE_REGISTRATION_CONTEXT_DESIGN_2026-10-24.md`; candidate SHA-256 `5AFDB908B616B68C70527F45ED7193B6712DB17F74232615A24909557780BEE4`. Manual source reconciliation corrected the final `verify_signed` overload to the six-argument signature retained after migration 007 dropped its older boolean overload. This is partial, source-only ACL closure; `S13-LEGACY-MUTATOR-CUTOVER-ACL-01` remains `NOT_RUN` pending complete grant/signature inventory, independent database/security review and disposable effective-grant measurement. No SQL parse, migration, database operation or test ran.

2026-10-25 S13 approval-envelope writer candidate: migration 027 now defines ungranted `store_approval_text_v1(text,text,uuid,text,text,uuid)` and the adapter routes to it only when `private_writer_schema_enabled` is explicitly true. The adapter preallocates `envelope_id`; SQL takes namespace 2, scope 7, lifecycle and sorted namespace-6 record/nonce/envelope identities before records → nonce row locks, checks envelope-ID collision, preserves exact lookup-only replay after lifecycle/nonce changes, validates new text/nonce, inserts the explicit ID and appends a digest-only event. The legacy path remains the default; no grant was added. An actual read-only `database-reviewer` pass found no concrete source issue after the final signature/ID changes; model/effort metadata is `UNKNOWN`. Candidate migration SHA-256 `D53E05B54C8DD1CA994F3C6A76467576BCBB677E9C0F6A55F47ED6B1AAC3F631`; adapter SHA-256 `3150651647BD09A7ED6080CE55C064A682E66B934C7BCE26C029C5B416D4C54F`. `S13-NONCE-RANK-01` remains `NOT_RUN`: issuance, approval, rejection and expiry still need one coordinated fence before the selector is granted/enabled. No SQL parse, tests/checks, migration, DB or COM action ran.

2026-10-25 S13 approval nonce/envelope candidates — superseding snapshot: migration 027 now also defines ungranted `issue_approval_nonce_v1(text,text,uuid,text)`, and the adapter selects it only under the explicit schema flag with a preallocated 64-hex nonce. The candidate takes scope 7, snapshots at most 199 scoped expired nonces, fences record plus expired/new nonce IDs in namespace 6, locks record before sorted nonce rows, and revalidates the exact expired set before updating/inserting. The envelope adapter/source now passes a preallocated UUID and uses the updated six-argument signature. Separate read-only database-reviewer passes found no concrete issue in the final envelope candidate or in nonce issuance; exact model/effort metadata is UNKNOWN. Final candidate migration SHA-256 `E11C020C165C5FE341E7C539EEC166E2901F8D3B0E709BF08AEBF42019892B52`; adapter SHA-256 `2E9F62A5E5F0C66B4DD88DA9FD353EA362E1769301DF6EA92CF97302FC78C5BF`. `S13-NONCE-RANK-01` remains `NOT_RUN`: approval/rejection and the coordinated expiry path remain open. These are source candidates only: no SQL parse, test/check, migration, database operation, staging, commit or push ran; no candidate grant was added.

2026-10-25 S13 approval/rejection candidate completion: migration 027 and the opt-in no-fallback adapter now also define `approve_v1` and `reject_v1`. Approval preallocates and fences its global approval ID, preserves exact replay only for the same nonce/approver/digest/version while authorization is APPROVED or CLAIMED, then retains independent approver/person/session, canonical envelope, epoch, duplicate override, nonce-consumption and digest-event behavior. Rejection preallocates/fences its approval ID and remains one-shot; it does not add a kill-switch-OFF rule absent from the legacy contract. Both exact signatures are explicitly revoked from PUBLIC and named application/private roles; no grants were added. Read-only database-reviewer passes found no concrete issue in all four candidate entry functions and routes; model/effort metadata UNKNOWN. Current candidate migration SHA-256 `30D0D1092E21C719019EB3D53779AC1EBCF654DF922989390CBEE122859DE954`; adapter SHA-256 `73AC1AC4DE9053F81E55D43284A48A2C6E761F2F0BD628A0F868EDF5629460C3`. `S13-NONCE-RANK-01` remains `NOT_RUN`: the legacy grants are not yet cut over, aggregate lock/trigger review and qualification are outstanding. No SQL parsing, tests/checks, migration, DB operation, COM, staging, commit or push ran.

2026-10-25 S13 validation lock-order candidate: migration 027 now defines ungranted `validate_v1`; its explicit-flag adapter route is no-fallback. It prelocks namespace 2/7/lifecycle, a global record ID, and the exact compatibility namespace-4 business-key identity before row locks; it then locks/revalidates the full record and optional business-key snapshots and preserves budget, duplicate/override, and event behavior. The still-granted historical `validate(text,text,uuid)` signature is replaced by a SECURITY DEFINER bridge to the same v1 body, closing the mixed legacy/v1 lock inversion identified by the first source review. A fresh read-only database-reviewer pass found no residual concurrency, behavior, or security issue; metadata UNKNOWN. Candidate SQL SHA-256 `FE7DBADA2B548CA71F5272FF61C995997BCF7649F2F5ADBF9078C09C4A46855B`; adapter SHA-256 `56BD13BA08AC2D95F991A58D84EE53C2CA3C2278FF17EB89FE29AA65B393CAD6`. `S13-VALIDATE-RANK-01` remains `NOT_RUN`; no SQL parse, tests/checks, migration, database operation, staging, commit or push ran.

2026-10-25 S13 `propose_v1` parity and bridge deferral: completed target organization/permission-expiry/requester-capability checks, persisted target/principal epoch dependencies and `session_user`, and restored exact concurrent logical-request replay/digest-conflict behavior. Removed the still-granted legacy bridge because the other epoch writers do not yet share namespace 7. Adapter flag remains default-off; candidate exact signature remains revoked and flag-on fails closed without a grant. An actual read-only database-reviewer re-review found no remaining source finding in the candidate or no-bridge posture (model/effort UNKNOWN). Candidate migration SHA-256 `E786D8DE19E6721D0188BB8F3A251B99224890E89AE2808BD6DC2C39383D098A`; adapter SHA-256 `BC57602BC9B3738BD2A9F390F7B39A72418820336C20B7D2D9A5B441987BDDAE`. This is not SQL, installed-ACL, or runtime evidence; tests, SQL parsing, migration, and DB calls were not run. Continue all-path/epoch-writer source closure before any qualification or cutover.

2026-10-25 code continuation: `PostgresWriterReceiptRegistrar` now implements the S12 writer receipt/no-entry receipt verification and evidence-ingest slice. Current contract: bounded canonical parse → exact attempt lookup → caller identity/process/CAS/payload/repair comparison → production signature/trust verification → one bounded `READ COMMITTED` registration transaction. It preserves original signed bytes, deterministic refs, and replay across validator-build upgrades while keeping the first validator build as provenance. A read-only database-reviewer pass found two MAJOR issues (build ID in replay equality and missing explicit isolation), both fixed; final static re-review found no remaining BLOCKER/MAJOR in the slice. Source hashes and scope are recorded in `S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` and `OPERATOR_BACKLOG.md`. No tests/checks, SQL parse, migration, DB or COM ran, and the adapter has no live composition/verified effective grants. Continue with source coding for the required outcome/completion registration path and private-writer composition; preserve no COM/terminalization authority in this registrar. Then finish all coding before delegated functional/E2E and specialist review/qualification.

2026-10-25 source-code checkpoint: `PostgresWriterReceiptRegistrar` is implemented for S12 writer/no-entry receipt envelopes. It uses bounded canonical parsing, exact attempt lookup, full caller identity/process/CAS/payload/repair binding, fresh trust/signature validation, and a separate `READ COMMITTED` evidence-registration transaction with deterministic refs and original bytes preserved. Two MAJOR findings from the actual read-only database-review pass (validator build ID in replay equality; implicit isolation) were corrected and the final review found no remaining BLOCKER/MAJOR in this slice. Exact hashes and evidence limits are in `S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` and `OPERATOR_BACKLOG.md`. No tests/checks, SQL parse, migration, DB or COM ran; effective grants and live composition are NOT_VERIFIED. Continue with remaining evidence registration and private-writer composition before entering the test phase.

2026-10-25 source checkpoint: evidence-set registration now uses explicit CAS + caller identity lookup, verifies up to five causal envelopes against one trust snapshot, and projects receipt/no-entry, outcome V1–V3, completion, challenge and read-attestation rows through separate replayable transactions. Database-review found and corrected first-record selector and challenge-role defects. Security review found the selector's cross-tenant metadata exposure and no evidence for certificate-mapped service isolation; all evidence-ingest EXECUTE grants were removed from candidate migration 027. The adapter now requires authenticated validator-build provenance, but the repository has no provider implementation/composition. Hashes and exact reviewer scope are in `S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` and `OPERATOR_BACKLOG.md`. No tests/checks, SQL parse, migration, DB, COM, staging, commit or push ran. Continue independent source work; keep credential/build provenance and effective grants blocked until their exact security dependencies are established.

2026-10-25 effective-grants recheck: read-only query against the local disposable PostgreSQL lane (`business_ai`, PostgreSQL 16.15, configured port 18432) found only `business_ai_app` among sampled candidate/application roles and no `change_ledger` schema. Candidate S13 effective table/function/type grants are `NOT_MEASURABLE`, not `DENIED` or verified. The in-process DSN was not printed; no grants or schema were changed. Evidence: `docs/phase2/artifacts/WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-25.md`. Re-run only after source closure and accepted service-credential isolation, on the disposable database.

2026-10-25 S13 recovery nested-guard correction: `private_writer_append_queued_events_v1` no longer reuses the top-level first-lock-participant assertion after recovery DML; it retains a READ COMMITTED/read-write mode guard. `private_writer_recover_sweep_core_v1` retains the full assertion for ordinary recovery and applies only the transaction-mode guard for `p_defer_events=true`, the revoked internal path called by operator-validated `kill_switch_v1`. A database-reviewer source pass found that the deferred kill-switch path otherwise necessarily failed because it already held namespace-2/namespace-7 and the lifecycle row before entering core; the correction was re-reviewed with no remaining BLOCKER/MAJOR in this slice. Candidate remains uninstalled/unqualified; no SQL parse, tests/checks, migration, DB or COM operation ran. Source review only; reviewer model/effort UNKNOWN. Accountable owner: operator; executor: Codex. Next: continue all-path lock/trigger/FK/effect closure before the full specialist review and disposable qualification.
2026-10-25 S13 claim replay authorization correction: `claim_v1` returned an existing live claim token before comparing the authenticated caller with the record requester. Moved the ownership check to immediately after the locked-scope recheck and before the replay return, while preserving replay ahead of lifecycle readiness, current switch, and fresh budget eligibility checks. A read-only database-reviewer pass found no BLOCKER/MAJOR in the relocation; the candidate remains unparsed/uninstalled/unqualified. No tests/checks, SQL parser, migration, DB or COM operation ran. Reviewer model/effort UNKNOWN. Accountable owner: operator; executor: Codex.

2026-10-25 S13 legacy claim-release cutover: the source-wide route scan found migration 004's still-reachable `release_claim(text,text,uuid)` locking token before record, opposite to candidate `claim_v1`'s record-before-token replay path. Migration 027 now `CREATE OR REPLACE`s the legacy release body as a fixed-search-path, schema-qualified call to `release_claim_v1`, preserving the signature and historical function ACL while leaving direct v1 execution revoked. The actual database-reviewer source follow-up found no BLOCKER/MAJOR: caller identity remains based on the existing `caller_role()` (`SESSION_USER` or the `SET ROLE` GUC), the versioned routine repeats requester/worker authorization, and it retains legacy no-readiness and return/event behavior. This removes the identified release-path source lock inversion only; SQL installation, effective grants, and runtime lock behavior remain `NOT_VERIFIED`/`NOT_RUN`. Candidate hash after this bridge: `2AFC2E6F2E5E62063F51029B1E9CD44957BB591E44035C7658F6CD1533EE1CB7`; relevant anchors: migration 004:61-65, 746-756; migration 027:5308-5455.

The same scan confirms that legacy `claim(text,text,uuid,text,uuid,numeric,boolean,boolean)` is still granted by migration 004 and is not revoked by candidate 027. That is deliberate for additive qualification: `claim_v1` has no application grant. It is an exact cutover dependency, not approval to leave both APIs active: route all callers to the versioned method and revoke that signature atomically before granting/enabling S13. The legacy path locks record before grant, opposite to `claim_v1`'s grant-before-record order, and it does not join the namespace-7 epoch fence. The requirement is stated next to the candidate ACL block in 027. Candidate SHA-256 after the comment: `C232E6C1C20C9B8C47C67BE38EFF046BA3CD0DD1113D7407158C564087D45F8F`. No tests/checks, parser, migration, database operation, COM, staging, commit or push ran. Accountable owner: operator; executor: Codex; reviewer role: database-reviewer (model/effort unavailable). Next: finish the all-path lock/trigger/FK/effect closure and exact caller/grant cutover map before disposable qualification.

2026-10-25 S13 claim replay-key identity closure: source review found that a live `UPDATE_DRAFT` token replay could accept a changed `p_key_hash` when its key existed only in `key_locks` and no `business_keys` row existed. Candidate 027 now snapshots at most one owner key row, includes its namespace-4 identity before row locking, locks/revalidates its full row after budget and claim-token child locks, and requires exact present/absent/hash agreement before replay; corrupt multiplicity greater than one refuses closed. The guard is inside the replay branch after grant and amount/count comparison, preserving `BUDGET_EXCEEDED` and fresh-claim error precedence. The actual `database-reviewer` first identified the initial precedence and child-order issues; both were fixed and the final focused re-review found no remaining source blocker. This remains unparsed/uninstalled/unqualified; no SQL parse, test/check, database operation, or migration ran. Final candidate SHA-256: `5753ECC81B95820A3CEF434B9FD83EAA1D86B00AF52A525A44012F19B6721202`; source anchors `027:5077-5100,5133-5145,5168-5228`; qualification prerequisite `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:626`. Reviewer model/effort UNKNOWN. Accountable owner: operator; executor: Codex. Next: continue source-wide lock/trigger/FK/effect and exact ACL/caller closure before disposable qualification.

2026-10-25 S13 begin-apply fence ordering: `change_ledger_begin_apply_v1` now acquires the existing namespace-6 call, token, parent-record and preallocated intent identities after switch/scope/lifecycle gates but before record/token row locks. It then locks the parent record before re-reading/validating the child token and retains exact call/host/session consumed replay and global call-ID collision checks. An actual read-only `database-reviewer` pass found no BLOCKER/MAJOR in the hint/fence identity, row order, stale-generation checks or replay path. Migration 027 grants this candidate to requester/writer in source; installed effective rights and runtime waits remain unverified. This is source-only: no SQL parse, tests/checks, migration or DB operation ran. Candidate hash: `01D28ABA725B8E3546CB8BC81057747056AA815FDFF6030BE48937E2866C4DAD`; anchors `027:2375-2449`, helper `027:1371-1385`, prerequisite `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:103,107-108`. Reviewer model/effort UNKNOWN. Next: continue all-path lock/trigger/FK/effect and effective ACL closure before disposable qualification.

The same scan confirms that legacy `claim(text,text,uuid,text,uuid,numeric,boolean,boolean)` is still granted by migration 004 and is not revoked by candidate 027. That is deliberate for additive qualification: `claim_v1` has no application grant. It is an exact cutover dependency, not approval to leave both APIs active: route all callers to the versioned method and revoke that signature atomically before granting/enabling S13, because the old route does not join the namespace-7 epoch fence. The requirement is stated next to the candidate ACL block in 027. Candidate SHA-256 after the comment: `FF9865BDA8147179C425270FD4486F8E03630DC32266400ED29C118DCF664E12`. No tests/checks, parser, migration, database operation, COM, staging, commit or push ran. Accountable owner: operator; executor: Codex; reviewer role: database-reviewer (model/effort unavailable). Next: finish the all-path lock/trigger/FK/effect closure and exact caller/grant cutover map before disposable qualification.

2026-10-25 S13 business-key child-plan closure: `declare_business_key_v1` now snapshots `business_keys` presence/full row before namespace-6/4 arbitration, then locks the parent record followed by the child and rejects any changed snapshot as `LOCK_PLAN_STALE` before replay or DML. A focused actual database-reviewer pass found no BLOCKER/MAJOR, including serialization with the legacy parent-first route. Current migration 027 SHA-256: `51CA4C23B9BF85B73773CB38EC8FDFFE23AB74AA02D4884307B9C1F4B19BF359`; source `027:8305-8342`; qualification prerequisite `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:290-292`. This is source-only: no SQL parse/install, effective-ACL measurement, runtime qualification or test ran. `S13-DECLARE-BUSINESS-KEY-01` remains `NOT_RUN`. Accountable owner: operator; executor: Codex. Next: complete remaining source closure, then run mapped qualification only in the approved disposable lane while keeping additive routing/grants disabled.

2026-10-25 S13 budget-plan closure: `declare_budget_v1` now compares complete pre-fence `records` and `grants` composites after taking sorted namespace-6 grant/record IDs and locking grant before record. Any changed present row refuses `LOCK_PLAN_STALE`; an unchanged missing grant retains legacy `BUDGET_EXCEEDED`. An actual focused `database-reviewer` source pass found no BLOCKER/MAJOR in composite comparison, absent-grant semantics, order, or unchanged-path error precedence. `budget_admin_v1`/`budget_revoke_v1` also passed focused source review; however, a mixed legacy/v1 explicit grant-ID first-insert race is not covered until atomic caller/ACL cutover, so candidates remain ungranted and the feature flag stays off. Current migration 027 SHA-256: `3BC38F63C69C592E11FDD5C5EA783C814911834154EDB399EDA5ECD464DD2926`. No SQL parse, tests, migration or DB operation ran; `S13-BUDGET-ADMIN-01`, `S13-BUDGET-DECLARE-01` and `S13-BUDGET-RANK-01` remain `NOT_RUN`. Accountable owner: operator; executor: Codex. Next: finish candidate coding and caller/grant cutover map before disposable qualification.

2026-10-25 S13 verifier-key lock-rank correction: migration 027 registration, approval and revocation candidates take lifecycle, exact legacy material advisory identity and namespace-6 key-ID fence before verifier row work. The reviewer found one MINOR: `revoke_verifier_key_v1(NULL)` failed while building the namespace-6 key, unlike legacy's authorized no-op; added return after transaction/scope/operator checks, and focused follow-up confirmed no issue. No BLOCKER/MAJOR in the reviewed source slice. Current migration 027 SHA-256: `3BF87F1989953A0124AC6FA2CC4263CA991C1FDA6788FE85B4851F9B1844A7D0`. Candidate functions remain ungranted; legacy grants are reachable; registration/approval/revocation races, cutover, and effective ACLs remain `NOT_RUN`/`NOT_VERIFIED`. Accountable owner: operator; executor: Codex. Next: keep v1 disabled until complete registry caller/ACL cutover is proven, then run `S13-REGISTRY-RANK-01` in disposable DB after coding closes.

2026-10-25 S13 target-observation error precedence: `observe_target_v1` previously rejected a NULL token/fingerprint before the legacy token lookup. The candidate now lets NULL/missing token follow the lookup-miss `TICKET_SUPERSEDED` branch and validates class/fingerprint only after locking and confirming current-generation `ISSUED`, preserving 005 source order. A focused database-reviewer follow-up found no remaining issue; lifecycle `NOT_READY`/`RECOVERING` intentionally refuses before token lookup per candidate acceptance. Current migration 027 SHA-256: `F524AD655C42DD64676366D942A2C79177C1F6DCCB2F60F94E49BA72272ED77F`. Candidate remains unparsed/uninstalled/ungranted; `S13-OBSERVE-REPLAY-01` is `NOT_RUN`, effective grants `NOT_VERIFIED`. No test/parser/DB/migration action ran. Accountable owner: operator; executor: Codex. Next: continue source closure before functional/E2E qualification.

2026-10-25 S13 recovery eligibility report: static reconciliation found a conflict between `S13-RECOVERY-ELIGIBILITY-REPORT-01` and the generic `RECOVERY_NOT_READY` guard: a stale-epoch row is deliberately exposed by `has_more_eligible` for separate `revoke_stale_v1`, but the guard prevented the required successful zero-work sweep report. Removed that guard for this already implemented separate queue and clarified the adjacent recovery acceptance criteria. `recover_sweep_v1` still performs no stale revocation; it reports `has_more_eligible=true` and records its own zero-work run, while `revoke_stale_v1` retains the actual mutation. Static source inspection only; no SQL parse, test/check, migration, database operation, COM, stage, commit or push ran. Candidate SHA-256 after this edit is recorded in `docs/commits/2026-10-25-s13-recovery-eligibility-report.md`. The explicit stale-only and restored-dependency scenarios remain `NOT_RUN`.

2026-10-25 WP0 Ivan read-only refresh: strict-host-key SSH to `koros@100.88.71.74` returned all nine `run-mcp-stack.ps1 -Action Status` components True and `dir /b D:\1c\mcp` returned only the expected stack folder/script names. No restart, secret read, COM activation, base open or write. Current 1C base identity, DPAPI signer and live effective rights remain NOT_VERIFIED. Evidence is appended in `WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-25.md`.

2026-10-25 S13 stale-epoch reporting / kill-switch gate: direct `recover_sweep_v1` now returns a zero-work run with `has_more_eligible=true` when stale epochs are the only separate `revoke_stale_v1` queue. A source review found that reusing that deferred report in `kill_switch_v1(OFF)` previously committed a blocked run/event despite §644 requiring `RECOVERY_NOT_READY` with no delta. The OFF wrapper now raises before state or queued-event writes, rolling back the nested run. The same actual source reviewer confirmed the MAJOR is closed. Candidate remains unparsed/uninstalled/unqualified; both runtime cases remain `NOT_RUN`; effective installed grants are `NOT_MEASURABLE`. No test/check/parser/migration/DB/COM/stage/commit/push ran. Candidate SHA-256 and detail record: `docs/commits/2026-10-25-s13-recovery-eligibility-report.md`.

2026-10-25 S13 T12 first-pass isolation: source review found that an old `APPLY_UNKNOWN` row without a RESOLVE counter could derive an already-due deadline and attempt/triage during the same pass that initialized the counter. Migration 027 now counts a successful new counter once, skips both attempt and window-triage branches for that first pass, and clears a prior T12 failure row on successful initialization; later passes may attempt/triage. A focused actual source-review follow-up confirmed both branch gates and failure rollback/cleanup. Model/effort metadata `UNKNOWN`. Candidate remains unparsed/uninstalled/unqualified; `S13-RECOVERY-T12-RANK-01` is `NOT_RUN`. Source snapshot SHA-256: `C29006394CD0431D213AC193AA64828286CB6B5B2AFA2EE2FBDA10C9B2CAEAAB`; detail: `docs/commits/2026-10-25-s13-t12-first-pass-isolation.md`.

2026-10-25 S13 GAP_BOUND eligibility report order: when only the `ANCHOR_GAP_BOUND_EXCEEDED` announcement was missing, the stage queued it but calculated `has_more_eligible` before the append, returning the just-repaired hold as still eligible. Direct GAP_BOUND now appends queued events after its `sweep_runs` row and before recomputing eligibility; deferred kill-switch calls retain the queue for the parent decision. An actual read-only `/root/recovery_event_sink_review` follow-up found no concrete issue and confirmed no double append, transaction-mode change, or namespace-1 order regression. Model/effort metadata `UNKNOWN`; runtime remains unproven. Migration 027 SHA-256 `1B5B2D2BAD8DC17CD130D95AB46ED851ACD36C3C7CB3E5B2023B75206EAC0724`; detail `docs/commits/2026-10-25-s13-gap-bound-report-order.md`. No parser, tests/checks, migration, DB write, COM, staging, commit or push ran; qualification `NOT_RUN`.

2026-10-25 S13 GAP/T3/VOID/T9/nonce source review: actual read-only recovery-stage review found no concrete finding. It confirmed GAP captures every related parent and full overdue-hold snapshot, keeps NULL hold parents in the hold set without a parent edge, and revalidates before DML; T3/VOID/T9 item exceptions restore event queue, changed count and success arrays; T3-to-VOID overlap follows the documented serial outcomes; T9 rejects duplicate selected bases before row locks; nonce expiry locks owning records before nonce rows; aggregate effect cap matches the accepted per-item maxima. Source anchors recorded in the reviewer result and the qualification sections; no runtime inference. Reviewer model/effort `UNKNOWN`; all these recovery cases remain `NOT_RUN`.

## 2026-10-25 private-writer nonzero UUID boundary

Source inspection found that canonical all-zero ticket UUIDs could pass `_identity`, be durably admitted and marked invoking, then be rejected by `InvocationContext`. The service rejects nil change/call/permit/repair IDs before admission, and `CallIdentity` independently rejects them. The same contract covers store-returned dispatch-CAS IDs, barrier IDs before read/close/recovery, barrier snapshots/origins/call sets, and UUID text decoded by `PostgresAdmissionStore`. SQL security-definer write entry points now reject nil IDs before admission, begin-apply, permit issuance, and barrier close/finish; candidate tables check nonzero dispatch identity and canonical process-instance UUIDs; startup rejects noncanonical instance strings. `PostgresAdmissionStore` validates process-instance and typed dispatch-CAS/barrier/event UUIDs before corresponding SQL calls, validates barrier-finish input snapshots, and strictly decodes active owners, barrier origins, startup instance and readiness references. Candidate table checks also reject nil non-NULL serving-readiness and evidence-projection UUIDs while retaining nullable semantics, constrain non-NULL evidence process IDs to the SQL UUID format, and classify malformed trust-snapshot process IDs as `TRUST_SNAPSHOT_REQUEST_INVALID` before binding reads after authentication. `TrustedProcessBinding` and `TrustSnapshotRequest` enforce the same RFC version/variant pattern. Service/store hashes: `service.py` `EBF2C8F2F61FBFB2C7DEAA687D14CC4A585FA0730FB8A072DC368666D9E15E0A`; `postgres_store.py` `E2F76BE618323E80A493CA3689695E1D4F9D160210D04A1D8E414B6EF36C6BBE`; `evidence_trust.py` `580FBB1D5C39B9BBEFBE788C36F6D5272802C7496063F8BB8B2D9F76D0BA2038`. Candidate SQL SHA-256: `4EC3076ADA998AA8D80BB14FD15C980E4B0A225D7BA92AE3CA4AACC54771E49A`; it is unparsed/uninstalled. No tests/checks/build/runtime dispatch/database/COM operation ran. Detail record: `docs/commits/2026-10-25-s13-private-writer-nil-uuid-admission.md`. Continue source closure across the Python/SQL UUID boundaries; after code closes, functional-test-reviewer and e2e-runner own nil-ID rejection, malformed owner/barrier/startup responses, nullable evidence-projection checks, and valid UUID controls, with Python and database review.

2026-10-25 S13 evidence UUID ingress follow-up: `PostgresEvidenceAttemptSource` now rejects nil CAS/call selectors before read-only SQL and rejects nil dispatch-intent/optional repair UUIDs in decoded attempt context; `PostgresWriterReceiptRegistrar` rejects nil CAS IDs before verifier/source work. Hashes: `postgres_attempt_source.py` `80C0B03933F158FC3DD03AEA5EF016F52FE79B49ABD61F482C09FDB923C21583`; `postgres_evidence_registrar.py` `5F439A88DBD55857E59FBF0995A2DD718125798E11C6DC5419C0059DE99F37F4`. No tests/checks or runtime evidence; malformed and valid-control cases remain `NOT_RUN`. Owner: operator accountable; Codex executor. Next: finish cross-boundary source closure, then assign evidence-ingress cases to the functional/E2E roles after coding closes.

2026-10-25 S13 process UUID consumer alignment: `PrivateWriterService` validates startup/current-call/admission/recovery owners, barrier origins and barrier-ack writer process IDs with canonical lowercase UUID version/variant bits; non-NULL startup readiness refs require canonical nonzero UUID syntax. `PostgresWriterReceiptRegistrar` rejects malformed process IDs before parsing or source lookups. Candidate SQL 027 applies the same UUID pattern at direct startup/admission/invocation/terminal/recovery/barrier entries and refuses malformed non-NULL evidence process projections before attempt/key reads, preserving allowed NULL projections. Qualification row `S13-PROCESS-UUID-CONSUMERS-01` captures collaborator call counts, direct SQL zero-delta/read-order cases and positive controls; all remain `NOT_RUN`. Hashes: `service.py` `BC5DE9BB99653036CC18EEEB742F3526248B633C179EF188D36EF7657E74E17A`; `postgres_evidence_registrar.py` `FBB37D653F3D8CF7685DE47A7D2A2F3CE1C957B27D7D96E26F37BD23FB144475`; candidate SQL `F53623131EC07C61A4DFF7367BC259B861FD764A0B8D79BEDAF8664517F0E0A3`. No tests/checks, SQL parse, DB/migration or COM activity. Owner: operator accountable; Codex executor. Next: continue accepted source closure; only after coding closes hand these cases to functional/E2E and relevant Python/database reviewers.

## 2026-10-25 S12/S13 shared Python UUID predicates

Added `change_ledger.uuid_contract` with separate canonical-nonzero UUID and process-instance UUID predicates, then routed the invocation context, private-writer service, PostgreSQL store, evidence-attempt source, evidence registrar, and trusted process snapshots through them. Generic IDs remain version-agnostic; process IDs require the SQL-aligned lowercase RFC variant/version 1–8 form. Invocation-context ticket/permit comparison now rejects uppercase, braced, compact or other noncanonical equivalents instead of normalizing them; `S13-INVOCATION-CONTEXT-BINDING-01` captures this case. Existing stable error codes and validation order were preserved. The source/design note is `S13_PYTHON_UUID_CONTRACT_2026-10-25.md`; detail record 171 captures the paths and review. Actual read-only `code-reviewer` passes (GPT-6 Luna, low effort) found no BLOCKER/MAJOR; this is source review, not runtime parity proof. Hashes: shared module `2C913B39D9163186AD932754D75652D938B075C13D1FF1D4B39057A1B215A081`; `service.py` `526C55C567ECDD6D68AD514367DE19D6AA8FABBE7A40166487A7C41219A35428`; `postgres_store.py` `78B8097B79F0F6BF360B3EB34184373CD0E4BD1CC5F8986AF98BA82A0CF6DEC5`; `postgres_attempt_source.py` `7CB5D295339A3EF0D92EBF17D1F2BF24BC4CE2246C8421BA22471D7D9BD2F46B`; `postgres_evidence_registrar.py` `C1F6A22EDF9E6BEEB7EBAFBB1E951C349491E77CC3B384D095EC6421A227DADF`; `evidence_trust.py` `A3DE84442471B603562F3B7CC49A7C03EFE31725F32039369847649B7D84BF9C`; `write_port.py` `40D9C015DECA4D2DEFF1A20F4621BA54D0274A098E4A5069AAB31B64A8C374F5`. No tests, checks, SQL parsing, database/migration, COM, staging, commit, or push. `S13-ADAPTER-UUID-01`, `S13-INSTANCE-UUID-01`, `S13-EVIDENCE-UUID-01`, `S13-PROCESS-UUID-CONSUMERS-01`, and `S13-INVOCATION-CONTEXT-BINDING-01` remain `NOT_RUN`. Continue the remaining source-level FK/unique-arbiter/trigger/effect and cutover caller-map closure; only after code closes, hand to functional/E2E, database, and Python review.

### Follow-up — malformed trust-snapshot list element

`TrustSnapshotRequest` now checks that every process-ID tuple element is exactly `str` before duplicate detection uses `set()`. This maps both hashable and unhashable wrong types to `TRUST_SNAPSHOT_REQUEST_INVALID`, before pool acquisition or database reads; duplicate canonical strings and valid controls retain behavior. Actual code-reviewer follow-up (GPT-6 Luna, low effort) found no issue; no tests/checks ran. Qualification row `S13-TRUST-REQUEST-SHAPE-01` was added and remains `NOT_RUN`. Current hashes: `evidence_trust.py` `0B7A97968215667817C5E657B6495255CFBB970BDF77B1179823FCBE9290B201`; prerequisites `BB300B093C8459C2F16170EBEE4668D8E0C6F3CE663183D8ECBF189BB14318C1`.

## 2026-10-25 S13 signed witness-cosign candidate

Added ungranted `witness_cosign_signed_v1` to migration 027 and routed the `SqlChangeLedger` call only under the explicit S13 schema flag. The candidate fences scope/lifecycle plus the preallocated record, evidence and cosign IDs; derives the exact retry envelope from the immutable signed completion evidence; scopes replay lookup to the record's tenant/company; requires recovery-witness capability for a new cosign; and locks/revalidates the record before its permit child and explicit-ID insert. A preflight and partial unique index prevent duplicate historical/current signer-session-evidence identities without rewriting rows. Candidate EXECUTE remains revoked; the legacy default route remains selected unless the explicit schema flag is enabled. `S13-WITNESS-COSIGN-REPLAY-01` remains `NOT_RUN`; no parser, migration, test/check, database write, COM, stage, commit or push ran. Code hashes: migration 027 `603800C1372EF52BCD000984778D1D3B8CA839244AAAAE9647925D6F3643E57B`; `sql_ledger.py` `23371C504097470D1327BC2D9D40852BA8FEF2E753B0A4BC70366AFF359B3798`. Detail record: `CHANGE_RECORD_172.md`. Next: source-close the remaining cosign/parent/unique-arbiter and caller/ACL routes, then run the focused database/security review after code closure; functional/E2E qualification follows only after the code phase closes. Accountable owner: operator; executor: Codex.

## 2026-10-25 S13 cosign parent-lock and replay candidates

Superseding the witness-only entry above: migration 027 now contains ungranted `witness_cosign_signed_v1` and `anchor_gap_cosign_v1`, with both routes available only behind the explicit private-writer schema flag. The witness candidate preallocates its ID, fences record/evidence/cosign IDs, scopes the replay lookup, compares the immutable evidence-derived proof, requires recovery-witness capability for new submissions, and snapshots/locks/revalidates the parent record before the permit child and insert. The anchor candidate preallocates/fences hold/cosign IDs, snapshots and locks the hold parent, derives replay identity from canonical JSONB evidence, checks exact replay before the open-hold requirement, and refuses digest collisions with different evidence. Both have duplicate-preflight plus partial unique index protection and explicit revokes; neither has an application grant. `S13-WITNESS-COSIGN-REPLAY-01` and `S13-ANCHOR-GAP-COSIGN-REPLAY-01` remain `NOT_RUN`. No SQL parser, tests/checks, migration, database operation, COM, stage, commit or push ran. Hashes: migration 027 `F4DF04257466438DABFE6E6BE00CFD0A989F570B0218FDFA65A8C15C3820E52F`; `sql_ledger.py` `27935E958F21019A7AF2F6EBBACA2D50DECE8F4A1474E089882C7831D32FC8CD`. Detail `CHANGE_RECORD_172.md`. Next: finish remaining source lock/trigger/unique-arbiter and caller/ACL closure before focused database/security review; functional/E2E qualification follows after code completion.

### 2026-10-25 witness call-state gate refinement

A source crosswalk follow-up tightened the new `witness_cosign_signed_v1` path: a new cosign now
requires the record to remain `TRIAGE_REQUIRED` and an unreleased `CALL_OWNERSHIP` hold. The
candidate snapshots that hold before namespace-6/namespace-3 arbitration, re-reads it after the
fences, then locks/revalidates it after the parent record and permit rows. Exact replay remains
lookup-only and does not require the call/hold to remain unresolved. Candidate migration SHA-256:
`C3D5E2C3829D951DF9B08F4D685CE67C7510FED725AD6CFB5079A877EF8560DA`. No parser, tests/checks,
installation, grant, or runtime operation was run.
### 2026-10-25 S13 T17 failed-verification closure candidate

Migration 027 now defines the ungranted `operator_close_failed_verify_v1` candidate and
`SqlChangeLedger.operator_close_failed_verify` selects it only in explicit private-writer-schema
mode. It plans the current record and any competing target-lock owner parent, then freezes/revalidates
the open halt, cosign, reservation, owned target locks and owned key locks. Ranked fences precede
row locks; closure effects preserve the historical `FAILED_VERIFY` record, reject refunding a
known effect, retain a present-effect reservation, release an absent-effect reservation, consume
the two-person cosign, insert one immutable closure, and append the event last. Its rank sequence
is namespace 7/lifecycle → sorted namespace 6 → the matching `FAILED_VERIFY_HALT` namespace 3 →
signed-sorted namespace 4 → canonical parent/resource row order. Exact candidate
EXECUTE is revoked from every runtime/private role; no grant, SQL parse, migration, test/check,
database operation, COM, staging, commit or push occurred. `S13-CLOSE-FAILED-VERIFY-01` remains
`NOT_RUN`; installed grants remain `NOT_VERIFIED`; the canonical FK-SCC sibling order and races
against repair/retry/cosign/hold writers remain open. Candidate SHA-256: migration
`A8B1BC3BC839F54AA11F33EDB8350EF457308FF6F338BE7DB764451CF00C37B2`; adapter
`CF0E2CE57AE9CE42B583F7FFF69E716EF7D98F7E9AF621E6DC12696154D7D730`. Detail:
`CHANGE_RECORD_173.md`. A current-turn database-reviewer pass found one tautological target-lock
snapshot predicate; it was fixed and focused recheck found no remaining source defect in this
reviewed slice. A focused follow-up confirmed the namespace-3 key matches existing recovery paths,
rank 6→3→4 is retained, and target rows align with the locked-parent plan; no additional concrete
source defect was found. Reviewer model/effort metadata are unknown.

### 2026-10-25 S13 checkpoint permit-signature attachment candidate

Added an additive `attach_permit_signature_v1` candidate to migration 027 and routed the existing
checkpoint adapter to it only when the explicit S13 schema flag is enabled. The candidate applies
the scope/lifecycle fence, change-ID namespace-6 lock, parent-record-before-permit-child row order,
full-row stale-plan revalidation, and active ED25519 checkpoint-key/signature verification against
the persisted permit digest. Its exact EXECUTE privilege is revoked from every runtime, private
writer and evidence-ingest role; no grant or schema enablement was added. The S12/S13 disposable
qualification note now records lifecycle/key-revocation races and exact update effects as
`NOT_RUN`. No parser, tests/checks, migration, database operation, COM, staging, commit or push ran.
Detail: `CHANGE_RECORD_174.md`. Next code gap remains `operator_resolve_v1`; do not route its legacy
caller booleans in S13 mode. Its immutable receipt/completion/outcome and T16 evidence contract is
specified in `S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md` under `operator_resolve`.

### 2026-10-25 T16 conditional-conflict witness cosign candidate

Extended the ungranted `witness_cosign_signed_v1` candidate so a new `APPLY_UNKNOWN` cosign requires
the exact generation's DISPATCHED permit, its POSSIBLY_EXECUTING attempt, a linked ENTERED /
CONDITIONAL_VERSION_CONFLICT receipt, and the same attempt's CompletionProof projection linked to
the public evidence ID. Namespace 6 now fences call/CAS/receipt/completion identities; the path
locks and revalidates record → permit → attempt → open call hold before inserting only the immutable
cosign. It does not resolve the outcome, consume the cosign or release resources. The exact route
remains revoked. A read-only database-reviewer pass (GPT-6 Luna, medium effort) found no concrete
BLOCKER/MAJOR in this slice and confirmed the public/private proof class enums must not be compared
directly; the immutable ID/CAS linkage remains. Qualification is `NOT_RUN`; no tests/checks, parser,
migration or DB operation ran. Detail: `CHANGE_RECORD_175.md`. Next: implement `operator_resolve_v1`
for both frozen triage and exact conditional-conflict branches, with post-commit checkpoint/readback.

### 2026-10-25 typed T16 adapter precursor

Added the opt-in `SqlChangeLedger.operator_resolve_s13` signature for immutable receipt, completion,
outcome, cosign, CAS and paired challenge/read-attestation references. It validates UUID/reference
shape, never falls back to legacy caller booleans, and requires a JSON result containing a terminal
state and event UUID. The SQL function is not implemented yet, so the method remains dormant and
`S13-OPERATOR-RESOLVE-01` remains `NOT_RUN`; no database function or grant is claimed. A read-only
`python-reviewer` pass (GPT-6 Luna, low effort) found no concrete adapter issue. No tests/checks,
parser, migration, DB/COM action, staging, commit or push ran. Detail: `CHANGE_RECORD_176.md`; adapter
SHA-256 `7B7A6932195342B6B4ECCFB1DF0F2C701F59610FCB09440E44C6BCFE734578FA`. Next: implement the
versioned SQL resolution and a post-commit exact-event checkpoint continuation that leaves an
effective stop-effects hold until read-back.

### 2026-10-25 current-turn T16 checkpoint continuation

The typed T16 SQL candidate and composite `DispatchGate.resolve_t16_s13` path now
exist in source. The SQL candidate inserts one scope `ANCHOR_GAP` hold per bounded target base in
the same transaction as `OPERATOR_RESOLVE`, keeps the call hold open, and replays the exact event
by cosign/evidence tuple before checking holds or rebuilding a bounded target plan. The
`release_hold_v1` branches now explicitly refuse an unlinked `CALL_OWNERSHIP` hold and require an
exact verified REAL checkpoint for a T16-linked call/anchor hold. `record_checkpoint` reuses an
exact already-verified row; the Python checkpoint gate accepts an ambiguous sink write only after
exact signed read-back. Canonical nonzero UUID output validation is applied at both SQL-adapter
and checkpoint boundaries. These fixes are source-only; migration 027 remains candidate and
ungranted.

Read-only SSH from the current executor to `koros@100.88.71.74` with
`StrictHostKeyChecking=yes` succeeded. `run-mcp-stack.ps1 -Action Status` reported all nine
components true: postgres, redis, apache, proxy8191, proxy8192, proxy8193, sidecar, idp, gateway.
`cmd /c dir /b D:\1c\mcp` returned only names; no config or secret contents were read. No service
was restarted. This confirms current host-stack connectivity only; it does not qualify the private
writer, database grants, COM, checkpoint provider, local 521.1 read or S12/S13 behavior.

Source-only review also corrected a `release_hold_v1` branch-nesting defect that could have let an
unlinked `CALL_OWNERSHIP` hold reach the update path. No SQL parse, tests/checks, migration,
database query, COM, stage, commit or push was run for the current changes. Exact code and scope
are recorded in `CHANGE_RECORD_177.md`; runtime acceptance remains `NOT_RUN` and effective grants
remain `NOT_VERIFIED`. Next coding priority: complete the private-writer evidence and composition
surface without adding an unapproved checkpoint provider or enabling the S13 selector; then finish
all source coding before delegated functional/E2E qualification and specialist reviews.

### 2026-10-25 private writer composition root

Added `src/erp_mcp_private_writer/runtime_composition.py` and package exports. The factory requires
Windows, the private-writer PostgreSQL pool, an injected non-skeleton writer port, host/base
bindings, the Windows service SID, and all barrier/receipt/outcome evidence interfaces; it composes
the current store, host authority mutex, and coordinator. `PostgresOutcomeEvidenceProvider` now
accepts exact three-record success or five-record conditional-conflict bundles from an injected
locator under a bounded deadline and delegates trust validation and immutable registration to the
existing registrar; it does not treat the locator as an authority. `T16RecoveryCoordinator` now
retains that verified evidence-reference set and orders the authorized T16 event, exact checkpoint
read-back, and the separate physical-writer terminal transition without invoking COM. An ambiguous
final response is resolved by exact private-writer lookup before any retry. Construction performs
no DB/COM call, startup epoch claim, listener startup, or public gateway registration.
`prepare_to_serve` remains an explicit future process action after the installed schema and durable
recovery prerequisites are qualified.
Identity provenance, locator/trust/build-attestation providers, operational writer, listener
authentication/ACL, process supervision, effective grants, and runtime behavior are still open or
`NOT_VERIFIED`. Detailed current-turn record: `CHANGE_RECORD_178.md`. No tests/checks, parser, build,
migration, DB, COM, service restart, listener, staging, commit, or push was run. Next coding
priority: continue the private writer's concrete evidence resolution and COM-operation surface from
the accepted S12/CT14 contracts; do not invent the external checkpoint or trusted identity
providers. Complete all source coding before functional/E2E qualification.

### 2026-10-25 S12 manifest digest primitives

Added `src/erp_mcp_private_writer/com_manifest.py`: immutable value-hash assignments and separate
domain-separated S12 property/COM-operation manifest digests. The property digest preserves ordered
property and tabular-section changes and binds write mode/property-setting method; the operation
digest binds operation, method, write mode, target and expected version. The code does not map
`DraftPayload`, discover 1C metadata, validate configuration provenance, invoke COM or authorize a
write. The current CT14 record explicitly lacks a canonical payload-to-property crosswalk, so the
historical copied-document trace is not wired as the mapping. See `CHANGE_RECORD_179.md`.
No tests/checks, parser, build, DB, migration, COM, restart, listener, staging, commit or push ran.
Next code remains to bind a reviewed authenticated clone mapping and implement its concrete COM
adapter without enabling dispatch until the mapping and atomic precondition are qualified.

### 2026-10-25 private ingress source candidate

Added `private_auth.py` and `private_ingress.py` plus `CHANGE_RECORD_181.md` and
`CHANGE_RECORD_182.md`. The private auth candidate pins JWT audience
`urn:erp-mcp:private-writer`, scope `erp_mcp:private_writer`, and a non-empty exact client allowlist;
the ASGI candidate exposes bounded loopback-only dispatch and lookup routes, rejects duplicate
headers/JSON keys, and never starts a socket. No test/check/build, listener, service, DB, migration,
COM, staging, commit or push ran. Exact ticket/permit and COM checks remain the writer port's duty.
Manual source review found that `PrivateWriterService.lookup()` checks identity shape but does not
enforce caller/tenant ACL. `CHANGE_RECORD_183.md` records the current source correction:
`ConfiguredPrivateWriterAuthorizer` binds each verified OAuth client-ID/subject pair to exact
tenant/company/organization/base-fingerprint grants; dispatch also invokes the trusted ticket/permit verifier, while historical
lookup relies on the exact persisted identity and remains available after permit expiry. This is not
provisioned or qualified runtime authorization. Continue the reviewed clone mapping and concrete COM
adapter; do not enable the app until IdP/grant provenance, effective installed grants, startup
recovery, and disposable qualification are complete. After all code is complete, launch only
`functional-test-reviewer`/`e2e-runner` for mapped acceptance cases, then relevant specialist
reviews. No commit is ready until GPT-PM reviews its exact diff; use the canonical `ERP_MCP` repo
binding, not the wrong project conversation `ERP`.

### 2026-10-25 private-writer measured line-count enforcement

Change record 188 closes a source omission in change 186: `parse_writer_payload()` now applies
`MEASURED_SHAPE_MAX_LINES` after typed `CREATE_DRAFT` parsing and before returning the payload to
the private service. This enforces the shared one-line ceiling but does not qualify currency or
provide the missing payload-to-1C property crosswalk. Source inspection only; no test/check/build,
SQL parse, migration, DB, COM, service/listener, staging, commit, or push ran. Next code: continue
the exact S13 source lock/trigger/FK/effect closure. Keep the concrete COM adapter and any physical
write disabled until the authenticated clone mapping, writer identity, and atomic target-version
precondition are available and qualified.

### 2026-10-25 S13 T16/T17 witness independence

Change record 189 corrects candidate 027: `operator_resolve_v1` and the shared candidate
`consume_two_person_cosign` now refuse when the recovery witness is the current approver. The
operator may be the approver if the witness is distinct. This is source-only; no SQL parse, tests,
database operation, or disposable qualification ran. Candidate 027 remains uninstalled and the
routes ungranted. Continue the source-only FK/trigger/unique-conflict/effect closure; the COM map,
host identity and installed grants remain separate gates.

### 2026-10-25 S13 terminal cosign requester independence

Change record 190 adds the approver/requester `same_person` check to both terminal implementations:
T16's inline `operator_resolve_v1` and T17's `consume_two_person_cosign` helper. The helper is
explicitly owned by `ledger_owner` and revoked from `PUBLIC` and every named application/private
role so it cannot consume a cosign outside the protected T17 entry point. This keeps terminal
recovery fail-closed if an approval row predates or bypasses the current approval writer.
Source-only; no SQL parse, test/check, migration, DB or COM operation ran. Continue candidate
source closure; the schema remains unparsed/uninstalled/ungranted.

### 2026-10-25 S13 target-plan and private-ingress follow-up

Change record 213 updates `private_writer_open_hold_v1` and `check_anchor_v1` to compare full
target-row snapshots after ranked locks; the open-hold helper now refuses a null base before
`assert_scope`. Change records 214–215 bind the private-ingress loopback Host IP/effective port to
the actual ASGI server endpoint and reject exponent-overflow floats during JSON decoding. The
qualification prerequisite now covers target status/epoch mutations, mismatched loopback endpoint
values and non-finite JSON values; all remain `NOT_RUN`. Candidate SHA-256 values: SQL 027
`04985D4708F5B5ADF81D0C4A88EECA6F6515145CEF96F2272AFFBB9F58A3FFD7`; private ingress
`2BAE3A9484414054D00BC9E92DB1578B9F9D06934C496A53D798259CF88A1942`. No SQL parse, tests/checks,
build, migration, database operation, COM activation, staging, commit or push ran. Continue the
source-level lock/FK/trigger/effect and ACL/caller closure before functional/E2E and specialist
reviews. Keep the private listener, COM writer and S13 selector gated until their separate
identity, effective-grant and disposable-qualification evidence is complete.

### 2026-10-25 S13 private-ingress proxy-header closure

Change record 216 rejects `Forwarded`, `X-Forwarded-*` and `X-Real-IP` headers at the private
writer boundary because trusted ASGI proxy middleware can rewrite `scope['client']` from those
caller-controlled headers. The `S13-PRIVATE-INGRESS-BIND-01` contract now requires this refusal
through the middleware path. Current `private_ingress.py` SHA-256:
`C688B13F9F108C13E4B73A8145B5714C2A57E627693E838B1AC2EBE0817C786F`; qualification prerequisite
SHA-256: `618DCA784D9065CAB9A0759FEA3C4FB35246438E565D2CD0656E0EDA298B0322`. This is source-only;
no tests/checks, runtime listener, migration, DB operation, staging, commit or push ran. After code
closure, assign middleware/header behavior to functional/E2E qualification and verify the actual
listener bind separately; keep private-writer enablement gated.


### 2026-10-25 10:59 UTC access and source checkpoint

Current strict SSH stack status returned all nine listed components `True`; local in-process `source_health` for `onec-818ha-reference` returned `is_error=false`, `ok=true`. The separately repeated PostgreSQL 18432 catalog check found no candidate schema/roles/functions, so S13 effective grants remain `NOT_MEASURABLE`, not denied. Exact current-turn output and limits: `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-25.md` and `docs/phase2/artifacts/WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-25.md`. Keep using strict SSH and the local in-process MCP path; do not restart the stack or use the ERP_MCP_REAL1 connector for this verification.

Change records 216-218 add private ingress rejection of forwarded peer metadata and a 30-second immutable barrier-wait configuration. Current `private_ingress.py` SHA-256: `C688B13F9F108C13E4B73A8145B5714C2A57E627693E838B1AC2EBE0817C786F`; current `service.py` SHA-256: `27F95F216030067CBF65CB5D43A3503F53D2CE87BF933BCDFBE922D01A850768`. These remain source-only; no tests/checks/build, listener startup, migration, DB write, staging, commit or push ran.

The in-scope CT14 project records `testlane/onec_extension/STATUS.md` (2026-10-12, sections 4–7) and `docs/phase2/CT14_FEASIBILITY_SPIKE_2026-10-12.md` document historical effective rights on disposable clone `818HA_p2diff`: `CT14_NARROW` with `CT14Писатель` plus `ЗапускВнешнегоСоединения`, 53 objects/13 rights, no Delete/interactive/admin rights, and measured create-draft/post/read-movements/unpost behavior. The same source records marker attributes as mutable by API writers with document Update. This is not a fresh Ivan-host rights observation or proof of COM transaction semantics. Fresh strict SSH at 10:59 UTC showed the nine service components True but only via `-Action Status`; current local MCP source health was `ok=true`; S13 PostgreSQL grants remained NOT_MEASURABLE because candidate schema and roles were absent. See the dated WP0 and WP2 artifacts for exact evidence and scope limits.

Change records 217-218 bound the private-service barrier timeout at 30 seconds and make that timeout immutable after construction. `service.py` SHA-256 is `27F95F216030067CBF65CB5D43A3503F53D2CE87BF933BCDFBE922D01A850768`; the timeout acceptance row now requires exact-max and mutation/deletion cases. Runtime remains NOT_RUN.

Change record 219 freezes validated pool, timeout, and trust/source dependencies across the six bounded PostgreSQL evidence/admission adapters (`PostgresAdmissionStore`, `PostgresEvidenceAttemptSource`, `PostgresWriterReceiptRegistrar`, `PostgresEvidenceKeyResolver`, `PostgresEvidenceTrustSource`, `PostgresOutcomeEvidenceProvider`, and `ProductionEvidenceVerifier`). Qualification `S13-DB-ADAPTER-CONFIG-IMMUTABILITY-01` requires mutation/delete/re-add refusal and zero calls on refusal; all cases remain `NOT_RUN`. Continue source coding; once complete, functional/E2E roles and Python/database reviewers take the mapped qualification/review. No tests, database operation, migration, COM, staging, commit or push ran for this change.

Change record 220 freezes the four validated `ComStaLane` lifecycle callback references (`connect`, `disconnect`, `initialize_sta`, `uninitialize_sta`) without freezing mutable queue state. `S13-COM-STA-CONFIG-IMMUTABILITY-01` is source-only and remains `NOT_RUN`; no Windows COM or tests ran. Continue code closure, then hand startup/cancellation/drain/close and mutation cases to functional/E2E and Python/reliability review.

Change record 221 freezes the host serving mutex's verified name, process-local registry key, Windows API handles and kernel handle after construction. It preserves constructor cleanup before freeze and keeps only lifecycle state mutable. Qualification `S13-SERVING-MUTEX-CONFIG-IMMUTABILITY-01` remains `NOT_RUN`; Windows mutex/ACL runtime and tests did not run. Continue source coding, then assign the ACL/lease/failure-cleanup cases to functional/E2E and security/reliability review.

Change record 222 freezes validated `PrivateWriterService` dependencies and identity while preserving mutable lifecycle state and forbidding attribute deletion. `S13-SERVICE-CONFIG-IMMUTABILITY-01` remains `NOT_RUN`; no tests, PostgreSQL, COM, mutex, staging, commit or push ran. Continue source closure, then hand service construction/mutation and lifecycle cases to the required functional/E2E and specialist reviewers.

Change record 223 hardens `_WindowsLease`: fixed mutex/thread identity, no deletion or instance-dictionary bypass, and one-way release state. The serving-mutex qualification now includes post-release rejection and thread-affine single release. Windows runtime remains `NOT_RUN`; no tests/checks, PostgreSQL, staging, commit or push ran.

### 2026-10-25 S13 permit replay authorization correction

Change record 240 fixes a source-review MAJOR in `private_writer_issue_permit_v1`: a replayed binding
now rechecks locked current generation, `APPLYING` state, switch, target, registry and repair
authorization before returning, and returns only while the permit remains `PERMITTED`. Expiry by
timestamp alone does not invalidate an otherwise exact replay. A focused actual `code-reviewer`
recheck found no remaining issue and confirmed the fence/row-lock order and new issuance path were
unchanged. Candidate migration SHA-256 is `D61228FFDF8068874D4E741A5AF7CC829BE092E7A63303CE8A7B439104F489BE`;
the correction and scenario remain source-only, with SQL parsing, tests, installation and runtime
qualification `NOT_RUN`. Detail: `docs/phase2/CHANGE_RECORD_240.md`.

### 2026-10-25 T16 target-parent lock rank correction

Manual source review found that `operator_resolve_v1` acquired `targets ... FOR SHARE` before its
namespace-4 target-key locks. Moved the bounded target-parent lock/revalidation block after all
applicable advisory ranks and before child `records` locks; the disposable T16 criterion now
requires the lock trace to prove advisory-before-row and target-before-record order. This is a
candidate-only source correction: no SQL parsing, tests/checks, migration, DB operation, COM,
staging, commit or push ran. Migration 027 remains uninstalled/ungranted and the scenario remains
`NOT_RUN`. Detail: `docs/phase2/CHANGE_RECORD_241.md`. Next: continue all-path source closure; after
coding ends, assign the mapped T16 path to functional/E2E qualification and database review.

### 2026-10-25 T16 checkpoint/terminal-replay criterion correction

Aligned `S13-OPERATOR-RESOLVE-01` with the candidate's required split: SQL terminalization keeps
`CALL_OWNERSHIP` open and creates `ANCHOR_GAP` stop-effects holds; a separate post-commit signed
checkpoint plus exact read-back precedes hold release. Same-tuple terminal replay returns the
stored event lookup-only with zero delta; a changed tuple refuses. This corrects qualification
wording, not runtime evidence. No test/check/parser, migration, DB, COM, stage, commit or push ran.
Detail: `docs/phase2/CHANGE_RECORD_242.md`. Candidate remains uninstalled/ungranted; qualification
is `NOT_RUN`. Continue source coding and all-path lock/FK/trigger/effect closure before the
functional/E2E phase.

### 2026-10-25 S13 evidence tenant-scope correction

In candidate `db/phase2/027_private_writer_admission_schema.sql`, `operator_resolve_v1` scopes all five evidence pre-reads, five post-fence re-reads, and both verifier-material lock-plan scans by `tenant_id`/`company_id` as well as `evidence_ref`. Also scope dispatch-attempt hints by supplied identity and evidence references by attempt scope in `private_writer_record_terminal_v1`, `private_writer_attach_recovered_receipt_v1`, `private_writer_record_verified_success_v1`, `private_writer_record_recovered_not_invoked_v1`, and `private_writer_record_recovered_terminal_v1`; lock scans in the latter three use the same tenant/company predicate. A global evidence reference is not an authorization boundary; foreign-scope rows must not disclose evidence or influence signer-key lock acquisition. New disposable criterion `S13-WRITER-EVIDENCE-SCOPE-01` requires every wrong-scope evidence class in all six API paths to match the corresponding absent-reference sanitized refusal, with no foreign-row detail, no foreign-derived verifier lock, and zero row/event delta; a foreign-scope dispatch CAS must match an absent scoped CAS. Detail: `docs/phase2/CHANGE_RECORD_243.md`. Candidate remains unparsed/uninstalled; runtime qualification is `NOT_RUN`. Continue source closure; only after coding ends assign the functional/E2E test roles and relevant database/security reviewers.

### 2026-10-25 S13 COM STA lifecycle-field protection

`ComStaLane` now rejects ordinary assignment and deletion of `_state`, `_in_flight`, and `_thread` after initialization; the narrow internal setter enforces valid state transitions (with idempotent repeated-state cleanup), boolean in-flight toggles, and one-time worker-thread binding at the existing worker/lock-protected sites. `S13-COM-STA-01` now requires mutation/deletion refusal, valid/invalid/repeated transition cases, and zero callback, queue, or lane-state side effects on refusal. This is a current-turn source change recorded in `docs/phase2/CHANGE_RECORD_244.md`; the file's broader pre-existing worktree state was preserved. It remains source-only and does not resist deliberate same-process `object.__setattr__`, establish COM mapping or provenance, or make the writer operational. No tests/checks/build/CI, SQL parse, migration, DB operation, COM call, listener, stage, commit, or push ran. Next: continue the independent source-closure queue; keep functional/E2E and specialist qualification until coding is complete.

### 2026-10-25 S13 coordinator lifecycle binding protection

`PrivateWriterService` now freezes the `_base_dispatch_lock`, `_terminal_mutation_lock`, and `_pending_t16_resolution_calls` references after initialization, and its operation-to-writer-method map is read-only. Ordinary assignment/deletion of startup readiness, service epoch, startup-recovery snapshot, and active-quiesce task state is refused; validated internal transitions preserve exact types, positive matching epochs, clean readiness prerequisites, barrier-task identity, task completion before clearing, and idempotent repeated values. The restart-required latch retains its separate serialized update path. This is a current-turn source change recorded in `docs/phase2/CHANGE_RECORD_245.md`; broader pre-existing edits in `service.py` were preserved. `S13-SERVICE-CONFIG-IMMUTABILITY-01` remains `NOT_RUN`. No tests/checks/build/CI, SQL parse, migration, database operation, COM, listener, stage, commit, or push ran. Next: continue source closure, then qualify startup, barrier, lifecycle mutation, and cleanup cases with assigned test and review roles after code completion.

### 2026-10-25 S13 future signed-time refusal

Static contract reconciliation found that `ProductionEvidenceVerifier._check_signer` required a key to be valid at both the envelope time and trusted snapshot time but did not require the envelope time to be at or before the trusted snapshot. It now rejects `signed_at > validation_time` as `EVIDENCE_SIGNED_TIME_FUTURE`; both single-record and same-snapshot set verification use this shared check. The production-verifier prerequisite now requires refusal one time unit after the trusted time and acceptance at the exact-time boundary. This source-only fix does not replace the database key resolver's validity/revocation checks or registration-time recheck. Detail: `docs/phase2/CHANGE_RECORD_246.md`; verifier SHA-256 `A320C95C4EB71455B2F4BA251C28172F72226C42B104F8C82B5F3953841DCF0D`. No tests/checks/build/CI, SQL parsing, migration, database, COM, listener, staging, commit or push ran; `S13-PRODUCTION-EVIDENCE-VERIFY-01` remains `NOT_RUN`. Continue independent source/FK/trigger/effect and caller-map closure; after coding closure, assign its boundary and exact-time cases to functional/E2E and relevant Python/database/security reviewers.

### 2026-10-25 S13 trusted process PID parity

`TrustedProcessBinding.os_pid` now matches the candidate schema's signed PostgreSQL `integer` domain (`1..2,147,483,647`) and rejects booleans and overflow through exact built-in integer validation. `S13-TRUSTED-PROCESS-PID-01` records endpoint, invalid and overflow cases as `NOT_RUN`. This is a trust-model value check only; process identity, attestation, source authority and runtime evidence remain open. Detail: `docs/phase2/CHANGE_RECORD_247.md`; source SHA-256 `A27938D1695666A7D4A8E2963633D9E2D836CF60658863AA7AF214BD0F8D28FB`. No tests/checks/build/CI, SQL parse, migration, database, COM, listener, stage, commit or push ran. Continue the WP4/S13 source closure; qualify this model boundary after coding is complete.

### 2026-10-25 signer-role service separation

`EvidenceTrustSnapshot` now requires pairwise-disjoint service identities across writer receipt, verification worker, completion supervisor, read attestor, and checkpoint signer roles, while allowing absent role sets and retaining within-role key rotation. `S13-TRUST-ROLE-SERVICE-SEPARATION-01` covers every role pair and remains `NOT_RUN`. This source-only correction does not establish real service/host separation or key provenance. See `docs/phase2/CHANGE_RECORD_248.md`; source SHA-256 `B681641BCB4208C4BE47911D6ECB5BDCA23230C1D27FC46C81F5E47FBE6B188C`. No tests/checks/build/CI, SQL parse, migration, database, COM, listener, staging, commit, or push ran. Continue S13 source closure; run the mapped functional scenarios and security/Python review only after the coding phase ends.

### 2026-10-25 signer-role service separation

`EvidenceTrustSnapshot` and candidate `private_writer_load_trust_snapshot_v1` now reject service-identity overlap across writer receipt, verification worker, completion supervisor, read attestor, and checkpoint signer roles. `S13-TRUST-ROLE-SERVICE-SEPARATION-01` is source-only and `NOT_RUN`; migration 027 remains unparsed/uninstalled/ungranted, and this does not establish real authority or key custody. Detail: `docs/phase2/CHANGE_RECORD_248.md`. No tests/checks/build/CI, SQL parse, migration, database, COM, listener, staging, commit or push ran.

### 2026-10-25 14:31 UTC local source-health observation

A bounded authenticated local MCP call, using `LaneEnv.load()` and an in-process auditor token, returned `is_error=false`, `ok=true` for `source_health` on `onec-818ha-reference`. The token and accounting data were not emitted. This point-in-time observation does not establish Ivan clone rights, COM behavior, accounting reconciliation, S13 grants, or a physical writer boundary. Evidence: `docs/phase2/artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-25.md`. No service restart or write was performed.

### 2026-10-25 S13 epoch-writer legacy-name bridge

Migration 027 now atomically replaces the existing `bump_epoch`, `register_principal`,
`register_target`, `approve_registry_change`, `add_epoch_dependency`, `register_verifier_key`,
`revoke_verifier_key`, `enforce_registry`, and `propose_registry_change` caller bodies with SECURITY
DEFINER bridges to the existing fenced v1 routines. Legacy signature ACLs and return contracts
remain; direct v1 calls remain revoked. This addresses the identified mixed-route epoch snapshot,
verifier-key lock, and same-person proposal replay races at source level.
`S13-REGISTRY-LEGACY-BRIDGE-01` remains `NOT_RUN`; no SQL parse,
migration, DB operation or test ran. It does not close other registry/legacy lock edges or qualify
the migration. Detail: `docs/phase2/CHANGE_RECORD_249.md`. Continue aggregate S13 source closure.

### 2026-10-25 14:32 UTC Ivan stack status

Strict SSH using `BatchMode=yes` and `StrictHostKeyChecking=yes` ran the documented `run-mcp-stack.ps1 -Action Status`. Exit 0; all nine named components returned `True`. This is a point-in-time service-status result, not effective-rights, clone-identity, COM-writer, or transaction-boundary evidence. No restart or secret read occurred. Exact command and limits are recorded in `artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-25.md`.

### 2026-10-25 14:42 UTC Ivan directory inventory and claim bridge

Strict SSH performed a names/types-only listing of `D:\1c\mcp`; it returned the expected runtime
folders and stack scripts without reading contents. The exact command/output and a harmless local
quoting error on the first attempt are recorded in `artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-25.md`.
Migration 027 also bridges the granted legacy `claim` signature to `claim_v1` with a token UUID
allocated before the ranked lock plan. The old signature/ACL remains; direct v1 execution stays
revoked. `S13-CLAIM-PARENT-RANK-01` now covers both old-name and flag-on routes and remains `NOT_RUN`.
Detail: `docs/phase2/CHANGE_RECORD_249.md`. No test, SQL parse, migration, or database operation ran.

### 2026-10-25 S13 ordinary proposal legacy-name bridge

Migration 027 now routes the granted legacy `propose` signature through `propose_v1` after the
same transaction replaces the source-identified epoch/dependency/verifier/registry mutators with
fenced bridges. The existing signature/ACL remains; direct v1 execution stays revoked. The
`S13-REGISTRY-LEGACY-BRIDGE-01` scenario now covers old-name and flag-on replay plus global
`change_id` reuse across scopes. Candidate SQL SHA-256:
`45FF128E57FF7E294899D5808EB791CCB5A53B65EC605F19A10C620C1EA812EC`. This remains source-only;
SQL parsing, effective privileges, migration and race qualification are `NOT_RUN`/`NOT_VERIFIED`.
No tests/checks/build/CI, DB operation, staging, commit or push ran.
### 2026-10-25 S13 approval-family bridges

Migration 027 now routes the four granted old approval-family names (`issue_approval_nonce`,
`store_approval_text`, `approve`, `reject`) through fenced v1 entries in the same transaction. The
old signatures/ACLs remain; direct v1 calls stay revoked. Legacy calls preallocate a lowercase
64-hex nonce or UUID envelope/approval IDs before the candidate lock plan. Qualification
`S13-NONCE-LEGACY-BRIDGE-01` covers both route forms and remains `NOT_RUN`. Migration SHA-256:
`FB563CEF6194575DBC04EFF3CEC2A610E21F0F254777E64E5A1BAA78FF3B5448`. No SQL parse, migration,
tests/checks, DB call, staging, commit or push ran; effective rights are `NOT_VERIFIED`.
### 2026-10-25 S13 budget-writer legacy-name bridges

Migration 027 now preserves the granted `budget_admin`, `budget_revoke`, and `declare_budget`
signatures while routing their bodies through fenced v1 implementations. Old signatures/ACLs remain;
direct v1 calls remain revoked. This source-closes the previously recorded legacy/v1 first-insert
and grant-parent ordering split. `S13-BUDGET-LEGACY-BRIDGE-01` covers old-name and flag-on routes
and remains `NOT_RUN`. Migration SHA-256:
`DD98CD5025C6F7DA3CD4D7F414545AA85F0C2194B6AA4486DB680AD9D70E20AB`. No SQL parse, migration,
tests/checks, DB call, staging, commit or push ran; effective rights remain `NOT_VERIFIED`.
### 2026-10-25 S13 sweep-policy legacy-name bridge

Migration 027 now preserves the granted `set_sweep_policy(text,text,jsonb)` caller boundary as a
SECURITY DEFINER bridge to `set_sweep_policy_v1`; direct v1 remains revoked. The source qualification
covers old-name/flag-on merge, lifecycle refusal and event order in
`S13-SWEEP-POLICY-LEGACY-BRIDGE-01` (`NOT_RUN`). Migration SHA-256:
`D80747E50BD875192959B85F163930B534C385E346C618684CE988534F66C046`. No SQL parse, migration,
test/check, DB call, staging, commit or push ran.
### 2026-10-25 S13 duplicate-override legacy-name bridge

Migration 027 now preserves the granted `bind_duplicate_override` signature as a bridge to the
fenced v1 routine, so legacy exact retry is lookup-only and cannot append a duplicate event. Direct
v1 remains revoked. `S13-OVERRIDE-LEGACY-BRIDGE-01` covers both route forms and remains `NOT_RUN`.
Migration SHA-256: `A5F6793CF9F3DC97A41D4580E87DB3174C936C96441A121047EAB9422333956A`. No parse,
test/check, migration, DB call, staging, commit or push ran.
### 2026-10-25 S13 target-observation bridge

The granted legacy `observe_target` signature now routes through `observe_target_v1` in migration
027, preserving old caller/return behavior while preventing duplicate retry events. Direct v1 remains
revoked. `S13-OBSERVE-LEGACY-BRIDGE-01` covers both route forms and remains `NOT_RUN`. Migration
SHA-256: `B2DC518A5F4D2F52F148D631FDFD1BC64D5CB38951A671193ADA18E87CCA95DE`. No parse, migration,
test/check, DB call, stage, commit or push ran.
### 2026-10-25 S13 requester mutation bridges

Migration 027 now routes the granted `declare_business_key` and `declare_target_class` signatures
through their fenced v1 routines, retaining legacy defaults/ACLs and keeping direct v1 revoked.
`S13-REQUESTER-MUTATION-LEGACY-BRIDGE-01` covers both routes and remains `NOT_RUN`. Migration
SHA-256: `EAD14928E49E9112C40C39011185BC79F17B7F616108E6C93B25FBE7F5A34164`. No SQL parse,
migration, tests/checks, database operation, stage, commit or push ran.
### 2026-10-25 S13 writer-resource bridges

Migration 027 now bridges the granted `release_hold`, `cancel_permit`, and `renew_writer_lease`
signatures/defaults to their fenced v1 bodies while retaining old ACLs and revoking direct v1.
`S13-WRITER-RESOURCE-LEGACY-BRIDGE-01` covers both route forms and remains `NOT_RUN`. Migration
SHA-256: `A045D51E00173BCB45BFFD9596F15EA0223D2A8D89C60E745B6F688CC50DEB30`. No SQL parse,
migration, tests/checks, DB operation, stage, commit or push ran.
### 2026-10-25 S13 anchor/restart bridges

Migration 027 now routes the granted `declare_anchor_gap`, `declare_unclean_restart`, and
`check_anchor` signatures through fenced v1 bodies while preserving legacy ACLs and keeping direct
v1 revoked. `S13-ANCHOR-LEGACY-BRIDGE-01` covers both route forms and remains `NOT_RUN`. Migration
SHA-256: `7157041478217248DAB88D18D9AB91D574B229BDEE8730362F6EB61B699D9FA8`. No SQL parse,
migration, tests/checks, DB operation, staging, commit or push ran.

### 2026-10-25 legacy route-closure source progress

Migration 027 now preserves the active legacy signatures for dispatch receipt/payload verification,
checkpoint permit-signature attachment, operator kill-switch, operator-only revoke-change,
12-argument signed evidence, signed witness cosign, and anchor-gap cosign as SECURITY DEFINER
bridges to their fenced v1 bodies. The 10-argument evidence overload was removed in migration 007
and was not recreated. Direct v1 execution remains revoked. Static source inventory finds 40
old-name/v1 bridge pairs, including the earlier epoch/registry/proposal/claim/approval/budget/
sweep/resource/anchor families; this is not installed-ACL or runtime evidence. New criteria are
`S13-DISPATCH-RECEIPT-LEGACY-BRIDGE-01`, `S13-PERMIT-SIGNATURE-LEGACY-BRIDGE-01`,
`S13-KILL-SWITCH-LEGACY-BRIDGE-01`, `S13-REVOKE-CHANGE-LEGACY-BRIDGE-01`,
`S13-EVIDENCE-LEGACY-BRIDGE-01`, `S13-WITNESS-COSIGN-LEGACY-BRIDGE-01`, and
`S13-ANCHOR-GAP-COSIGN-LEGACY-BRIDGE-01`; all remain `NOT_RUN`. `record_evidence` compatibility
was reconciled against the actual migration chain: 007 drops its prior 10-argument form and the
active 12-argument contract carries generation/call ID. `operator_resolve` still needs the new
immutable evidence-reference contract and is intentionally not represented by a signature-only
bridge. Candidate migration SHA-256 at this point:
`121B770E6FB57255EEEA4DA05B398E28B4BD242253DA5E9456F737A9B4722F9F`. No SQL parse, tests/checks,
migration, database operation, staging, commit or push ran. Detail:
`docs/phase2/CHANGE_RECORD_249.md`.

### 2026-10-25 S13 terminal evidence-link conflict closure

Migration 027 now preflights all four existing purpose slots in recovered-terminal finalization;
a distinct reference for an occupied `OUTCOME`, `COMPLETION`, `POST_COMPLETION_CHALLENGE`, or
`READ_ATTESTATION` slot returns `EVIDENCE_IDENTITY_CONFLICT/P0001` before insert arbitration. Both
verified-success and recovered-terminal paths then verify every expected per-attempt evidence
reference/purpose after the explicitly targeted inserts and before lifecycle or event effects.
`S13-ATTEMPT-EVIDENCE-LINK-01` covers positive associations, exact terminal replay, conflicting
purpose ownership and unchanged state (`NOT_RUN`). Candidate SHA-256:
`9FD636675D0B6A09F0D93BD15B511CC441B396913BCF198E509ACCA42EE7BA0A`. No SQL parse, migration,
database operation, test/check, staging, commit or push ran. Continue independent S13 source
lock/FK/trigger/effect closure; start qualification only after coding closes.

### 2026-10-25 S13 ledger-owner role isolation

Migration 027 now fails closed unless `ledger_owner` is `NOLOGIN`, `NOSUPERUSER`, `NOBYPASSRLS`,
`NOCREATEDB`, `NOCREATEROLE`, and `NOINHERIT`, with no role memberships granted to it or from it.
This closes inherited/set-role privilege paths before the candidate installs SECURITY DEFINER
functions. S12-PG-01/S13-UNIVERSAL-FENCE-54-01 now require these exact catalog assertions. The
candidate remains uninstalled; this is source-only, not effective privilege evidence. SHA-256:
`9FD636675D0B6A09F0D93BD15B511CC441B396913BCF198E509ACCA42EE7BA0A`. No SQL parse, migration,
database operation, tests/checks, stage, commit or push ran.

### 2026-10-25 operator-resolve full target prelock

`operator_resolve_v1` now acquires namespace-4 advisory locks for the union of the current
change's owned target-lock identities and the complete bounded active-target snapshot before its
first target-parent `FOR SHARE`. The previous source locked only the change-owned subset while
reading every active target as a parent, leaving part of the documented rank-4 lock set implicit.
`S13-OPERATOR-RESOLVE-01` adds a sparse-plan contention fixture for an unrelated active target.
Candidate SHA-256: `CAC75207D5D9E031B9C5061B5B1EF81487238909B7BC946FA454FDFDF44A898F`. The
scenario remains `NOT_RUN`; no SQL parse, test/check, migration, database operation, COM, stage,
commit or push ran. Continue source-wide lock/FK/trigger/effect closure before review/qualification.

### 2026-10-25 GAP_BOUND cross-scope event association

Current migration 027 source already builds `SWEEP_ITEM_FAILED` from the `GAP_BOUND` item with
explicit `change_id=NULL` (`027:7524-7527`). The disposable case where a foreign-scope
`records.change_id` equals the selected `hold_id` therefore moves from an implementation gap to a
runtime assertion; it remains `NOT_RUN`. This source observation does not prove installed behavior.

### Current access recheck — 2026-10-25

The local gateway client returned `is_error=false`, `ok=true` for the scoped read-only
`source_health` call. Strict SSH to the trusted IP returned exit 0 for the stack status command;
postgres, redis, apache, proxies 8191–8193, sidecar, IdP and gateway were all `True`. No token was
printed and no service was restarted. This does not establish current clone COM access or writer
authority.

### 2026-10-25 S13 versioned nonterminal unknown-outcome path

Migration 027 now defines an explicitly revoked `resolve_unknown_v2`; the adapter selects it only
with the S13 schema flag and rejects the legacy caller-boolean API in that mode. The candidate
requires an exact dispatch CAS and attempt-linked receipt, completion, and typed outcome references.
It derives only a complete, healthy, determinate V1/V2 `PRESENT` or `ABSENT` outcome into
`TRIAGE_REQUIRED`, and only with a returned-success receipt and `WRITER_CALL_RETURNED` completion
proof. It terminalizes the exact attempt and clears only its matching physical-base slot while
retaining the call hold and business resources for witnessed T16. `UNKNOWN`, independent-closure
proof, and entered conditional conflict refuse before DML; conditional conflict remains
`APPLY_UNKNOWN` for the separate T16 Path B. The design/prerequisite documents identify the typed
outcome as the candidate schema's immutable observation. This remains source-only: full lock/FK/
effect review, grants, migration and S13-RESOLVE-UNKNOWN-01 remain open/NOT_RUN. No SQL parse,
test/check, migration, database operation, COM, stage, commit or push ran. Detail:
`docs/phase2/CHANGE_RECORD_251.md`.

### 2026-10-25 S13 unknown-outcome completion-class binding

Manual source reconciliation against S12 added class-specific signer/process bindings, exact attempt
session equality, returned-receipt consistency for the writer-return proof, and matching signed
OutcomeEvidence completion class; V3 also matches the proof digest. The later T16-reachability review
restricts `resolve_unknown_v2` to `WRITER_CALL_RETURNED`; independent closure cannot enter generic
`TRIAGE_REQUIRED`. The supervisor proof remains available only to the exact entered conditional-
conflict V3 T16 Path B. Qualification `S13-RESOLVE-UNKNOWN-01` covers the allowed class and negative
cross-binding cases. Source-only; no SQL parse, migration, test/check, database operation, COM,
stage, commit or push ran. Detail:
`docs/phase2/CHANGE_RECORD_251.md`.

The same cross-record completion proof checks now run before either T16 branch in
`operator_resolve_v1` can consume its witness cosign or release resources: class, class-specific
signer/process, exact attempt session, signed outcome class, and V3 digest. The qualification
`S13-OPERATOR-RESOLVE-01` now requires both valid proof classes and cross-binding refusal cases.
These changes remain source-only, ungranted, and unqualified.

**2026-10-25 T16 reachability correction:** resolve_unknown_v2 must not move an in-flight conditional conflict or indeterminate UNKNOWN result into generic T16 triage. Path A requires a physically terminal returned call, so the candidate now enters that path only for a returned-success receipt, class WRITER_CALL_RETURNED proof, and complete/healthy/determinate V1/V2 outcome; it terminalizes only the exact attempt and matching physical-base slot while retaining the call hold and business resources for T16. Independent closure and indeterminate outcomes refuse before DML; conditional conflicts remain APPLY_UNKNOWN for Path B, which retains both class-specific proof cases. See CHANGE_RECORD_251 and S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md; qualification and SQL parsing remain NOT_RUN.

**2026-10-25 T16 absent-effect target preflight:** source tracing found that the failed-apply path could silently continue if its exact active-change target lock was absent; the repair helper also ran only after cosign/terminal/resource mutations. `operator_resolve_v1` now checks the exact target-lock tuple, still owned by the resolving change, after ranked row locks/frozen-plan comparison and before cosign consumption for every proven-absent branch. Missing/changed owner returns `LOCK_PLAN_STALE`; the ordinary delete or repair handback remains the final mutation guard. `S13-OPERATOR-RESOLVE-01` captures this pre-DML order and unchanged state for ordinary and repair cases. Source-only, ungranted and `NOT_RUN`; no test/check, parser, migration, database operation, staging, commit or push ran. Detail: `docs/phase2/CHANGE_RECORD_251.md`.

**2026-10-25 T16 recovery-tuple binding:** `private_writer_record_recovered_terminal_v1` now compares the dispatch CAS and exact receipt/completion/outcome/challenge/read-attestation references against the immutable `OPERATOR_RESOLVE` event before evidence-link inserts or physical-attempt/slot changes. A changed tuple refuses `RECOVERY_EVIDENCE_REJECTED`; exact replay remains lookup-only. Qualification now varies each reference independently. Candidate source-only, ungranted and `NOT_RUN`; no parser, test/check, migration, DB/COM operation, staging, commit or push ran. Detail: `docs/phase2/CHANGE_RECORD_251.md`.

**2026-10-25 T16 finalizer replay reachability:** manual source tracing found that an early attempt-state guard rejected `TERMINAL_WITH_EVIDENCE` before the finalizer's existing exact-replay branch. The guard now permits only `POSSIBLY_EXECUTING` or `TERMINAL_WITH_EVIDENCE`; the latter still requires an empty physical slot, exact finalized event/evidence tuple and all expected attempt-evidence links before returning lookup-only. Other states remain refused. Exact replay case remains `NOT_RUN`. Detail: `docs/phase2/CHANGE_RECORD_251.md`.

**2026-10-25 T16 finalizer event-shape gate:** the post-checkpoint finalizer now also requires its exact `OPERATOR_RESOLVE` payload to say `execution=FAILED_APPLY` and `checkpoint_required=true`. Before casting the payload cosign identifier, it enforces canonical UUID grouping; malformed event text therefore maps to the stable T16 refusal instead of an unhandled cast error. These are source predicates only and remain `NOT_RUN`; no SQL parser, test/check, migration, or database operation ran. Detail: `docs/phase2/CHANGE_RECORD_251.md`.

**2026-10-25 evidence row-shape constraints:** source review found nullable `CHECK` predicates for the V3 completion-proof and read-attestation digests and version-specific row-shape gaps. Source tracing confirms every outcome version needs its dispatch receipt ID for terminalization/replay binding; migration 027 now requires it for all outcome rows, requires non-null V3 digests before regex checks, requires the matching completion-proof class for every outcome version, and excludes V3-only projection fields from V1/V2 rows. Disposable schema-owner negative fixtures are recorded in the qualification prerequisites; implementation remains source-only and `NOT_RUN`.

**2026-10-25 legacy registry bridge reconciliation:** the final migration 027 bridge block routes preserved legacy epoch/registry signatures through fenced v1 bodies in the same transactional cutover; direct v1 signatures remain revoked. This removes the source-only claim that proposal waits for those legacy bodies to be coordinated, while effective ACLs and runtime races remain `NOT_VERIFIED`/`NOT_RUN`.

**2026-10-25 immutability inventory reconciliation:** source tracing found migration 027 already installs shared immutable and no-TRUNCATE triggers through its `$immut$` and `$no_truncate$` blocks for evidence/history/intent/permit/ack/barrier-call/link tables and state/trust-registry relations. Redundant explicit triggers were removed before closing this turn; the qualification prerequisite records the existing source predicates. This is source inspection only and does not prove installed trigger state; no parser, tests/checks, migration or DB operation ran.

### 2026-10-25 S12 payload-to-COM manifest source binding

The new manifest builder derives every physical business-value assignment digest from the typed approved DraftPayload and enforces complete one-to-one source/destination binding for the currently measured single-line shape. It excludes only the duplicate-override authorization object and expected target version from document assignments. This is code-level payload provenance only; exact destination crosswalk, authenticated mapping/configuration, operational OneCWritePort, signer/witness keys, invocation guard, COM receipts, and clone qualification remain open. See CHANGE_RECORD_252.md. No tests/checks, parser, migration, database operation, COM, staging, commit or push ran.

### 2026-10-25 migration 027 success-terminal parse correction

Manual source reading found and removed a duplicate local slot variable in private_writer_record_verified_success_v1. This is a source fix only; candidate migration 027 has not been parsed or installed. Continue manual source closure without running tests/checks. After coding closure, the test/database-review phase must parse and qualify the exact candidate on the disposable PostgreSQL instance. See CHANGE_RECORD_253.md.

### 2026-10-25 T16 checkpoint hold-list alignment

`T16RecoveryCoordinator` now rejects an empty `checkpoint_hold_ids` list before hold-release comparison or S13 terminalization, matching the existing checkpoint coordinator and SQL-ledger validations. Source-only; no test/check, SQL parse, migration, DB/COM operation, stage, commit or push ran. Detail: `docs/phase2/CHANGE_RECORD_254.md`. After coding closes, functional/E2E qualification must prove empty, missing, malformed and duplicate hold lists fail before `record_recovered_terminal`, with a valid non-empty control.

### 2026-10-25 source continuation — CT14 argument boundary and lifecycle cutover

`ct14_common.run_designer` now snapshots caller arguments and refuses selectors that could replace
the guarded base/server, credentials, alternate infobase connection string, or output log; the
repository's exact `-Files` and `-partial` selectors remain allowed. A focused actual
`code-reviewer` re-review found no selector bypass or compatibility defect. The separate
`tasklist`-to-process-start race remains an explicit limitation; no Designer run or test was made.
In candidate migration 027, the same-transaction legacy bridge cutover now drops the two
row-locking lifecycle triggers and revokes `lifecycle_writer_epoch` from runtime roles while
preserving `events_chain_guard`. This is unparsed, uninstalled source only; effective ACL and
concurrency evidence remain `NOT_VERIFIED`/`NOT_RUN`. See `CHANGE_RECORD_273.md`,
`CHANGE_RECORD_274.md`, and prerequisite `S13-LIFECYCLE-TRIGGER-CUTOVER-01`.

### 2026-10-26 source continuation — legacy fence-check cutover

Source tracing found migration 006 grants `fence_check` to `writer_role`; its short-lived result
cannot authorize a later COM entry. Candidate migration 027 now revokes that exact signature and
the S13-enabled SQL adapter fails before `invoke()`, preserving the legacy-disabled route. Effective
grants and recovery-race qualification remain `NOT_VERIFIED`/`NOT_RUN`; no SQL parse, migration,
test, or database operation ran. See `CHANGE_RECORD_276.md` and prerequisite
`S13-FENCE-CHECK-CUTOVER-01`.

**2026-10-26 recovery-source reconciliation:** an earlier continuation note above says T12, GAP_BOUND,
GAP and VERIFY still refuse with `RECOVERY_NOT_READY`. Current candidate migration 027 now defines
their versioned handlers (`private_writer_recovery_t12_v1` at 8614, GAP_BOUND at 7922, GAP at 8051,
VERIFY at 8200) and `recover_sweep` dispatches the stages at 9193-9249. That earlier statement is
superseded for source presence only; it must not be read as runtime qualification. Full stage
selection, effects, SQL parsing, installed grants, and disposable behavior remain subject to the
named `NOT_RUN` acceptance cases. Source anchors were reread on 2026-10-26; no parser, test, database
operation, or migration ran.

**2026-10-26 access recheck:** strict read-only SSH to Ivan's `koros@100.88.71.74` host completed
with exit 0; `run-mcp-stack.ps1 -Action Status` reported postgres, redis, apache, proxy8191-8193,
sidecar, idp, and gateway all `True`. On the local execution host, TCP listeners were present on
8088, 18432, 19379, 21768, 21080, and 21000; 8191-8193 were absent. Direct anonymous HTTP to
8088 returned 401, while the absent proxies could not connect. The first local MCP request failed
to connect before those services were restored. A first IdP start used the helper's default
environment and safely refused port 18080 because it had a foreign listener (PID 27984); nothing
was stopped. With explicit `E2E_DIR=D:\ERP_MCP_Testbed\real1c_e2e`, only the missing IdP and gateway
were started through `fault.ps1 -Action start`; neither Apache nor any proxy was restarted. A
subsequent authenticated local MCP `source_health` call connected but returned safe error
`SOURCE_UNAVAILABLE`, correlation `7e17fa00-4e30-4bd4-9be2-44e1cb905b62`. The configured proxy
launch via `Start-Process` was rejected by the execution policy, so local source-health recovery
awaits the operator-provided command `scripts\real1c\autostart\start_lane.ps1 -ApachePort 8088`
(use 18088 if 8088 is re-reserved). No token or secret was printed; no adjacent project was
investigated.

**2026-10-26 local MCP source-health retry:** using the repository virtualenv client at `scripts/real1c/gateway_client.py`, an in-process auditor token (600-second TTL, never printed), and the configured local gateway, `source_health` for `onec-818ha-reference` again returned `SOURCE_UNAVAILABLE` (`category=dependency`, `retryable=true`, correlation `b709a832-cf80-4c00-b060-252428e29291`). The request reached the local MCP gateway; this does not prove the reference connector or lane proxy is healthy. No token/secret was emitted, no service was restarted, and no database/1C/COM operation occurred. The missing local 8191–8193 proxy listeners and policy-rejected proxy launch remain the exact recovery dependency; operator's supplied command remains `scripts\real1c\autostart\start_lane.ps1 -ApachePort 8088` (use 18088 if Windows reserves 8088).

**2026-10-26 PM Bridge S12/S13 source review:** request `c6c7dc4f-11f6-4810-9cad-326f3d1e6a67` was routed to canonical project `erp_mcp` / repository `https://github.com/xLZDx/ERP_MCP.git` and correlated to reply `e8866c5f-24c2-5fd8-b3ee-0026449439b0` (GPT-PM verdict `MODIFY`, source-only). Findings: B-01 no operational 1C writer or authenticated property/transaction boundary; M-01 no enforced schema-mode/startup compatibility; M-02 the one-way database COM-entry authorization is not evidence of physical entry; M-03 process takeover/barrier requires physical worker proof; M-04 evidence providers/resolver are injected but not operationally bound; M-05 complete installed ACL/lock graph is not verified. The review positively confirms fail-closed adapter routing and revocation of legacy point-in-time `fence_check`. It is not commit, push, migration, deployment, or production approval. Correlated response and attached-file hashes are held by PM Bridge; no tests, parser, DB operation, migration, COM action, commit, or push occurred in the review.

**2026-10-26 local listener recheck:** read-only `Get-NetTCPConnection -State Listen` shows 8088, 18432, 19379, 21768, 21080 and 21000 listening; 8191–8193 remain absent. The 8088 listener owner PID is 34620. No listener was restarted or stopped. A local MCP `source_health` retry for `onec-818ha-reference` returned `SOURCE_UNAVAILABLE`, correlation `b709a832-cf80-4c00-b060-252428e29291`; local connection recovery is still pending. The previously supplied `start_lane.ps1 -ApachePort 8088` command is the only unblocked recovery route known; the prior attempt to start the missing proxies was rejected by execution policy.

**2026-10-26 schema-mode compatibility source follow-up:** responding to pre-commit GPT-PM finding M-01, `SqlChangeLedger.invoke()` now reads `pg_catalog.to_regtype('change_ledger.private_writer_identity_v1')` inside the adapter-owned READ COMMITTED transaction and requires the marker result to equal the immutable `private_writer_schema_enabled` configuration before role/scope setup or the selected business function. A settled mismatch refuses with `S13_SCHEMA_MODE_MISMATCH`. This guards each invocation; it does not permit concurrent legacy writers during migration 027. Acceptance `S13-ADAPTER-SCHEMA-MODE-01` records both matching modes and both mismatch combinations as `NOT_RUN`. The new code was added after GPT-PM's MODIFY review and has not received a follow-up review. No test/check, SQL parse, database operation, migration, build, COM call, stage, commit or push ran.

**2026-10-26 adapter-schema mode source re-review:** the actual `code-reviewer` role inspected the current `SqlChangeLedger.invoke()` route and prerequisite `S13-ADAPTER-SCHEMA-MODE-01`. It found no material source finding: caller transactions are refused; the owned transaction sets and verifies READ COMMITTED first; marker/mode comparison precedes role, scope, and selected business SQL. Both settled matchings proceed and both mismatch pairings refuse. This is source-only; the disposable four-way runtime/effective-role matrix remains `NOT_RUN`. Reviewer model/effort metadata were not exposed.

**2026-10-26 disposable PostgreSQL catalog recheck:** using `LaneEnv` and the repository venv, connected in-process as `business_ai_admin` to database `business_ai` on server port 5432 and queried only catalogs in a `REPEATABLE READ READ ONLY` transaction. `change_ledger` and marker type `change_ledger.private_writer_identity_v1` are absent; the named S13 roles are absent; no memberships among the candidate S13 roles were present; `information_schema.role_table_grants` returned zero rows for `change_ledger`. Existing `business_ai_admin`, `business_ai_app`, and `business_ai_control_api` were non-superuser and `NOBYPASSRLS`; the separate `business_ai` role was superuser/`BYPASSRLS`. No business rows, schema, data, grants, or files were changed and no credential/DSN was printed. This is disposable database metadata only: candidate S13 grants remain `NOT_VERIFIED`, not denied or zero, until the approved schema is installed and measured.

**2026-10-26 local lane recovery and access recheck:** the operator-authorized `scripts/real1c/autostart/start_lane.ps1 -ApachePort 8088` was run once. The script reported postgres, Redis, Apache/1C, proxies 8191–8193, sidecar, IdP and gateway as present; the proxy listeners are now reachable. Its tunnel-client `Start-Process` reported an invalid `WorkingDirectory`, so tunnel-client start remains `NOT_VERIFIED`; no neighboring checkout was inspected to diagnose it. Existing Apache and the already-running services were not intentionally restarted. Read-only anonymous HTTP to each `127.0.0.1:8191-8193/erp_mcp_ref/odata/standard.odata` returned 401, the expected authentication challenge. An in-process, short-lived auditor token (never printed) through the repository gateway client returned `source_health ok=true` for `onec-818ha-reference` with HTTP 200. Strict SSH to `koros@100.88.71.74` with `StrictHostKeyChecking=yes` succeeded; `run-mcp-stack.ps1 -Action Status` reported all nine remote components True. This proves current transport and source-health response, not writer rights, COM transaction boundaries, or S12/S13 qualification.

**2026-10-26 database-reviewer recheck:** a separate actual `database-reviewer` agent repeated a catalog-only query through the repository venv and `LaneEnv` in a `REPEATABLE READ READ ONLY` transaction (`transaction_read_only=on`). It confirmed `business_ai` on PostgreSQL server port 5432, session role `business_ai_admin`; no installed `change_ledger` schema/marker or S13 roles; and no non-system role memberships. Existing admin/app/control roles are non-superuser and `NOBYPASSRLS`; the distinct `business_ai` role is superuser/`BYPASSRLS`. Candidate S13 `has_function_privilege` and effective table grants remain `NOT_VERIFIED` because the candidate schema is absent; this is not evidence of denial. No business rows, DDL, grants, migration, tests or checks were touched, and no credentials were printed. Repeat exact per-role effective grants and `has_function_privilege` after the approved disposable candidate schema is installed.

**2026-10-26 local lane recovery correction:** the operator-authorized `scripts/real1c/autostart/start_lane.ps1 -ApachePort 8088` was run once. It reported the local postgres, Redis, Apache/1C, proxies 8191–8193, sidecar, IdP and gateway as present. The proxy listeners are reachable; anonymous requests to each proxy OData path return 401. The script also reported its tunnel-client `Start-Process` failure (`WorkingDirectory` invalid); tunnel-client start remains `NOT_VERIFIED`, and no neighboring repository was inspected to diagnose it. Existing Apache and already-running services were not intentionally restarted. Using an in-process short-lived auditor token, the repo gateway client returned `source_health ok=true` (HTTP 200) for `onec-818ha-reference`. Strict SSH with `StrictHostKeyChecking=yes` to `koros@100.88.71.74` succeeded; remote `run-mcp-stack.ps1 -Action Status` reported all nine components True. This updates earlier notes that the proxies were absent and source-health recovery was pending; it proves transport/source-health only, not writer rights, COM transaction boundaries, or S12/S13 qualification.

**2026-10-26 adapter schema-mode source review:** the focused actual `code-reviewer` review `/root/review_schema_mode_guard` accepted the per-invocation marker/configuration comparison at source level and found no source blocker. The exact order is adapter-owned READ COMMITTED transaction, isolation check, marker/config match, then role, scope and selected function. Model/effort metadata were not exposed. This does not replace GPT-PM broad follow-up, runtime qualification, or rollout sequencing. See `CHANGE_RECORD_276.md`.

**2026-10-26 CT14 identity inventory and COM-lane source guard:** read-only inventory of local `D:\secrets\erp_mcp` filenames found `admin_1c_clone_password.dpapi`, `admin_1c_clone_user.txt`, and `test_reader_password.dpapi`; no filename identifies a `CT14_NARROW` writer credential. Strict SSH directory inventory of `D:\1c\mcp\env` found `onec_admin.dpapi`, `test_reader_password.dpapi`, and `credentials.json` among other configuration files. Only `credentials.json`'s top-level property names and two in-memory substring booleans were queried; the only top-level key was `users`, with no `818HA_p2diff` or `CT14` text. No credential values were output or separately inspected; the later guarded metadata probe loaded its DPAPI credential in-process only. Clone-specific least-privilege credential binding remains `NOT_VERIFIED`.

To fail closed if a different 1C account is supplied by a future COM composition, `windows_com_sta_lane()` now requires an expected username and on the STA worker compares it to `InfoBaseUsers.CurrentUser().Name` immediately after `Connect`, before base fingerprint measurement and before the lane can open. It returns sanitized `COM_BASE_USER_UNAVAILABLE` or `COM_BASE_USER_MISMATCH`; the startup error allowlist recognizes both. The focused actual `code-reviewer` `/root/com_user_binding_review` found no material source blocker, including for UTF-8 comparison and cleanup order. This is code/source-review evidence only; it does not prove the expected-name configuration, effective CT14 role rights, base fingerprint provenance, or a live COM session. No tests/checks, COM operation, database operation, or migration ran. Hashes: `windows_com_lane.py` `D73E5F4D6858422008E209F64445D12154E1BEDE488A1DB1A5464E878D33B5F4`; `com_sta_lane.py` `2400799249C3FE1A94C807BFB12D46FAA57E4DD2737011C78B9149B0CC7FDE7A`. Detail: `CHANGE_RECORD_277.md`; acceptance `S13-COM-USER-BINDING-01` is appended to the disposable qualification prerequisites and remains `NOT_RUN`.

**2026-10-26 local lane recovery:** the operator-authorized `scripts/real1c/autostart/start_lane.ps1 -ApachePort 8088` was run once. The script reported local PostgreSQL, Redis, Apache/1C, proxies 8191–8193, sidecar, IdP and gateway present; proxy OData paths on 8191–8193 returned anonymous HTTP 401. Its tunnel-client `Start-Process` reported an invalid `WorkingDirectory`, so only tunnel-client startup remains `NOT_VERIFIED`; do not inspect the adjacent repositories to diagnose it. Existing Apache and already-running services were not intentionally restarted. A short-lived in-process auditor token (never printed) through the repository gateway client returned HTTP 200 / `source_health ok=true` for `onec-818ha-reference`. Strict SSH to `koros@100.88.71.74` with `StrictHostKeyChecking=yes` succeeded; `run-mcp-stack.ps1 -Action Status` reported all nine components True. These observations supersede earlier same-date notes that proxies were absent and source health remained unavailable; they prove transport/source-health only, not the private writer, effective candidate SQL grants, COM transaction boundary, or S12/S13 qualification.

**2026-10-26 disposable-clone metadata inventory result:** after source review, ran `.venv\Scripts\python.exe .\testlane\onec_extension\scripts\ct14_metadata_inventory_readonly.py`. The script's source states it only reads 1C configuration/document metadata, prints names and versions, uses `ct14_common`'s exact `818HA_p2diff` path guard, and loads the DPAPI credential in process without emitting it. It exited 1 before establishing a COM session: sanitized result `CT14_METADATA_COM_CONNECT_FAILED`, exception type `com_error`, HRESULT `0x80020009`, automation codes `0x00000000` and `0x80004005`, diagnostic class `LICENSE`. No metadata or business rows were returned, no write occurred, and no test/check/migration ran. Do not retry this COM path until the licensing/connection condition changes. The exact payload-to-1C property and tabular-section map remains `NOT_VERIFIED`; code that depends on it is still gated.

**2026-10-26 remote disposable-clone inventory:** strict SSH, names/timestamps only, to `D:\1c\env\bases` found `818HA_p2diff`, `818HA_reference_ro`, and `818HA_test_ready`. This confirms the named clone directory exists on Ivan's host but does not prove a COM session, current license availability, or which credential is valid for that clone. The remote `D:\1c\mcp\env` names-only inventory and sanitized `credentials.json` metadata above show no CT14/p2diff marker; do not try `onec_admin.dpapi` against a different base or substitute admin credentials for the writer.

**2026-10-26 S13 aggregate recovery budget source fix:** manual source inspection found that migration 027 applied the configured `batch_size` independently to T3, T9, VOID, and expired-nonce selections, then refused an aggregate above 66 items or 200 weighted row effects. A persistently oversized mixed queue could therefore be selected and refused identically on every pass without progress. The combined selector now consumes a shared 66-item budget and a shared effect budget (`200 - run row - deferred-event reserve`), decrementing by the existing stage upper bounds (T3/VOID 3, T9 4, nonce 1). The same stage selection order and pre-DML fail-closed assertions remain. Prerequisite `S13-RECOVERY-AGGREGATE-BUDGET-01` requires bounded progress/drain through direct recovery; deferred `kill_switch(OFF)` must atomically refuse with no state/event/run-row delta while work remains, then succeed after recovery drains it. This follows the existing stop contract and is `NOT_RUN`. This is source-only; SQL parse, migration, database operation, tests/checks, build, CI, staging, commit, push, effective ACL measurement, and runtime qualification remain `NOT_RUN`/`NOT_VERIFIED`. The migration and prerequisite file were already untracked before this turn; baseline and current hashes are in `CHANGE_RECORD_278.md`.

**2026-10-26 S13 stale-revocation batch source fix:** `revoke_stale_v1` previously chose a fixed top 20, then refused the unchanged batch if token/resource fan-out exceeded the 200-row lock/effect caps. The selector now chooses the largest deterministic leading prefix of those 20 whose conservative per-record closure estimates fit both caps; a single oversized candidate still returns `NOT_ACCEPTED` before DML. A focused read-only database-reviewer source pass found no BLOCKER/MAJOR; model/effort metadata is UNKNOWN. `S13-REVOKE-STALE-BATCH-RANK-01` now separately requires aggregate-overflow prefix progress and single-item oversized refusal. This is source-only; no parser, tests/checks, migration, database operation, staging, commit, or push ran. Runtime, timing, exact locked closure and qualification remain unverified. Detail: `docs/phase2/CHANGE_RECORD_279.md`; the migration and qualification file were inherited untracked files, not authored wholesale in this turn.

**2026-10-26 current access and effective-grant recheck:** strict-host-key SSH to `koros@100.88.71.74` reported all nine stack components True via read-only Status; the local gateway client minted a short-lived auditor token in process and `source_health` returned `is_error=false, ok=true` for `onec-818ha-reference`. No service restarted and no credential was printed. A separate read-only database-reviewer catalog transaction found PostgreSQL 16.15/database `business_ai`, role `business_ai_admin`, no `change_ledger` schema, no S13 roles/functions or role-table-grant rows for that schema; effective candidate grants remain `NOT_MEASURABLE`, not denied. Evidence: `artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md` and `artifacts/WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-25.md`. COM identity and transaction boundary remain unverified.

**2026-10-26 S13 VERIFY counter-fence source fix:** `verify_inconclusive_v1` omitted namespace-6 identity `sweep-counter:v1:<lowercase-change-id>:VERIFY` before later inserting/updating the global VERIFY counter. The key is now part of the sorted pre-row fence set for new-attempt and exact-replay branches; `S13-COUNTER-RANK-01` explicitly qualifies both. A focused read-only database-reviewer pass found no BLOCKER/MAJOR (model/effort UNKNOWN). Source-only: no SQL parse, tests/checks, migration or runtime call. Detail `docs/phase2/CHANGE_RECORD_280.md`.

**2026-10-26 WP5 envelope preflight allocation bound:** source review found that the lexical verifier preflight counted JSON values but omitted object keys, although `json.loads` materializes object-pair lists before duplicate-key rejection. The candidate now counts both keys and values and caps structural nodes at 100,000 under the existing 2 MiB envelope ceiling rejects integer tokens outside signed 64-bit range before record construction, and rejects all floating-point tokens before float construction. `WP5-VERIFIER-DECODE-01` requires the exact 100,000/100,001 boundary, rejection before `json.loads`, unchanged canonical type selection, and zero trust-source calls for invalid input. This is source-only; no test/check, build, parser benchmark, migration, database/COM operation, staging, commit, or push ran. Detail `CHANGE_RECORD_282.md`.

**2026-10-26 private-ingress JSON allocation bound:** `json_preflight.py` now supplies the non-recursive 32-container/100,000 key-plus-value preflight to both the S12 evidence verifier and the private writer's 1 MiB dispatch/lookup bodies. The ingress runs it after caller authentication and strict UTF-8 decoding but before `json.loads`; refusals use the existing `INVALID_REQUEST`/400 path before ticket/permit verification or service calls. Acceptance `S13-PRIVATE-INGRESS-JSON-STRUCTURE-01` requires exact depth/node boundaries and zero downstream calls; it remains `NOT_RUN`. Detail `CHANGE_RECORD_283.md`. No tests/checks, build, CI, benchmark, migration, DB/COM operation, staging, commit or push ran.

**2026-10-26 stale-revocation bounded-prefix revalidation:** manual source comparison found `revoke_stale_v1` planned a cost-bounded prefix from the top-20 window but revalidated it against the entire top-20 list. Any batch whose aggregate exceeded the cap while a shorter prefix fit therefore refused before processing with `LOCK_PLAN_STALE`. Revalidation now reloads only the selected `ids`, reapplies the original scope/state/stale-epoch eligibility predicates, and compares full row snapshots; tokens and owned resource/failure rows retain their separate complete snapshots. `S13-REVOKE-STALE-BATCH-RANK-01` requires the overflow fixture to commit the bounded prefix and advance on the next pass. Source-only; no SQL parse, tests/checks, migration, database operation, build, CI, staging, commit or push ran. Detail `CHANGE_RECORD_284.md`; candidate migration remains uninstalled and ungranted.

**2026-10-26 S13 stale-revocation retry-rank preservation:** follow-up source inspection found the selected bounded prefix was re-sorted by creation time before per-item revocation, even though candidate selection prioritizes never-attempted failures and then uses `(created_at, change_id)` tie-breaks. Migration 027 now carries `batch_rank` into the planned snapshot, processes the JSON array with explicit ordinality, and revalidates selected records in the same `REVOKE_STALE` failure-rank order, preserving deterministic item/event order. Acceptance `S13-REVOKE-STALE-BATCH-RANK-01` now explicitly covers this ordering. This is source-only; no SQL parse, tests/checks, migration, database operation, build, CI, staging, commit or push ran. Detail `CHANGE_RECORD_284.md`; independent review and disposable qualification remain open.

**2026-10-26 S13 combined-recovery array ordering:** manual source inspection found T3, T9, VOID and expiry selectors sorted their limited subqueries, then passed an `array_agg` without its own ordering clause into per-item loops. The candidate now orders each aggregate by its documented retry rank and timestamp/ID tie-break; expired nonces use `(expires_at, nonce)`. `S13-RECOVERY-AGGREGATE-BUDGET-01` now requires selection and committed item/event order to match. Source-only; no SQL parse, tests/checks, migration, database operation, build, CI, staging, commit or push ran. Detail `CHANGE_RECORD_285.md`; source review and disposable qualification remain open.

**2026-10-26 10:12 UTC effective-grant recheck:** database-reviewer connected through the in-process LaneEnv admin DSN under `REPEATABLE READ READ ONLY`; `business_ai` is PostgreSQL 16.15 and the session is `business_ai_admin`. The candidate `change_ledger` schema, S13 routines, private-writer/legacy roles and memberships are absent; no schema table-grant rows exist. The catalog routine query returned zero rows, so `has_function_privilege` was not evaluated for any candidate routine. Effective S13 grants remain `NOT_MEASURABLE`, not denied. No schema, grants or data changed, and no credentials were printed. Evidence: `artifacts/WP2_EFFECTIVE_GRANTS_RECHECK_2026-10-25.md`, supplemental current-state recheck.

**2026-10-26 10:14–10:16 UTC MCP/SSH refresh:** strict-host-key SSH to Ivan succeeded; the read-only stack status returned all nine component flags `True`. Local Apache 8088, proxies 8191–8193 and gateway 21000 were already listening and were not restarted. The expected read-only `testlane.phase2_mcp` service was absent on 21200, so only that venv process was started; it now listens on loopback `127.0.0.1:21200`. MCP initialization and `phase2_capabilities` returned `is_error=false`, `TESTLANE_EVALUATION_ONLY` / `NO-GO`. An in-process 300-second auditor token authenticated to local gateway 21000 and `source_health(onec-818ha-reference)` returned `ok=true`, HTTP 200; no business rows were read and no token was printed. This is access evidence only, not S13 writer qualification. Evidence: `artifacts/WP0_ACCESS_AND_SOURCE_RECHECK_2026-10-24.md`, “2026-10-26 10:14–10:16 UTC current connection refresh”.

**2026-10-26 S13 stale-generation refusal order:** `renew_writer_lease_v1` now rechecks the locked scope and returns `TICKET_SUPERSEDED` for a mismatched or NULL generation before locking permit/lease child rows; matching generations retain the existing child lock and snapshot revalidation. A bounded source review identified the previous wait-before-refusal ordering; post-change review and disposable SQL qualification remain pending. Detail: `CHANGE_RECORD_303.md`. Next: functional-test-reviewer authors focused SQL cases using only the owned disposable fixture; after coding closes, run SQL parser and runtime qualification through the authorized test roles.

**2026-10-26 WP5 decoder preflight performance and acceptance:** the scanner caches input lengths and counts exact UTF-8 bytes via an ASCII fast path or bounded strict-encoding chunks. Five 8 MiB trust-payload samples had a 1.414163-second median below the three-second source budget. The expanded functional suite `uv run pytest -q tests/phase2/test_wp5_json_decoder_contracts.py` passed with exit 0, 20 tests and 54 subtests in 35.07 seconds after the test owner corrected a schema-invalid fixture only. Earlier performance measurements lacked a captured untracked-source hash, and the unchanged 2 MiB evidence parser had a higher observed range in the updated run; do not attribute the full difference to the scanner. Detail and source/test hashes: `CHANGE_RECORD_304.md`. Full WP5 signer/trust acceptance and final stable remeasurement remain open.

**2026-10-26 WP5 DPAPI provisioning primitive:** added `provision_windows_dpapi_ed25519_key()` to generate an Ed25519 key in process memory and publish only its CurrentUser-DPAPI-protected seed; the API returns only public material and does not select registry identity/scope/validity or register the key. The code reviewer closed an orphan-on-interruption finding; the functional-test reviewer then found name-only cleanup could delete a replacement file. Current code verifies the published identity and removes paths only when device/inode matches the created file; post-fix independent review and replacement-sentinel unit test are pending. The utility was not run on Ivan's host, and no key was generated or registered. Detail: `CHANGE_RECORD_305.md`. Next: finish the focused source slice and its mocked tests; use the provisioning function on Ivan only with the exact account-private path and established S13 service/host/scope/validity metadata.

**2026-10-26 S13 candidate migration setup repairs:** the first E2E retry failed on unquoted `session_user`; the candidate now quotes that existing column/record-field identifier while preserving bare PostgreSQL `SESSION_USER` identity expressions. A second retry passed that point but found `LEDGER_ROLE_UNSAFE`: migration 004 creates `ledger_owner` without `NOINHERIT`, leaving PostgreSQL's default `INHERIT`. Candidate 027 now rejects unsafe attributes/memberships, then tightens this known non-login owner to NOINHERIT and rechecks it. Both setup failures occurred before all three test bodies. Third focused disposable retry pending; latest candidate SHA-256 `56A9CA5CF182EB652C52FA549C4A5AA6B22B81DC6410BAAB970D1986F4DD3E28`. Detail: `CHANGE_RECORD_306.md`.

**2026-10-26 dispatch/process authority follow-up:** `PrivateWriterService.dispatch()` now holds the existing base-scoped host mutex from before database admission through the complete COM/evidence path. Request cancellation shields the accepted inner dispatch. If the internal task is cancelled during loop shutdown, the service fail-stops without calling `ReleaseMutex`; Windows abandons the mutex when its owning thread exits, which can precede process exit. The COM STA must therefore drain before that event-loop thread terminates; this shutdown sequence has not been proven. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` remains `NOT_RUN`; no COM atomicity or physical outcome is claimed. See `CHANGE_RECORD_287.md`.

**2026-10-26 stable mutex-owner thread:** superseding the event-loop-thread kernel ownership described in CR287, `WindowsServingAuthorityMutex` now assigns kernel mutex acquire/release to a dedicated non-daemon owner thread and exposes opaque thread-independent logical leases. This prevents event-loop exit alone from abandoning authority. Runtime shutdown still needs to drain COM, release all leases, and close the owner thread; otherwise it fails closed. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` remains `NOT_RUN`. Detail: `CHANGE_RECORD_288.md`.

**2026-10-26 runtime shutdown drain:** added bounded `PrivateWriterService.shutdown()` and made `PrivateWriterRuntime.close()` asynchronous: stop dispatch admission, drain dispatch/barrier work, close the COM writer through `close_after_drain()`, then close/join the dedicated Windows mutex owner. Failed drain/COM close leaves authority held. The listener stop is an explicit caller precondition. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` remains `NOT_RUN`; no operational writer/listener or runtime proof exists. Detail: `CHANGE_RECORD_289.md`.

**2026-10-26 complete runtime-close deadline:** `PrivateWriterRuntime.close()` now serializes callers (including lock wait) and applies one bounded deadline across service drain and COM STA close, then closes/joins the authority owner. A COM close timeout leaves the serving-authority mutex open; a later serialized call may finish after shielded STA cleanup completes. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` adds concurrent-close, timeout, retained-authority and retry acceptance and remains `NOT_RUN`. No tests/checks, COM, database, migration, staging, commit or push ran. Detail: `CHANGE_RECORD_290.md`.

**2026-10-26 shutdown/control race fence:** `inspect_startup_recovery()`, `fence_scope()` and `resume_barrier()` register accepted lifecycle work before their first await; shutdown refuses later control operations and drains earlier ones before COM/mutex close. `prepare_to_serve()` cannot reopen readiness after shutdown. The bounded timeout leaves authority held and restart-required if accepted work cannot finish. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` covers the DB-lookup/closure race, startup readiness race, post-shutdown refusal and accepted-operation drain; it remains `NOT_RUN`. No tests/checks, DB/COM, migration, stage, commit or push ran. Detail: `CHANGE_RECORD_291.md`.

**2026-10-26 async authority-owner calls:** serving-mutex acquire/release now await a worker-thread response rather than blocking the event loop; cancellation retains same-process exclusion and restart-required state. Runtime close awaits and shields the final owner-thread close after COM drain. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` covers event-loop responsiveness and cancellation during acquire/release/close; it remains `NOT_RUN`. No tests/checks, DB/COM, migration, stage, commit or push ran. Detail: `CHANGE_RECORD_292.md`.

**2026-10-26 single-flight authority close:** `WindowsServingAuthorityMutex.close_async()` retains one task across cancellation. Repeated runtime close attempts join that command instead of queueing a duplicate owner-thread close; an ambiguous failure stays fail-closed and requires process replacement. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` covers repeated cancellation/retry and exact command count; it remains `NOT_RUN`. No tests/checks, DB/COM, migration, stage, commit or push ran. Detail: `CHANGE_RECORD_293.md`.

**2026-10-26 ASGI/runtime lifecycle binding:** added `create_private_writer_runtime_app()`. It refuses ASGI startup until the caller has completed service recovery and always drains/closes the runtime during lifespan exit after the host stops accepting requests. The factory does not start a listener or attest release gates. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` covers the prepared-runtime precondition and listener/lifespan close order; it remains `NOT_RUN`. No tests/checks, DB/COM, migration, stage, commit or push ran. Detail: `CHANGE_RECORD_294.md`.

**2026-10-26 private-ingress lifecycle bypass closure:** source tracing found the lower-level `create_private_writer_app()` still accepted `runtime=None`, which omitted the prepared-runtime startup gate and drain/close lifespan. It now requires the exact `PrivateWriterRuntime` matching its routed service, so every app factory retains the runtime lifecycle. A source search found no other in-repository direct callers. `S13-PHYSICAL-AUTHORITY-DISPATCH-01` now includes missing/mismatched-runtime refusal and remains `NOT_RUN`; no test/check, build, DB/COM, migration, stage, commit or push ran. Detail: `CHANGE_RECORD_295.md`.

**2026-10-26 selected resource FK-owner scope closure:** migration 027 adds the explicitly revoked `private_writer_assert_planned_resource_owner_scope_v1` helper to `claim_v1`, `release_claim_v1`, `revoke_change_v1`, `retry_verify_v1`, `private_writer_recovery_permit_v1`, `private_writer_recovery_t5x_v1`, `cancel_permit_v1`, `operator_close_failed_verify_v1`, and `operator_resolve_v1`. It checks planned record membership/scope and selected target/key/lease owner identity after namespace-6 fences and before namespace-4/resource row locks. Retry verification now fences and locks its selected target-lock owners as part of the sorted parent plan; failed-verification close and operator resolution apply the same exact parent/resource-owner check before locking or releasing target resources. Operator resolution also acquires namespace-4 fences for the complete frozen target and business-key identities as one signed-sorted set before resource row locks, caps snapshot collection at 201 and rejects above 200, caps post-fence target/key row locks at 201, and checks lifecycle after advisory namespaces 3/4. `S13-FK-RESOURCE-OWNER-SCOPE-01` requires cross-scope/cross-base fixtures, bounded-plan refusal, parent-before-child order, namespace-4 coverage, refusal and zero state/event delta; it remains `NOT_RUN`. No SQL parse, tests/checks/build, DB/COM, migration, stage, commit or push ran; effective grants remain `NOT_VERIFIED`. Detail: `CHANGE_RECORD_296.md`.

**2026-10-26 `revoke_stale_v1` bounded resource plans:** frozen and post-fence resource snapshots and child-row lock loops are capped at 201; plans above the 200-row contract refuse before row locking, and a changed snapshot returns `LOCK_PLAN_STALE` before any batch item DML. Target-registry rows use their primary-key order `(base_fingerprint)`; target-lock rows use `(base_fingerprint,target_ref)`. `S13-REVOKE-STALE-BATCH-RANK-01` adds the over-limit, changed-plan and target-lock-order scenarios; it remains `NOT_RUN`. No SQL parse, tests/checks/build, DB/COM, migration, stage, commit or push ran. Detail: `CHANGE_RECORD_297.md`.

**2026-10-26 target registry identity correction:** canonical `004_change_ledger.sql` defines one `targets` row per `(tenant_id,company_id,base_fingerprint)`; `target_ref` is carried by `target_locks`. Migration 027 now uses base-only target-parent snapshots, namespace-4 keys from target-lock rows, and one hold ID per eligible base selected from the primary-key registry. A serialized peer-created hold is treated as the source-compatible no-op by `private_writer_open_hold_v1`; unplanned newly eligible bases remain stale. `S13-OPEN-HOLD-RANK-01`, `S13-ANCHOR-CHECK-RANK-01`, and `S13-REVOKE-STALE-BATCH-RANK-01` distinguish target-parent ordering from target-lock ordering. Source-only; no parser or runtime qualification. Detail `CHANGE_RECORD_298.md`.

**2026-10-26 anchor-check aggregate-plan bound:** `check_anchor_v1` now applies the 200-row cap to the combined target-parent rows, selected existing open holds, and preallocated new hold IDs, and uses `MUTATION_TRANSACTION_INVALID` for over-limit refusal before row locking/DML. Acceptance detail: `S13-ANCHOR-CHECK-RANK-01`; implementation record: `CHANGE_RECORD_299.md`. Source-only; SQL parse and runtime qualification remain `NOT_RUN`.

**2026-10-26 current-turn WP0/WP2 evidence:** strict SSH status reported all nine listed Ivan stack components `True`; the local authenticated `source_health("onec-818ha-reference")` call returned `ok=true`/HTTP 200. The disposable PostgreSQL catalog session was read-only and found no `change_ledger` schema, candidate tables, or selected S13 functions; effective candidate grants are `NOT_MEASURABLE` there. See `artifacts/WP0_WP2_CURRENT_TURN_RECHECK_2026-10-26.md`. No service restart or database write occurred.

**2026-10-26 release-claim mutation preconditions:** `release_claim_v1` now freezes and compares the complete repair/ordinary parent row after ordered parent locks and before mutation; changed, missing, or cross-scope parent fails `LOCK_PLAN_STALE`. For a new `ISSUED` token it refuses an absent or differently owned target lock as `LOCK_BUSY` before token/resource updates, while non-`ISSUED` exact replay remains lookup-only ahead of that check. Acceptance `S13-RELEASE-CLAIM-RANK-01`; detail `CHANGE_RECORD_300.md`. Source-only, no parser/runtime qualification.

**2026-10-26 kill-switch idempotency:** `kill_switch_v1` now returns `OFF` without updating `kill_switch_state` or appending an event when the locked scope is already OFF. Scope/fence/lifecycle authorization checks still precede the no-op; OFF from a stopped mode retains deferred recovery and fail-closed `RECOVERY_NOT_READY`. Acceptance `S13-KILL-SWITCH-LEGACY-BRIDGE-01`; detail `CHANGE_RECORD_301.md`. Source-only, no parser/runtime qualification.

**2026-10-26 lease-generation NULL precedence:** `renew_writer_lease_v1` now uses `IS DISTINCT FROM` so a NULL requested generation fails as `TICKET_SUPERSEDED` before execution/permit checks. Acceptance `S13-LEASE-RENEW-RANK-01`; detail `CHANGE_RECORD_302.md`. Source-only, no parser/runtime qualification.

**2026-10-26 DPAPI protect-result contract correction:** `provision_windows_dpapi_ed25519_key()` accepts only bytes from pywin32 `CryptProtectData`, refusing a tuple rather than risking persisting a description as ciphertext. Safe trace of the prior mock run found `AttributeError` at public-key serialization because the fake omitted `serialization.PublicFormat`; it never reached DPAPI. The functional-test-reviewer corrected the fake and keyword-call expectations; the focused rerun passed (7 tests and 3 subtests, exit 0). Test SHA-256 `69576400F255601E34C6AE8DFC35CA1DDA12854BB2316B41049B520CB0C26423`; source SHA-256 `C5119D626BC66050439AE748E42E5697D32637EF1420A88C8E63ADDD8B3DF0B3`. Only mocks were used; real signer provisioning and trust registration remain NOT_RUN. See `CHANGE_RECORD_305.md`.

**2026-10-26 S13 migration parser and focused qualification:** candidate 027 now parses after removing the extra closing parenthesis in `revoke_stale_v1`; the `claim_v1` key-lock snapshot clarification and recovery-function CASE parentheses remain semantics-preserving. The exact focused disposable command `uv run pytest -q tests/phase2/test_s13_current_turn_sql.py` passed: 3 tests in 20.51 seconds, covering legacy OFF no-write/no-event, NULL generation precedence, and mismatched permit generation refusal. Migration SHA-256 `D5F22EAF09DA1B2A0ED4CC6D29F70860EF6D55459FF2EA1F381B932FA4C46525`; test diagnostic SHA-256 `98A4519BB7C9E1E4B17AF13661EEA4CC14CCB585B3BDCAEB65C0DDF63689841B`; HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`. The invocation-owned cluster and throwaway DB were cleaned; no lane/business DB or COM was used. This closes only three focused criteria; full S13 qualification and effective installed grants remain open. See `CHANGE_RECORD_306.md` and artifact.

**2026-10-26 S13 pre-existing-role ACL normalization:** database-reviewer found that migration 027 validated pre-existing private role attributes/memberships but revoked table privileges only from a fixed list of new S13 tables. Migration 027 now revokes `PUBLIC` and both private roles across all current schema tables, sequences and functions, removes their schema `CREATE`, and sets `ledger_owner` default privileges to withhold future schema grants. The configured disposable DB was checked through `LaneEnv` in a read-only transaction without printing its DSN: database `business_ai`, configured port 18432, server port 5432, `change_ledger` schema absent; by instruction no grant catalog query followed. Candidate hash `67CF140B2D4B62A89B1308C7F49B8005926994B3CB1039AC6D9476E54BFAA3DC`. No test, SQL parser, migration, or database write ran after this source edit; independent re-review and seeded-role qualification remain pending. The operational COM `OneCWritePort` and reviewed clone destination crosswalk are also still absent. Detail: `CHANGE_RECORD_307.md`; acceptance addendum: `S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`.

**2026-10-26 ACL-default review correction:** the database reviewer noted that PostgreSQL schema-specific default ACL revokes only subtract schema-local entries; they cannot cancel global defaults. Candidate 027 now normalizes `ledger_owner` global defaults and revokes all current schema routines (including procedures/aggregates) as well as tables/sequences before reapplying the explicit function grants. Candidate hash is now `8F6E4AC280D8CCDCE8FC3082832554018D073D8EFA30F0C1D9E068182D8E1266`. The change remains candidate-only and source re-review is pending. Disposable acceptance now seeds legacy function/procedure grants and verifies future owner-created routines; current DB effective grants remain `NOT_MEASURABLE` because `change_ledger` is absent. See `CHANGE_RECORD_307.md` and the `S13-ACL-SOURCE-ROLE-MAP-01` addendum in the qualification prerequisites.

**2026-10-26 database-CREATE ACL closure:** a subsequent database-reviewer source review found that safe role attributes (`NOCREATEDB`) do not prevent creating schemas inside the existing business database when an application role has database-level `CREATE`. Candidate migration 027 now revokes database `CREATE` from both private roles using `current_database()` and verifies `has_database_privilege(...,'CREATE')` is false; any remaining PUBLIC/other grant path raises `PRIVATE_WRITER_DATABASE_CREATE_UNSAFE` and rolls back cutover. Current candidate hash `A6EABA3DE5E974BD830D97900DE21F568F34B31B3F6A276C6899B0E564432266`. The source-only review recheck is pending. Effective grants remain `NOT_MEASURABLE` on local port 18432 because its configured DB lacks `change_ledger`; no test, parser or migration has run after this edit. Seeded-role acceptance now includes direct database CREATE and requires effective denial. See `CHANGE_RECORD_307.md`.

**2026-10-26 private-role object-ownership guard:** the database reviewer confirmed that ordinary ACL revokes do not remove implicit owner rights for existing private service roles. Candidate migration 027 now fails with `PRIVATE_WRITER_ROLE_OWNS_OBJECT` if either role owns the current database or any schema, relation/sequence, routine, type, extension or large object; ownership is not silently reassigned. Candidate hash `EA9C04087A4D452CCCD4AB4C91321A2C97549C280AF3C510CA028ACE1AB9A942`. A read-only source recheck of the catalog query is pending; effective ownership/grants remain `NOT_MEASURABLE` because the disposable DB has no candidate schema/roles. The S13 ACL acceptance now seeds ownership and requires fail-closed transactional rollback. No test, parser, migration or DB write ran after this edit. See `CHANGE_RECORD_307.md`.

**2026-10-26 ACL effective-reachability correction (supersedes prior candidate hashes in this log):** after database-reviewer flagged `living.record_migration(text,text[])` as a possible false positive for the cross-schema routine predicate, source inspection found migration 003 revokes all access to schema `living` from `PUBLIC` and does not grant `USAGE` to either new private role. The privilege check now gates table/column, sequence and routine ACL evaluation on the corresponding private role having schema `USAGE`; direct grants to the two roles continue to be revoked across non-system schemas, and reachable residual/public privileges still fail closed. No unrelated PUBLIC API grants were changed. Current candidate SHA-256 `76A191BE062AF74CB3556D674D38CC366D4E82EAF5775A84BC1F721A21384D40`; exact-predicate source re-review is pending. This is source reasoning, not a live catalog observation. No tests, SQL parser, migration, database query/write, COM, stage, commit or push was run after this edit. Detail: `CHANGE_RECORD_307.md`.

**2026-10-26 final S13 ACL candidate source re-review:** the `database-reviewer` inspected exact SHA-256 `76A191BE062AF74CB3556D674D38CC366D4E82EAF5775A84BC1F721A21384D40`. It found no syntax issue or remaining bypass within the stated persistent data/routine boundary. The new schema-`USAGE` gates correctly model whether table, sequence and routine ACLs are reachable; table-level revoke plus `has_any_column_privilege` catches surviving column grants. The candidate remains deliberately fail-closed when PUBLIC EXECUTE is still reachable in an application schema. This is source review only, not SQL parse or grant/runtime evidence. Current disposable DB still has no `change_ledger`, so effective candidate grants remain `NOT_MEASURABLE`. No tests, parser, migration, DB write, COM, stage, commit or push ran after the source correction. CR307 records the complete state.

**2026-10-26 schema-local default-ACL code correction:** source inspection found that PostgreSQL schema-specific default ACL entries are additive to global defaults. Candidate 027 now closes both global and `change_ledger`-local future table, sequence and routine privileges for `ledger_owner`; the disposable qualification criterion now explicitly verifies both layers. Exact current candidate SHA-256 `DD7A1F1F63F0ED0935D685051885DF24E43F3C6B1A1D0E5ED62F55402B2F2EF2`; current-hash database-reviewer source audit is in progress. Effective grants remain unmeasured, and no parser/test/migration/database action ran after this edit. Owner: Codex. Next: reconcile source audit and continue code closure.

**2026-10-26 candidate type-ACL hardening:** database-reviewer identified missing type default-ACL normalization as a non-blocking least-privilege gap. Migration 027 now closes `ledger_owner` type defaults globally and within `change_ledger`, revokes direct type USAGE from private roles in non-system schemas, revokes current `change_ledger` PUBLIC/private-role USAGE before the explicit per-type allowlist, and checks effective reachable type USAGE. The acceptance now seeds current type grants and checks future owner-created types and `has_type_privilege`. Candidate SHA-256 `F83FD11BB1BC3E3B83876FC25128E0BA10AACCDD2C2102681A44B4DA51B8FA33`; exact delta review pending. The type finding was not a demonstrated write bypass. No tests/parser/migration/DB/COM ran. See `docs/phase2/CHANGE_RECORD_307.md`.

**2026-10-26 final type-ACL source re-review:** database-reviewer inspected exact candidate SHA-256 `F83FD11BB1BC3E3B83876FC25128E0BA10AACCDD2C2102681A44B4DA51B8FA33`; no actionable issue was found. Global and `change_ledger`-local type defaults are both normalized, current direct USAGE grants are revoked with catalog names safely quoted (including generated row/array types), `has_type_privilege` is gated by schema USAGE, and later explicit grants restore only the intended writer/evidence types. This closes a least-privilege hardening gap, not a demonstrated data-write bypass. No parse, tests, migration, or DB operation was run. Runtime grants remain `NOT_MEASURABLE` until an approved disposable install. See `CHANGE_RECORD_307.md`.

**2026-10-26 remote DPAPI account/path ACL check:** strict SSH to `koros@100.88.71.74` read-only inspection found scheduled task `ERP_MCP_Ivan_Stack` `Ready`, principal `koros`, interactive logon, highest run level. `D:\secrets\erp_mcp` is absent on the host and was not created. Existing `D:\1c\mcp\env` ACL has owner `BUILTIN\Administrators` and explicit non-inherited FullControl ACEs for `BUILTIN\Administrators` and `IVAN\koros`; no file names or contents were inspected. No task started, no key provisioned or registered. This verifies directory permissions for `koros` but not a dedicated writer-service identity or DPAPI round-trip. Owner Codex: after S13 has the approved service/host/scope/validity registration path, provision and register D9/D10b using the authorized key workflow. See the current-turn recheck artifact.

- A names-only follow-up of remote `D:\1c\mcp\env` found no filename containing `D9`, `D10b`, `signer`, or `witness`. This is scoped to that directory and does not prove host-wide absence; file contents were not read. See current-turn recheck artifact.

- Read-only remote service/process inventory returned no 1C/1cv8/Sentinel/license service match and no `1cv8`/Sentinel/HASP process; Windows `LicenseManager` was Running and `ClipSVC` Stopped/Manual. These generic service states do not establish a 1C license. No service was started or restarted and no COM retry followed. Existing sanitized COM evidence remains the license-not-found diagnostic.

2026-10-26 16:15 UTC WP5 DPAPI provisioning source recheck: a fresh read-only `code-reviewer` pass inspected the current source after identity-checked cleanup. No actionable BLOCKER/MAJOR was found in publication or cleanup: the code captures the temporary file identity, flushes before same-directory publication, checks the published identity before returning, and only unlinks matching file identities. Review did not run tests/checks; model/effort metadata were not exposed. This does not verify parent ACL, dedicated account/host, or registry scope. Those deployment inputs remain required before key provisioning/registration on Ivan. Evidence: `docs/phase2/CHANGE_RECORD_305.md`, current-turn source-review section; reviewed file `src/erp_mcp_private_writer/signer_provisioning.py`. Accountable owner: operator; executor: Codex; reviewer execution role: code-reviewer. Next: continue WP5/S13 source coding where safe; do not provision remotely until the exact account-private path and registry identity/scope/validity are established.

2026-10-26 current-turn migration provenance reconciliation: current candidate
`db/phase2/027_private_writer_admission_schema.sql` SHA-256 is
`47983E7958BB2C48C978B324CD2587D7165F835CDBCC1AACBB2A2213D99E2293`. The ACL review recorded
above applies only to exact SHA-256
`F83FD11BB1BC3E3B83876FC25128E0BA10AACCDD2C2102681A44B4DA51B8FA33`; it does not establish review
of the current bytes. The current hash appears in the later budget-review context, which did not
cover the ACL delta. Therefore current-hash ACL review is `NOT_RUN`. No candidate source bytes,
tests, parser, migration, database, COM, stage, commit, or push were changed/run for this record
correction. Evidence and next step: `docs/phase2/CHANGE_RECORD_307.md`.

2026-10-26 WP5/S13 private-ingress Content-Length preflight: `_read_bounded_json()` now normalizes leading zeroes and compares decimal length/lexical value to the 1 MiB ceiling before integer conversion. Over-limit values take the existing 413 path before body streaming; invalid syntax retains 400 and the streaming byte limit remains the fallback for missing/understated headers. `S13-PRIVATE-INGRESS-CONTENT-LENGTH-01` requires exact ceiling, leading-zero, very-long decimal, invalid-header and zero-stream/downstream cases. Source SHA-256 `C7DAFF1C23EE350A5E246DC1E308859F469FB508599C1AEF3AFF6588E65BE2AD`; focused read-only code-reviewer pass found no issue. No tests/checks/build/CI ran; qualification remains `NOT_RUN`. Detail: `docs/phase2/CHANGE_RECORD_312.md`. Accountable owner: operator; executor: Codex; functional-test-reviewer owns later behavioral qualification after coding closes.

**2026-10-26 S13 persisted evidence resolver qualification:** focused disposable SQL matrix for candidate migration 027 SHA-256 `F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F` passed 23 tests (15 deselected). The independent database-reviewer reviewed the exact candidate SQL and found no actionable source issue; security-reviewer reviewed the resolver/service/composition plus SQL and found no actionable BLOCKER/MAJOR/MINOR. The candidate remains uninstalled and ungranted; effective configured grants remain `NOT_VERIFIED`. T16 service E2E remains `NOT_RUN`: no authenticated validator build-provenance source/policy is present. See `CHANGE_RECORD_317.md`.

**2026-10-26 checkpoint runtime authority hardening:** `DispatchGate` now requires an authority dependency, checks provider policy and admission readiness in order, fails closed on all non-`None` results, and bounds both calls by a shared five-second deadline. Exact hash `B67AB573916A3FD4F0FBA34B65915E8BB369DAD8954819B7A44B4B51D5334173`; 19 unit tests and 18 full direct regression tests passed on that exact source hash. Code/security/Python reviews confirmed the non-`None`/timeout issues closed. M1 (no concrete authenticated provider/policy authority) and M2 (external latest/readiness is not bound transactionally to permit issuance) remain activation blockers; no real provider implementation is composed and no production readiness is claimed. See `CHANGE_RECORD_318.md`.

**2026-10-26 full S13 candidate SQL qualification:** after coding closure, the complete `uv run pytest -q tests/phase2/test_s13_current_turn_sql.py` passed **38 tests in 174.20s** against migration SHA-256 `F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F` and test SHA-256 `EC85FCDC550ABC69D19BFECB49CDE3145CA3989778E4BCDBBE46D81829297853`. Tests ran only in a fresh invocation-owned loopback PostgreSQL 16 cluster with throwaway databases; cleanup passed exact owner-label/container-name verification. This does not install migration 027 on the configured lane or establish effective grants. Production registrar/T16 service E2E stays `NOT_RUN` on missing authenticated validator build provenance and external checkpoint trust. See `CHANGE_RECORD_317.md`.
**2026-10-26 S14 pure payload-to-COM helper evidence:** the code and test files were already in the
dirty worktree before this turn; origin is not verified. This turn's code-reviewer found no
actionable BLOCKER/MAJOR/MINOR, and the functional-test-reviewer ran
`uv run pytest -q tests/phase2/test_s14_com_ephemeral_value_binding.py`: **5 passed in 0.52s**.
The exact source/test/design hashes and review scope are recorded in `CHANGE_RECORD_319.md`. This
qualifies only pure payload/digest binding and value redaction. The live clone crosswalk and
operational `OneCWritePort` remain blocked by the recorded COM license failure and missing reviewed
destination/type mapping. No COM, database or lane operation occurred. Next: continue source work
that does not infer the missing external trust, key-custody or clone contracts.

2026-10-26 S14 simulated protocol-consumer E2E: `e2e-runner` ran
`uv run pytest -q tests/phase2/test_s14_simulated_write_port_protocol_e2e.py`: **4 passed in
0.49s** on synthetic in-memory state. It covers CREATE_DRAFT → POST → UNPOST, mismatch refusals,
and unknown-outcome/no-retry behavior. Exact source/test hashes and limitations are in
`CHANGE_RECORD_319.md`. This is not evidence for real 1C/COM, CT14, the licensed-clone crosswalk,
or S13 acceptance. No source files changed during the run.

2026-10-26 candidate 027 effective-grant snapshot: a database-reviewer applied exact SHA-256
`F344CA5BD839D2DCA284545F27049E7D7F34F81B0F3F907ED7076DE9AF33F91F` only in fresh owned
PostgreSQL 16.14 disposable clusters, with cleanup verified. Visible results show no direct table,
column or sequence grants to the two private service roles; `business_ai_private_writer` had 13
visible EXECUTE routines and `private_writer_evidence_ingest` none. The visible effective schema
predicates deny `living` and permit `change_ledger` USAGE. Some full function/type predicate output
was truncated and is `NOT_RECOVERABLE`; configured lane grants remain `NOT_VERIFIED`. Details and
limitations: `CHANGE_RECORD_320.md`. No migration was applied outside the disposable clusters.

The initial truncation note is superseded for five runtime roles by the final bounded per-role
follow-up in `CHANGE_RECORD_320.md`: `has_function_privilege` returned 13 rows for
`business_ai_private_writer`, 0 for `private_writer_evidence_ingest`, 9 for `checkpoint_role`,
17 for `writer_role`, and 24 for `worker_role`. Exact visible names and type/schema predicates are
in the record. `TEMP=true` is measured but its ACL attribution is `NOT_COLLECTED` because the
query filtered `TEMP` rather than `TEMPORARY`; no broader ACL was changed. Configured lane grants
remain `NOT_VERIFIED`.

The later minimal `TEMPORARY` ACL attribution attempt returned no nested execution ID, rows, or
cleanup result because the tool response was truncated; do not treat it as measured or claim its
cleanup. No broad Docker inspection or cleanup was run. Codex owns any bounded retry only with a
preserved execution ID and short per-role output; do not change PUBLIC/database ACLs from the
missing result.

That ACL attribution was subsequently recovered in a separate bounded clean fixture: `PUBLIC` has
`TEMPORARY`, and each of the five runtime roles inherits `TEMP=true` without a direct grant. No
ACL was changed. Cleanup for the earlier unidentified truncated invocation remains unverified;
full successful rows are in `CHANGE_RECORD_320.md`.

Database-reviewer found no TEMP-table creation/use in in-scope migrations/source/tests. Candidate
027 revokes database CREATE, not TEMPORARY. Keep PUBLIC TEMPORARY unchanged because repository
evidence does not prove this database is dedicated or inventory external clients; revoking PUBLIC
could break them, and a role-only revoke cannot override the inherited grant. Recorded in
`CHANGE_RECORD_320.md`.

2026-10-26 current-turn Ivan key-path recheck: strict SSH read-only query found
`D:\secrets\erp_mcp` absent and `D:\1c\mcp\env` present; names-only scan found no D9/D10b/signer/
witness filename. No contents, secret bytes, or paths were read/created. D9/D10b remain dependent
on the approved writer process identity and registry scope/validity path; do not generate under
`koros` by assumption.

2026-10-26 current-turn access refresh: exact known_hosts entry for `100.88.71.74` fingerprints as
`SHA256:Y/7fmEZDlL/+RpcokSA3OKtajipmEPdg/7BsK02VwmQ`; strict-key SSH ran read-only Ivan stack
status and all nine components returned `True`. From the project venv, an in-process 300-second
auditor token called local MCP `source_health(onec-818ha-reference)` and received
`is_error=false`, `ok=true`, HTTP 200. No token or business rows were printed; no restart or
business-data read occurred. The detailed grant and TEMPORARY disposition remains in
`CHANGE_RECORD_320.md`.

The bounded read-only S13 harness-container inventory returned only seven matching pre-existing
containers, all exited 9–11 days ago; none of the current-turn fixture names remained and no
matching container was running. No container was removed because ownership of the old exited
containers is unverified. The prior truncated invocation's exact DB cleanup remains unknown; see
`CHANGE_RECORD_320.md`.

**2026-10-27 S13 production evidence composition:** `compose_private_writer_runtime()` now rejects
duck-typed/in-memory writer-receipt verifiers and outcome providers. It requires the concrete
`PostgresWriterReceiptRegistrar` and `PostgresOutcomeEvidenceProvider`, ties the latter to that
registrar, and requires registration and `PostgresWriterEvidenceResolver` to share the same
evidence pool, attempt-source instance and `ProductionEvidenceVerifier`. The evidence pool must
differ from admission. Acceptance `S13-EVIDENCE-PROVIDER-COMPOSITION-01` is added to the disposable
prerequisites. Source SHA-256: `955EBA2B93CF6AD4BEA2C2A22C133D14F38E228C3A1186865F591776B4E4F6A8`.
Runtime composition and effective role behavior remain `NOT_RUN`/`NOT_VERIFIED`; no tests/checks,
database action or production composition ran. Detail: `CHANGE_RECORD_326.md`.

**2026-10-27 WP5 DPAPI provisioning round-trip guard:**
`provision_windows_dpapi_ed25519_key()` now unprotects the exact ciphertext under the current
Windows account and constant-time compares it with the generated seed before creating any
temporary/final file. Failure returns `SIGNER_PROVISIONING_ROUNDTRIP_FAILED`; success still
persists only ciphertext and returns public identity only. This does not establish the intended
service account, host, ACL or registry identity/scope. Source SHA-256
`87A23976EF2E1F169516D87C46C719C0DF5220D4930C7A07D98ECD09B34A574D`; acceptance
`WP5-DPAPI-PROVISION-ROUNDTRIP-01`; functional-test reviewer passed 8 tests and 9 subtests in
0.84 s (test SHA-256 `D77F1F3FDC3DAA7DE6598FDCC80859707DC9637C2B8CB6A736F9A097C7A55DD6`), and
Python/security reviews found no actionable issue. Detail: `CHANGE_RECORD_327.md`.

**2026-10-27 S13 barrier-ack active-binding guard:** candidate migration 027 now requires an exact
enabled, non-revoked base/service/host binding and holds it `FOR SHARE` before trust-revision and
advisory locks while registering/replaying an acknowledgement. The routine remains revoked, and
the configured candidate schema/roles remain absent. Candidate SQL SHA-256
`7C559B7B4278DFB9E63CBC8CBD045A77EF00FEAC6B5BC50B5B3A36BF54C8654E`; acceptance
`S13-BARRIER-ACK-SERVICE-BINDING-01`; exact SQL parse/race qualification `NOT_RUN`. Detail:
`CHANGE_RECORD_328.md`. Next: database review of this exact hash, then post-coding positive,
mismatch, zero-write, and both revocation-race cases in disposable PostgreSQL 16.

**2026-10-27 barrier-ack runtime composite-access defect:** the new disposable registration test
exposed `missing FROM-clause entry for table "scope"` before the active-binding guard. Four nested
field references now use `(p_ack.scope).tenant_id/company_id`. Current migration 027 SHA-256
`69FBAEA9018D6738416F8F20E7055F4503392F6551B0EA7CB8DD3A62F07DBAC4`; the focused
`functional-test-reviewer` rerun passed 3 tests on that exact hash in 25.70 s
(`test_s13_barrier_ack_sql.py`, test SHA-256
`74724C930C3CD9C6FC27B942A4F6748F1CD38B213DCFD2A7B8841C1C551F23A5`), covering the nested-field
path, binding mismatch/refusal with no row delta, and binding-before-trust/advisory source order.
Full ACK insertion and both concurrent revocation orders remain `NOT_RUN` while the test role
attempts a complete signed fixture. Prior candidate test results do not apply. Detail:
`CHANGE_RECORD_329.md`.

**2026-10-27 successive barrier-ACK PL/pgSQL name collisions:** the full signed fixture reached
additional registrar/trigger branches and exposed ambiguous `sk.key_id` and `p.supervisor_key_id`
references caused by row variables shadowing query aliases. The registrar now uses scalar
supervisor-key snapshots and the trigger's unused `p` row variable is removed. Current migration
027 SHA-256 `29CA6DB680C29707682B922CFA83823D4A53A1A8D79B90E18FB93272BD210FD7`. The exact command
`uv run pytest -q tests/phase2/test_s13_barrier_ack_sql.py` passed 6 tests in 50.59 s (test SHA-256
`866F8DE65F5F209AEAD13B24544636525D7D982958E035508CABCC4FFD42D1D6`). Coverage includes durable
positive insert, absent/base/service/host/revoked binding refusals with no ACK row, default-denied
EXECUTE, lock order, and both registration/revocation race orders on an invocation-owned disposable
PostgreSQL 16 fixture. Fresh database-reviewer and security-reviewer passes found no actionable
issue for this exact ACK candidate hash; they did not establish installed grants, validator build
provenance or the physical COM transaction boundary. Full S13 SQL suite and system qualification
remain open. Earlier candidate results do not qualify it. Detail: `CHANGE_RECORD_330.md`.

**2026-10-27 S12 OutcomeEvidence version-floor enforcement:** production verification now refuses V1 when an oracle is pinned for the exact scope/operation, regardless of a stale minimum floor of 1. The trust request explicitly asks for the complete bounded oracle set only for V1 outcomes; SQL fails closed above 16 rows and does not truncate. Source-only Python/database reviews found no issue; SQL parsing and runtime qualification are `NOT_RUN`. Evidence-ingest EXECUTE remains withheld pending independent identity, build-provenance and cross-tenant reviews. See `CHANGE_RECORD_332.md`.

**2026-10-27 access and S13 audit continuation:** strict-host-key SSH and the authenticated local gateway source-health result were re-observed in this turn and recorded in `CHANGE_RECORD_333.md`. The read-only effective-grants query against the configured disposable PostgreSQL 16.15 endpoint found migration-027 schema, types, routines, tables and candidate roles absent; candidate privileges are `NOT_MEASURABLE`, not an observed EXECUTE denial. Exact sanitized catalog scope is in `CHANGE_RECORD_336.md`. The S13 validator-provenance source was reviewed and its direct-registration bypass closed under `CHANGE_RECORD_334.md`; the exact source allowlist remains empty because no authorized host-bound trust provider exists. The barrier-ACK source audit found no actionable B/MAJ issue; a tentative lifecycle-state edit was reverted after tracing that `finish_barrier` changes barrier progress to `QUIESCED` while retaining lifecycle state `RECOVERING`. No source/acceptance change remains, as recorded in `CHANGE_RECORD_335.md`. No new tests, checks, builds, SQL parsing, migration, DB mutation, COM operation, local commit or push were performed in this continuation. Current next gates: complete independent S13 source closure; after all coding, assign mapped functional/E2E scenarios and exact database/security reviews; do not install/grant the candidate or invoke COM while the authorized clone license, crosswalk, trust-root/build identity and candidate-schema prerequisites remain absent.

**2026-10-27 S13 trust-snapshot isolation fix:** the candidate migration audit found that `private_writer_load_trust_snapshot_v1` did not enforce the isolation/read-only mode required for a consistent multi-query snapshot. Migration 027 now refuses non-`REPEATABLE READ READ ONLY` direct calls before registry access, and the Python adapter maps the stable refusal. Fresh focused and broader read-only database-reviewer passes found no actionable B/MAJ source issue on current migration hash `D60423AAFB89CA3F7D4C9E0B8B48E563A083550162DF7C710B2FE45690A0B90B`. No tests, SQL parsing, migration or DB call ran; runtime remains NOT_RUN and candidate schema/roles remain absent. See `CHANGE_RECORD_337.md`.

**2026-10-27 current-turn access recheck and dependency correction:** strict-host-key SSH to Ivan returned all nine stack components `True`; a top-level listing of `D:\1c\mcp` succeeded. The in-process auditor call to the local MCP returned `source_health.ok=true`, HTTP 200 for `onec-818ha-reference`; no business rows or secrets were printed. These observations demonstrate transport/source health only. The effective S13 candidate grants remain `NOT_MEASURABLE` per CHANGE_RECORD_336, and the reviewed S13 source is not runtime-qualified despite the clean source-only pass in CHANGE_RECORD_337. The concrete S14 COM writer, licensed read-only clone session, and exact property/type crosswalk remain absent or `NOT_VERIFIED`, so WP6 cannot be safely completed and WP7/WP8/WP10 remain dependency-ordered behind it. No services were restarted; no test, check, build, SQL parse, migration, database mutation, COM call, stage, commit or push occurred in this continuation. Evidence and owner-assigned next steps: `CHANGE_RECORD_338.md`.

**2026-10-27 GPT-PM S13 design adjudication:** exact request `b73cbf50-173d-4507-8af9-035668d20f7f`, correlated reply `9ca65b28-dd05-5c34-bc73-028bf7faceb3`, project `erp_mcp` / repository `xLZDx/ERP_MCP`. Verdict `ACCEPT — S13 Criterion 3: DESIGN_COMPLETE`, architecture/design contract only; 0 BLOCKER, 0 MAJOR, one MINOR `S13-DES-N01` deferred to S18. This does not approve the source candidate or close formal S13 approval, disposable qualification, effective grants, external trust, physical S14 COM writer, deployment or production. Overall S13 gate/manifest is unchanged. Details and exact correlation: `CHANGE_RECORD_338.md`.

**2026-10-27 S14 write-port payload bridge:** current shared writer source exposed a type seam: `OneCWritePort` accepts a dictionary while the COM value extractor requires `DraftPayload`. This turn added strict exact-shape decoding and a digest-bound CREATE_DRAFT wrapper in `com_manifest.py`; exact string keys are checked before set conversion. A read-only `code-reviewer` pass found and confirmed resolution of one malformed-key MINOR, then found no direct regression on source SHA-256 `E3DA7F50E129DC4329B9D6B388D9F205C9A08C056B8F7E8E21F35EE3CBBE66EF`. Functional cases were added to the acceptance contract but not run. This does not implement a COM writer or establish the 1C crosswalk. Detail: `CHANGE_RECORD_339.md`.
