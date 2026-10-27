# Change record: S13 private writer design for Ivan's licensed lane

## Summary and reason

Recorded the operator-authorized S13 writer decision as a private-service design contract. The
accepted direction is a separate writer service on Ivan's licensed lane, starting
with the disposable `818HA_p2diff` clone, private loopback/Tailscale access, durable call-ID
idempotency, stale-epoch rejection, authoritative outcome lookup, and a quiescence barrier.

## Affected paths

- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md` — service boundary, inherited
  S12 contract, ownership, admission/lookup/barrier/restart rules, source-final lock/grant limits,
  implementation order and acceptance matrix.
- `docs/phase2/artifacts/WP4_WP10_DEPENDENCIES_2026-10-21.md` — current owner correction and
  dependency status for S13 and downstream WP5–WP8/WP10, including the confirmed absence of a
  deployed/effective-grant claim, a current-turn read-only catalog query against the disposable
  local PostgreSQL instance, and the remaining source-level fence prerequisites.
- `core/LESSONS_LOG.md` — records the distinction between source-level lock inventory and a
  qualified full-path fence, and the need to record the operator's technical-owner decision.
- `docs/commits/2026-10-22-s13-ivan-writer-design.md` — this linked change record.

## Decisions and safety boundaries

- The operator is accountable for the delegated work; the Ivan stack owns the technical
  connection/host boundary; Codex executes repository work.
- The design explicitly keeps the public MCP gateway read-only, keeps 022–024 unchanged and
  non-activated, prohibits a readiness transition before full fence coverage, and retains
  unresolved-call holds after timeout or process loss.
- The candidate common order uses one nonblocking transaction mutex for ledger mutation and
  recovery, so a caller-held advisory lock cannot wait on it; its performance, grant coverage,
  trigger behavior, lock-timeout handling and full path coverage remain subject to database and
  reliability review. `CLOSED_WITH_HOLD` and `QUIESCED` are separate barrier states; unresolved
  calls never count as readiness.
- The design does not claim effective grants on Ivan's host, qualified COM behavior, S13
  acceptance, production readiness, or authorization to deploy/write a live company base.

## Review and verification state

An actual read-only `architect` reviewer found no concrete contradiction or architecture finding
against the accepted S12/S13 contracts. An actual read-only `database-reviewer` found that a
table/trigger-only fence would be unsafe: existing trigger ordering can take the event-chain
advisory lock before a lifecycle row lock; `validate` takes the business-key advisory lock after
the record row; `declare_business_key` and `bind_duplicate_override` have related key/record
ordering; and verifier-key receipt guards add another advisory lock. Lifecycle coverage does not
cover every granted registry, evidence, budget, hold, key, observation, and recovery path. The
review therefore requires a complete granted-API/helper map and one reviewed global lock order
before a forward additive migration; the event-chain lock remains last. It also confirms that a
short database epoch transaction cannot quiesce an already admitted physical COM call, so database
admission and the writer service's durable barrier must share a protocol. Migration 023's recovery
refusal and `NOT_READY` remain required until that work is complete.

A read-only database follow-up additionally required the eventual common-order proof to include
the `recover_sweep`/`revoke_stale`/`kill_switch` advisory and row-lock chains, plus unique-index
conflict arbitration (`ON CONFLICT`) for reservation, permit, recovery-counter, evidence, receipt,
policy, observation and registry paths. These are explicit design prerequisites, not claims that
the current source already follows the future order. A new candidate serial-mutex protocol was
then reviewed independently: the database reviewer required nonblocking mutex acquisition so a
caller holding an advisory lock cannot wait while another writer holds the mutex; the reliability
reviewer required distinct closed-with-hold and fully-quiesced states. Both findings were applied
to the design. The targeted database reviewer (GPT-6 Luna, medium effort) found that the function
cannot roll back its caller's transaction. The contract now requires a dedicated fresh top-level
transaction and full client rollback/discard on every refusal or SQL error, with no savepoint
catch-and-continue; follow-up confirmed this closes the caller-held-lock cycle at contract level.
The targeted reliability reviewer (GPT-6 Luna, medium effort) found that a closed barrier with
unresolved calls could be confused with readiness. The contract now distinguishes
`CLOSED_WITH_HOLD` from `QUIESCED`; follow-up confirmed the ambiguity is closed and retained
startup-before-listener admission as an implementation qualification condition. Implementation
must still prove that every API/service path follows the transaction rule and that the complete
grant/trigger inventory participates. The candidate is not yet a qualified lock order and does not
authorize migration design or readiness.

A further targeted database-review follow-up found the singleton row needed schema-level proof.
The design now requires a fixed primary-key value, exactly one bootstrap row, runtime revocation
of delete/truncate/direct table access, and fail-closed acquisition if no row is selected. The
reviewer confirmed that this closes the singleton-invariant concern; full API, trigger and recovery
path coverage remains an implementation and qualification condition.

Codex also ran an independent read-only query in a transaction against the local disposable
`business_ai` database on port 18432, loading its admin DSN in process via `LaneEnv` without
printing credentials. `pg_roles` returned the four lane roles; the `change_ledger` table-grant and
function privilege result sets were empty because that schema is absent. This is not deployed
grant evidence. No migration ran.

No tests, checks, builds, CI, migrations, COM calls, clone writes, or service deployment were run.
This is a design artifact only; implementation and functional/E2E qualification remain open. No
push or PR is authorized by this record.

## Exact-patch review correction

The previous exact staged patch review returned `BLOCK` with zero BLOCKER findings, one MAJOR
dependency inconsistency, and one MINOR obsolete contention scenario. Both findings are corrected
in this revision: WP4's S13 service foundation uses an injected writer port, WP6 owns the physical
COM/S14 adapter, and final S12/S13/S14 acceptance follows dependency-ordered coding and
qualification. The contention scenario uses the private singleton row with
`SELECT ... FOR UPDATE NOWAIT`; `MUTATION_BUSY` requires full top-level rollback/discard even when
the caller holds an unrelated advisory lock, no savepoint catch-and-continue, and successful
subsequent writer progress. A follow-up review approved that exact patch for one local
documentation commit and closed both findings, while noting one non-blocking sequencing
ambiguity: step 1 could be read as running S12 qualification before coding is complete. The
sequence now states that step 1 only resolves the S12 clarification and records qualification
prerequisites; actual qualification remains in the post-coding test phase. This final wording
revision awaits exact-patch review before its local commit.
