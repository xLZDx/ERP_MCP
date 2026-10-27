# Change record 337 — enforce repeatable-read trust snapshots in SQL

## Ownership and baseline

- Date: 2026-10-27.
- Accountable owner: operator; implementation owner: Codex; finding source: read-only database-reviewer audit.
- The current candidate migration is a pre-existing untracked shared-worktree artifact. Its hash was observed as `94B34F0FAAEEC4E3F71172A061ED74F972C5B0DB17F320E88B5F5061DD99D5AA` immediately before this focused edit; earlier migration deltas are not attributed here.
- S13 contract: `S13-TRUST-SNAPSHOT-ISOLATION-01`, added to the disposable qualification prerequisites.

## Finding and implementation

The Python `PostgresEvidenceTrustSource` already starts a top-level `REPEATABLE READ READ ONLY` transaction, and refuses when a connection is already in a transaction. The candidate SQL function `private_writer_load_trust_snapshot_v1` checked only `SESSION_USER`, then ran multiple registry queries. A direct invocation under `READ COMMITTED` could therefore associate a revision read with a mixed set of registry rows.

The SQL routine now refuses any transaction other than `repeatable read` and `read only` before any trust-registry query, with stable code `TRUST_SNAPSHOT_TRANSACTION_INVALID` (`P0001`). The Python PostgreSQL adapter maps that code to the same sanitized `EvidenceTrustSourceError` instead of collapsing it into a generic lookup error. The qualification contract now requires direct-call refusal under `READ COMMITTED`, `SERIALIZABLE`, and read/write mode, zero trust data returned, plus a top-level adapter path.

## Verification state and limitations

- No tests, SQL parse, migration, database call, check, build, or production composition ran for this change.
- A fresh read-only `database-reviewer` pass inspected the exact post-fix hashes and found no actionable BLOCKER/MAJOR issue: SQL lines 474–477 check isolation/read-only before trust-registry reads, the adapter lines 84–96 enforces no existing transaction and starts a top-level transaction, and lines 134–143 map the stable error. The reviewer did not parse/execute SQL or establish runtime behavior.
- A broader follow-up read-only database source audit rechecked exact migration hash `D60423AAFB89CA3F7D4C9E0B8B48E563A083550162DF7C710B2FE45690A0B90B` and found no further actionable source-level BLOCKER/MAJOR in the reviewed S13 schema/ACL, trust/evidence, admission/idempotency, lifecycle/terminal, barrier, transaction and advisory-lock paths. This still does not prove runtime behavior or effective grants. The migration remains an untracked candidate and its prior hash provenance limitation remains recorded in `CHANGE_RECORD_335.md`.
- The candidate schema and roles remain absent from the disposable database. This source fix does not establish runtime behavior, effective grants, trusted build provenance, tenant identity mapping, or production authorization.

## Current hashes

- `db/phase2/027_private_writer_admission_schema.sql`: `D60423AAFB89CA3F7D4C9E0B8B48E563A083550162DF7C710B2FE45690A0B90B`.
- `src/erp_mcp_private_writer/postgres_evidence_trust.py`: `6348B6E74AF642B989EAB084B21F583BBD5CD387D334846F0085ACC1EEC30E5B`.
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `C99D3F7DAF443549EFE7A77575EA054E1748ABC59E91F2E026835F6238BEB0BA`.

## Ordered next work

1. Codex obtains exact-source database/Python review of these hashes and fixes any valid issue before calling code closure.
2. After all S12/S13/S14/WP5–WP8/WP10 coding is complete, `functional-test-reviewer` owns the mapped isolation and registry-race cases on an invocation-owned disposable PostgreSQL database.
3. Candidate installation and effective-grants measurement remain disabled until code, tests, independent authorization reviews, and external trust/deployment prerequisites close.
