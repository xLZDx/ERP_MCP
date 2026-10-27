# Change Record 343 — mechanical ruff cleanup of four clean phase2 files

## Ownership and scope

- Date: 2026-10-27.
- Accountable owner: operator; executor: Claude Code session.
- Covers only `src/business_ai_gateway/phase2/change/transitions.py`,
  `tests/phase2/test_change_offline.py`, `tests/phase2/test_change_ledger_sql.py`,
  `tests/phase2/test_change_registry_sql.py`, this record and the matching `core/DECISION_LOG.md` and
  `core/LESSONS_LOG.md` entries. Only files with no pre-existing modification were touched; files under
  active S13 work (`src/erp_mcp_private_writer/`, new untracked tests) were deliberately left alone.

## Why

Step A2 of the continuation plan asks to address ruff findings in phase2 code. The four files carried 91
mechanical findings (unnecessary `dict()`/`list()` calls, unused imports, unsorted imports and `__all__`,
verbose `Decimal` constructors, printf-style formatting, unused unpacked variables).

## Change

`ruff --fix --unsafe-fixes` on the four files. Every transformation is behaviour-neutral by construction
(call to literal, import order, removal of an unused import, `Decimal("1")` form, f-string for `%`
formatting, `_` for an unused unpacked name). The three remaining `DTZ001` findings (naive `datetime`
in `test_change_offline.py`) are real test-data choices and were not changed.

`testlane/onec_extension/scripts/ct14_measure.py` was fixed by the same command and then reverted to its
committed content, because it is an evidence-bound 1C measurement script whose bytes may be pinned.

## Contracts and paths affected

None. No public name, signature or behaviour changes (the set of 153 function/class definitions in
`transitions.py` and their signatures were compared with HEAD and are identical).

## Verification state

Static only: `py_compile` passes on the four files and ruff reports 3 findings (the `DTZ001` ones) across
them. pytest NOT_RUN; the test agents own the run.
