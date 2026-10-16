# Change record 113 — add S13 kill-switch recovery runtime evidence

## What changed

- Added `tests/phase2/test_s13_migration020.py`, a focused direct PostgreSQL harness for migration 020.
- Added `tests/phase2/s13_migration020_e2e.py`, exercising the critical OFF/retry flow through the application adapter.

## Why

Migration 020 was part of the local unpushed prototype series but had no runtime evidence. These tests link its safety behavior to the acceptance criteria in `S13_KILL_SWITCH_RECOVERY_DESIGN.md` without claiming formal S13 approval or production evidence.

## Functional runtime evidence

- Command: `.venv\\Scripts\\python.exe tests\\phase2\\test_s13_migration020.py` — exit 0, against worktree HEAD `19605848b8fb760d7aaac93395db2d13f1577a61` plus the uncommitted migration/test assets.
- Verified clean STOP→OFF and idempotent repeated OFF; invalid mode/scope and non-operator refusal; signatures, return values and grants; each allowed active hold blocks OFF including `RLC_UNCLEAN`.
- Verified poisoned T5x retains STOP while eligible T9 work and failure evidence commit; repair/retry clears the failure before OFF; delayed T12/VERIFY remain unresolved; cleanup requires successful/terminal handling for T12, VERIFY, REVOKE_STALE, and GAP_BOUND.
- Verified 100 of 101 eligible claims process in one batch, the first OFF remains blocked, and concurrent sweep calls serialize without duplicate T3 handling.
- Disposable container `r2-s13-dump-5e73ace7ec8c-a`, PostgreSQL image digest `sha256:4b7183ac05f8ef417db21fd72d71047a4238340c261d3cc3ddb6d579ab5071ae`. The harness verified its owner label before cleanup; exact-name post-run inspection found no container.

## End-to-end evidence

- Command: `.venv\\Scripts\\python.exe tests\\phase2\\s13_migration020_e2e.py` — 1/1 journey passed at code HEAD `ffccbc393f10ba487ce4612561532f72b9805b56`.
- Through `SqlChangeLedger.kill_switch`, the first OFF retained STOP and recorded BLOCKED with sweep progress and unresolved work; repair/retry cleared the failure, OFF remained blocked until dispatch resolution, then OFF succeeded. Repeated OFF started no sweep.
- Disposable container `r2-s13-dump-a4cff19f641c-a`, same PostgreSQL image digest. The run confirmed the owned container and anonymous volume absent after cleanup.

## Scope and remaining reviews

- This record reports local synthetic database behavior only. Formal S13 remains unapproved; G1–G8, Release 2, deployed systems and production authorization are unchanged.
- Fresh `database-reviewer`, `reliability-reviewer`, `security-reviewer`, and final exact-head GPT review remain pending.

## Affected paths

- `tests/phase2/test_s13_migration020.py`
- `tests/phase2/s13_migration020_e2e.py`
- `docs/phase2/CHANGE_RECORD_113.md`
