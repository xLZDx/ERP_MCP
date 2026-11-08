# Sprint S10 plan — bounded dev/test capture prerequisite; production canary NOT_RUN

Date: 2026-11-08. Operator-approved rebaseline: `ERP-S10-DEV-PREREQUISITE` (dev/test only).
Current task: **R2-US-042**. Scope: `R2-REQ15`, `R2-REQ28`, `R2-TC124`–`R2-TC126`.

## Goal and acceptance

Implement and qualify the dev/test runtime composition for exact-scope capture/comparison and
kill-switch ownership of its running jobs. A dev/test PASS is evidence only for that environment;
it cannot set a production approval, close G6/G7, authorize a canary, or make Release 2 GO.

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

Production canary, production data, 1C mutation, migrations, deployment and G6/G7 closure are
explicitly out of scope. R2-US-048 must not begin until the technical R2-US-042 implementation,
task-mapped tests and required reviews are complete. S11 remains held until S10 closes.

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

1. R2-US-042 dev/test implementation and exact TC124–126 evidence (current).
2. R2-US-048 release-evidence package and TC142–144 only after R2-US-042 is technically closed;
   production UAT/canary/release approval remain separately gated and may remain NOT_RUN.
3. Close S10 only when its bounded criteria and exact-head evidence are reconciled; do not start S11
   before then.
