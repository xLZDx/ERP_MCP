# Change Record 279 — cap stale-revocation batches by aggregate closure

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor and source-closure owner: Codex.
- Technical owner: ERP_MCP change-ledger recovery boundary; review/test roles are execution roles.
- State: source-only candidate implementation; SQL parse, migration, database operation, tests, checks, build, CI, staging, commit and push were not run.

## Baseline and change

Migration 027 and the qualification prerequisite file were already untracked before this turn; their original baseline hashes are recorded in `CHANGE_RECORD_278.md`. This turn changes the `revoke_stale_v1` source selector and extends its existing qualification scenario; inherited content remains unverified as authored by this turn.

`revoke_stale_v1` selected a fixed top-20 prefix and only afterward counted the aggregate lock/effect closure. If that prefix exceeded the 200-row cap, it raised `NOT_ACCEPTED` before per-item failure state or revocations were written. Repeated calls selected the same records, preventing the documented multi-batch progress. The selector now costs each of the ordered first 20 candidates before locking: it conservatively counts the record and possible failure row, distinct possible parent records, tokens, target rows, target/key locks, reservations and leases for lock budget; and uses the existing effect accounting for records/failure/event, tokens, keys and claimed-record transitions. It selects only the largest deterministic prefix whose cumulative lock rows and effects each fit 200. If the first candidate alone exceeds a cap, the call still refuses `NOT_ACCEPTED` before DML, preserving fail-closed handling for individually oversized work. Existing post-plan full closure counts and stale-plan revalidation remain authoritative.

The qualification scenario now distinguishes an aggregate oversized top-20 set (bounded prefix must progress over later calls) from one individually oversized candidate (refuse before DML and report blocked). It also retains fairness for previously failed items and the full lock/race requirements. Runtime qualification remains `NOT_RUN`.

## Affected paths and evidence

- `db/phase2/027_private_writer_admission_schema.sql`: `revoke_stale_v1` selector and pre-plan cap at approximately lines 7370–7425; subsequent full closure cap and revalidation remain in the same function.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `S13-REVOKE-STALE-BATCH-RANK-01` now has the aggregate-prefix and individual-oversize cases.
- A fresh read-only `database-reviewer` source pass found no BLOCKER/MAJOR in the selector. It confirmed retry-priority ordering, the first-20 bound, conservative resource estimates and retention of the locked full-plan checks. Model/effort metadata: `UNKNOWN`. This is not SQL validity or runtime-progress evidence.
- SHA-256 at this record snapshot: migration 027 `139A7120F64FE97C44BEA112A27255A0B672D6604DFC54622318DAD845084686`; qualification prerequisites `B78DB301B4A2F4092F2D6C04A2F79F7AC5BC60A63AB0C138515FE8E83CA07713`.
- Source contract: the scenario already required forward progress across multiple batches, failure-priority fairness, and refusal/reporting for oversized closure. The change makes the bounded batch reflect the same 200-row closure limit checked later.

## Limits and next action

The per-candidate estimate is conservative and does not replace the locked full-set plan. A single oversized candidate still blocks with a stable refusal; runtime progress, exact five-second budget, planner cost, lock order and error behavior are not proven. Next, finish remaining source closure, then have functional/E2E roles qualify aggregate and individual oversized cases on the approved disposable database after coding closes.
