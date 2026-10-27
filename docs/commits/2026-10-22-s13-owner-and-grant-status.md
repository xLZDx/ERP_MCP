# Change record: Reconcile S13 owner and grant status

## Summary

Updated the current S13 row in `docs/phase2/OPERATOR_BACKLOG.md` to match the operator's verified
ownership correction and the current read-only disposable-database grant evidence.

## Why

The prior row treated the Ivan host/service boundary owner as unidentified and omitted the latest
local PostgreSQL catalog result. The operator explicitly assigned accountability to the operator,
the Ivan stack (`ERP_MCP_Ivan_Stack`) as technical owner of the host/connection boundary, and
Codex as local implementation executor. The project-venv database query found no `change_ledger`
schema on the disposable local instance, so post-migration effective grants cannot be claimed.

## Affected paths and contract

- `docs/phase2/OPERATOR_BACKLOG.md` — S13 owner roles, current NOT_VERIFIED grant evidence, and
  next dependency sequence.
- `core/LESSONS_LOG.md` — distinguishes accountable task ownership from technical host/connection
  ownership and from the executor role.
- This change record documents the correction.

The S13 boundary remains a separate private service on Ivan's licensed lane. This update changes
ownership/evidence wording only; it does not apply migrations, change grants, restart services, or
claim writer qualification.

## Verification state

- Compared the S13 backlog row with the operator's 2026-10-22 verified correction.
- Reused the current-turn read-only query evidence against disposable PostgreSQL on port 18432:
  `change_ledger` schema, matching table grants, and matching functions were absent. No credentials
  or database URL are included here.
- No tests, checks, builds, CI, migrations, database writes, COM calls, service restarts, or remote
  writes were performed for this documentation correction.
