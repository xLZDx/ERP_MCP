# Sprint S10 plan — bounded dev/test capture prerequisite; production canary NOT_RUN

Date: 2026-11-08. Operator-approved rebaseline: `ERP-S10-DEV-PREREQUISITE` (dev/test only).
Current task: **R2-US-048** (R2-US-042 bounded dev/test implementation has been pushed in PR #53). Scope: `R2-REQ01`, `R2-REQ28`, `R2-TC142`–`R2-TC144`.

## Goal and acceptance

R2-US-042 implemented and qualified the dev/test runtime composition for exact-scope capture/comparison
and kill-switch ownership of its running jobs. The current task assembles exact-head evidence and keeps
unrun UAT distinct. A dev/test PASS is evidence only for that environment; it cannot set a production
approval, close G6/G7, authorize a canary, or make Release 2 GO.

- TC124: capture and comparison remain bound to the exact tenant, company, source and accepted
  scope epoch; cross-scope requests are refused before connector work.
- TC125: dev/test results remain explicitly environment-labelled and cannot satisfy production
  approval or release state.
- TC126: the scope-bound kill switch stops admission and cancels/joins the jobs it owns, without
  affecting another scope; cancellation and terminal state are observable. It must retain timed-out
  synchronous connector work in its drain inventory and atomically cancel queued work or only the
  exact RUNNING lease (worker + fence) previously acquired by its scheduler.

The dev/test composition binds the capture loop to the same accepted `ViewerScope` (tenant,
company, epoch) as the job ticket, and checks the request's tenant/source/epoch before enqueue.

For R2-US-048, TC142 requires all six S10 acceptance IDs (TC124–126 and TC142–144) with their
recorded outcomes and provenance bound to a clean exact source HEAD. TC143 requires `NOT_RUN` and
`NOT_VERIFIED` to remain explicit and forbids a release `PASS`. TC144 keeps user, admin and production
UAT as separate evidence slots; a lane remains `NOT_RUN` until its own evidence is supplied. This
bounded package is engineering evidence only and always records Release 2 as `NO-GO`.

Production canary, production data, 1C mutation, migrations, deployment and G6/G7 closure are
explicitly out of scope. R2-US-048 began only after the technical R2-US-042 implementation,
task-mapped tests and required reviews were complete. S11 remains held until S10 closes.

## Design decision

Two options were considered: (A) wire capture endpoints and worker state into the serving runtime
and its production job store now; (B) add a bounded dev/test runtime composition around the existing
typed capture loop and job contracts, with no production serving path. Choose **B** because it
exercises the frozen capture/kill-switch contract while preserving the read-only production surface
and avoiding an unapproved production canary or schema change. The decisive criterion is the
operator's dev/test-only authorization and the existing production read-only invariant.

The composition must validate scope and environment before dispatch, keep active task ownership
scope-local, stop admission before cancellation, await task termination, and fail closed on unknown
scope/state. It must not accept model-supplied URLs, credentials, SQL or executable 1C code. The
existing synchronous connector boundary remains isolated from the event loop. Rollback is disabling
the dev/test composition and returning to the prior runtime path; no persisted production state is
introduced.

## Failure modes and verification plan

Required negatives: wrong tenant/company/source/epoch, production environment, malformed or missing
kill-switch state, simultaneous start/stop, connector refusal/failure, cancellation while running,
and proof that one scope's switch cannot cancel another scope's work. Verify TC124–TC126 with
synthetic test data only. No test or runtime result is evidence of production approval. Test authors
and executors remain `functional-test-reviewer` and `e2e-runner` after coding is complete.

## Ordered S10 work

1. R2-US-042 dev/test implementation and exact TC124–126 evidence (bounded technical closure delivered by PR #53).
2. R2-US-048 release-evidence package and TC142–144 (current); production UAT/canary/release approval remain separately gated and may remain NOT_RUN.
3. Close S10 only when its bounded criteria and exact-head evidence are reconciled; do not start S11
   before then.

## R2-US-048 current evidence checkpoint — 2026-11-08

- Exact source candidate: `490d7638ea6ec84ccf856312237161fbfa94f584`, pushed on PR #53. The four task-mapped runs total 45/45 passing (11 + 22 functional; 4 + 8 CLI/capture E2E), with every JUnit testcase carrying that candidate head and no failures, errors or skips.
- Internal code/security/silent-failure reviews and GPT-PM code review are complete for the source candidate; GPT-PM's minor parser finding was fixed and re-reviewed. This does not review or approve the assembled manifest artifact.
- The committed input record maps TC124–126 and TC142–144 to the synthetic runs. User/admin/production UAT slots are all `NOT_RUN`; Release 2 remains `NO-GO`.
- Remaining before S10 closure: generate the fixed-path manifest from the current clean pushed PR head, inspect its six case mappings/UAT lanes/NO-GO, obtain GPT-PM review of the exact manifest, and push the artifact. Do not start S11 until this current task is closed.
