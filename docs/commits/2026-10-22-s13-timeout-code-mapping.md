# Change record: document S13 lock and PostgreSQL error protocol corrections

Date: 2026-10-22  
Scope: S13 lock ordering and stable refusal-code contract; Python documentation and S13 design documentation. The runtime transaction isolation/fence protocol is not implemented here.

## What changed

- Clarified the existing Python fallback contract in a docstring: explicit contract messages remain explicit, `42501` maps to `NOT_ENTITLED`, and other SQL errors retain `SQL_<state>`. In the reviewed diff, `_common.py` executable logic is unchanged; raw `55P03` already falls through to `SQL_55P03`.
- Updated the S13 scope-fence and private-writer service designs to require a fresh top-level `READ COMMITTED` transaction, with isolation set before any SQL that can establish a snapshot. The separate PostgreSQL admission-schema proposal is not modified in this patch.
- Defined lock ordering on actual advisory-lock integer keys: derive, deduplicate, and sort the acquired integer resources within each namespace rank. This covers hash collisions for namespace 6 and existing multi-key namespaces 2–4.
- Preserved namespace 5 after source inspection found migration 020 already uses it for recovery-sweep serialization; assigned namespace 7 to the new scope fence. The rank now includes the existing switch-to-sweep edge before global-ID locks.
- Required authoritative non-locking lifecycle checks after the scope fence, followed by the lifecycle row lock and state/epoch recheck at its declared row-lock rank.
- Specified that only a future dedicated blocking-fence helper may map its own bounded lock attempt to `LEDGER_LOCK_TIMEOUT`. Statement cancellation (`57014`), deadlock (`40P01`), and unrelated `55P03` remain distinct fail-closed outcomes; this patch does not implement the helper.

## Why

An adversarial review of an earlier lock-protocol proposal found snapshot-isolation ambiguity, multi-key hash-collision ordering risk, lifecycle-row rank ambiguity, and an overbroad proposed `55P03` timeout mapping. The source inspection confirmed the lifecycle helper takes `FOR SHARE` and the existing `take_lock` maps names to a namespace integer plus `hashtext` key. PostgreSQL uses `55P03` for lock-not-available conditions beyond the S13 blocking-fence timeout, so the future dedicated bounded fence helper must own timeout provenance; the current Python adapter continues to preserve raw SQLSTATEs.

The review arrived through a PM Bridge request whose project header incorrectly identified `ERP` / `D:\Repo\ERP`; it is used here as a defect lead only, not as an ERP_MCP approval or commit authorization. Each correction was checked against the local ERP_MCP sources and designs before editing.

## Contracts and paths

- `src/business_ai_gateway/phase2/change_ledger/_common.py`: generic SQLSTATE-to-code fallback.
- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`: documented adapter error contract only; no executable transaction-isolation or fence-acquisition change.
- `docs/phase2/S13_SCOPE_FENCE_IMPLEMENTATION_DESIGN_2026-10-22.md`: isolation, scope fence, collision-aware ordering, lifecycle-row rank, timeout provenance.
- `docs/phase2/S13_POSTGRES_ADMISSION_SCHEMA_DESIGN_2026-10-22.md`: consulted as a related proposal, but unmodified and not part of this patch.
- `docs/phase2/S13_IVAN_PRIVATE_WRITER_SERVICE_DESIGN_2026-10-22.md`: admission sequencing.
- `docs/phase2/S13_ACCEPTANCE_MAP_AND_MIGRATION_INVENTORY.md`: records the misrouted review as `REVISE`, not an ERP_MCP commit approval.
- `core/LESSONS_LOG.md`: append-only lesson on validating lock semantics against PostgreSQL error codes and actual hashed resources.

No migration, runtime database, COM call, deployment, or public MCP surface was changed. S13 remains unqualified and `NOT_READY`.

## Verification state

- Manually inspected the local `take_lock` implementation in `db/phase2/008_change_hardening_b.sql` and lifecycle-row helper in `db/phase2/024_restore_caller_lock_timeout.sql`.
- Manually inspected `code_from_message`: explicit contract messages are checked before SQLSTATE fallbacks, `42501` maps to `NOT_ENTITLED`, and raw `55P03` reaches the existing `SQL_55P03` fallback. The diff changes explanatory docstrings only in `_common.py` and `sql_ledger.py`; it does not change executable mapping or transaction behavior.
- A fresh read-only `code-reviewer` agent pass over the pre-namespace-correction working tree found no material findings. A follow-up read-only pass over the namespace-7/rank adjustment found no lock-order contradiction and confirmed the 2→5 edge from `kill_switch` to sweep recovery. It found one minor lesson-log drift; that wording has now been corrected to distinguish namespace-5 sweep, namespace-6 IDs, and namespace-7 scope-fence collision behavior. The role uses its configured GPT-6 Luna model; exact reasoning effort is not exposed by the agent result. Neither pass ran tests or reviewed an implementation, and the planned scenarios remain unverified.
- Correlated PM Bridge review `d9f2bb82-5519-4d7c-9a8e-8b8c8b907a31` returned `REVISE` for attachment SHA-256 `7F18293E6609B86406525BE3C2D55531EEFE8CF28D5E7FA36691B70A479F5372` (0 BLOCKER, 2 MAJOR, 0 MINOR, 1 INFO). Its two MAJOR findings concerned disputed prior-review provenance and omission of this change record; the acceptance map now records the prior claim as UNVERIFIED and the linked record is included.
- Correlated PM Bridge review `7eac430f-8930-4676-ae2f-dbbd462e34cf` returned `REVISE` for attachment SHA-256 `E63704676FA8960B33F90BAD4D1E9C4C38E831BA804AE1D857700693F08130AD` (0 BLOCKER, 2 MAJOR). It confirmed those two findings were closed, then identified two new record-accuracy defects: this record overstated a Python executable mapping change, and called the attached patch stale-staged even though the attachment was a worktree diff. This revision corrects both claims. A fresh exact-hash review is still required.
- The review attachment is a generated worktree diff against `HEAD`, not a claim that the Git index is synchronized. The index contains earlier staged content on several paths. If the exact corrected patch is approved, stage only its seven reviewed paths and verify the staged content matches before committing. No paths from this package have been staged as part of this review cycle.
- Correlated PM Bridge review `cf6fc604-4227-45c0-90aa-517ea3112a96` approved SHA-256 `48975A61164AF22166FEFF1250E2BFA07C2DD37155BB5CC46D6CFE69BBCBCFD1` (0 BLOCKER, 0 MAJOR) for one local commit of the exact seven-path worktree diff. While preparing the staged-content comparison, a further record-scope omission was found: the detail file listed the related admission-schema proposal without saying it was unmodified and outside this patch. This correction changes the approved patch, so that approval does not cover the current contents and a new exact-hash review is required.
- No tests, checks, builds, CI, migrations, or database writes were run. Runtime behavior remains `NOT_RUN` for the designated functional/E2E phase.

## Ownership and next step

- Accountable owner: operator; executor: Codex.
- Next: obtain a new exact-hash ERP_MCP review of the corrected package; if approved, stage the seven reviewed paths explicitly, verify the staged diff, and make one local commit. Then complete the source-wide API/helper/trigger/conflict map before migration work. After all coding, have the authorized functional-test reviewer cover explicit fence-timeout provenance, raw `55P03`, statement cancellation, deadlock, fresh-snapshot barrier races, switch-gate concurrency, sweep lock order, and collision-aware multi-key order; obtain database/reliability/security review on the exact tested head.
