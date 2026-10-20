# Change record 154 — minimize S13 checkpoint suffix evidence

## Goal and scope

Close the worker-role evidence disclosure found during review of CR152's bounded S13 checkpoint suffix reader. Preserve the fail-closed classifier behavior while removing raw event evidence from the worker/auditor SQL response.

## Changes and affected contracts

- Added migration `026_lifecycle_checkpoint_payload_minimization.sql`, requiring the complete 001–025 chain. It replaces the migration-025 function body without changing its signature, scope checks, worker/auditor-only grants, fixed `search_path`, owner, read-only behavior, or 128-event bound.
- The function now returns only the boolean `payload_found` for `RESOLVE_UNKNOWN`, and only when the stored JSON value is actually boolean; malformed values return `NULL`. For `VERIFY_VERIFIED`, `payload_nonempty` is true only for a nonempty JSON object. Raw payload bodies, nested values, and per-event/head hashes are not included in the result.
- Updated `LifecycleCoordinator` to require the exact minimized event schema, reject malformed summary combinations and preserve T11/T12 and T13 behavior. A valid suffix still returns `NOT_READY / SHARED_FENCE_UNAVAILABLE`.
- Updated S13 acceptance and lifecycle design records to distinguish the initial migration-025 review finding from the corrected migration-026 state. No gate status is changed.

## Verification evidence

Both agents tested the working tree based on committed HEAD `b8ff72967aec0787a70a1c91ed87ff1ed3e17d57` plus the exact uncommitted implementation/test files listed below. Commits between the original CR152 code test and this base HEAD were documentation-only. The final corrected hashes were:

- Final `db/phase2/026_lifecycle_checkpoint_payload_minimization.sql`: `9D64DF2884B6BF6D2D99B0F3FA3BF528A0690CFEAD880621AF9DEB066BD8E9F6`
- Final `src/business_ai_gateway/phase2/change_ledger/lifecycle.py`: `2542380E5F67A1A2B776D416842EFD5FCAABFB680986EA5D35CAA8E4E45D3FDD`
- Functional tests: `tests/phase2/test_s13_checkpoint_suffix_functional.py`, SHA-256 `11AC3522FFD9CA98F24182180794407816C09396A3719E794AFA20B0A8AEB74B`
- E2E tests: `tests/phase2/test_s13_checkpoint_suffix_e2e.py`, SHA-256 `6E5DF4DA546EB8780DB01330F789AD6F280C658AA332F543E73C926869B900BF`

`functional-test-reviewer` ran:

```powershell
$env:ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS='1'; & .\.venv\Scripts\python.exe tests/phase2/test_s13_checkpoint_suffix_functional.py
```

Result: **PASS**, 47 Python classifier assertions and 14 grouped PostgreSQL checks on disposable PostgreSQL 16. The SQL scenarios applied migrations 001–026 and checked role/scope, bounded suffix, no mutation, idempotent reapply, absence of raw payload and event/head hashes, malformed `found` object/string redaction, malformed verification scalar/array rejection, and T11/T12 classification.

`e2e-runner` ran:

```powershell
$env:ERP_PHASE2_ENABLE_G1_CLUSTER_TESTS='1'; & .\.venv\Scripts\python.exe tests/phase2/test_s13_checkpoint_suffix_e2e.py
```

Result: **PASS** on disposable PostgreSQL 16.14. It covered empty and valid T13 diagnostic tails, scope and anchor failures, truncation, sequence gaps, role denial, absence of raw payload and event/head hashes, malformed payload-summary cases and coordinator NOT_READY outcomes. Test environments used Python 3.14.3, asyncpg 0.32.0 and Docker 29.5.2. Each agent confirmed its owned database/container was removed; subsequent container inspection returned no object.

Fresh database, security and reliability reviews checked the exact final source hashes above and found **no remaining BLOCKER or MAJOR**. The DB reviewer confirmed migration ordering, scope, worker/auditor grants, function ownership/search_path, boundedness and snapshot/count consistency. Security confirmed both raw-payload exposure and the per-event hash inference channel are closed; only the caller-supplied checkpoint hash is echoed. Reliability confirmed concurrent append and malformed summary behavior fail closed. Reviewers did not run tests.

## Limitations and remaining S13 acceptance

- Migration 026 only corrects databases that have applied it; an environment at migration 025 retains that earlier function response until 026 is applied. No shared or production database was changed.
- This diagnostic reader still does not provide a cross-process mutation/dispatch fence, recovery-to-READY path, authenticated anti-rollback provider, bounded service transaction lifetime, physical writer coverage, or production signer/key custody. Formal S13 remains `NOT_STARTED / NOT_APPROVED`; G1–G8 remain `NOT_PASSED`; Release 2 remains `NO-GO`; production authorization remains `NONE`.
- No broader S13 story suite, restore proof, multi-process fence proof, external provider evidence or real 1C execution is claimed.

## Ownership and changed paths

- The operator is accountable for delegated project closure; GPT/Codex implemented the local correction.
- `functional-test-reviewer` and `e2e-runner` own test design/execution. Database, security and reliability reviewers own their respective reviews.
- Changed paths: migration 026; `change_ledger/lifecycle.py`; the two S13 suffix test files; `S13_STARTUP_RESTORE_LIFECYCLE_DESIGN_2026-10-17.md`; `S13_ACCEPTANCE_MAP_AND_MIGRATION_INVENTORY.md`; `S14-S19_SPRINT_PLANS_AND_ACCEPTANCE_MAP_2026-10-17.md`; this change record.
- The unrelated `governance/DOCUMENT_REGISTRY.md` and `.claude/` workspace changes were not included or modified.
