# Change Record 306 — quote S13 binding session-user identifiers

## Ownership and state

- Date: 2026-10-26.
- Accountable task owner: operator, by explicit delegation.
- Executor: Codex.
- Technical owner: ERP_MCP S13 PostgreSQL admission candidate.
- Acceptance: `S13-CANDIDATE-MIGRATION-PARSE-01` and focused `S13-LEASE-RENEW-RANK-01` run.
- State: candidate migration 027 installs through the focused disposable fixture and its three
  mapped S13 SQL scenarios pass. Broader S13 qualification, installed grants outside the throwaway
  cluster, and writer/COM boundary remain open; an independent database review of the exact
  candidate is in progress.

## Change and reason

The first corrected S13 SQL run reached candidate migration 027 and PostgreSQL rejected its first
table definition with `syntax error at or near "session_user"` at line 58. The candidate used
unquoted `session_user` as a column/record-field identifier even though PostgreSQL parses that
token as its session identity keyword. Quoted the existing lowercase column name in table
definitions, constraints, DML, and record-field references. Bare `session_user`/`SESSION_USER`
expressions that intentionally obtain the authenticated PostgreSQL role remain unchanged.

## Affected paths

- `db/phase2/027_private_writer_admission_schema.sql` — quote the S13 binding column and field
  references without changing stored column names or the session-identity expression.
- `docs/phase2/CODEX_CONTINUATION_PROMPT_2026-10-22.md` — record failed setup and source fix.

## Verification

- Authorized E2E test-role command before the fix: `uv run pytest -q tests/phase2/test_s13_current_turn_sql.py`; exit 1, three setup errors, all while applying
  migration 027 at the first unquoted column. No acceptance body ran.
- The second invocation after quoting the column passed the previous syntax point but failed in
  the same migration with `LEDGER_ROLE_UNSAFE`. Migration 004 creates `ledger_owner` without
  `NOINHERIT`, so fresh PostgreSQL uses the default `INHERIT`. Candidate 027 now rejects unsafe
  privilege attributes and any role membership first, then applies `ALTER ROLE ledger_owner NOINHERIT`
  and verifies the result. That invocation used candidate hash
  `95244FFA020A172B34EDFE68ED647046C4CA1B9FF321D98C43382717B594C3CB`. No acceptance body ran in
  that attempt either.
- Invocation-owned disposable PostgreSQL harness reported cleanup of its unique database and no
  change to four pre-existing exited containers.
- Candidate migration SHA-256 after the latest two source corrections:
  `56A9CA5CF182EB652C52FA549C4A5AA6B22B81DC6410BAAB970D1986F4DD3E28`.
- The next focused run captured SQLSTATE `42601` with `internal_position=433480` and context
  `PL/pgSQL function inline_code_block line 5 at EXECUTE`. The offset maps into `claim_v1` near
  the post-fence key-lock plan at candidate line 6916. The mapped `IF`, scalar subquery, CASE,
  `array_append` calls and loop are balanced on source review; this position is diagnostic only,
  not a root-cause finding. Exact candidate-body identity: 785,447 bytes,
  SHA-256 `933D530CD9B0599833C5F4FFF36FDE81ED3DF94F2B3A8C52998DBFC52EEC63F1`. SQLSTATE/context
  and safe identity are in `artifacts/WP0_WP2_CURRENT_TURN_RECHECK_2026-10-26.md`; no DSN was
  recorded. Three setup errors occurred; test bodies remain `NOT_RUN`; fixture cleanup was
  observed. No installed/live schema or effective grant is claimed.
- Codex materialized the `claim_v1` post-fence owned-key aggregate into
  `current_owned_key_snapshot` and compared it in explicit present/empty branches. This preserves
  the prior zero-or-one-row plan contract while removing the scalar-subquery-versus-CASE form. It
  is retained as a diagnostic-guided clarification; that earlier offset's root cause was not
  established.
- A second parser diagnostic localized `revoke_stale_v1` near its planned-record key-lock checks.
  Source review found one extra closing parenthesis in the preceding empty-plan `EXISTS` predicate:
  `epoch_deps_current(...)` plus `EXISTS(...)` requires two closing parentheses, not three. Codex
  removed the extra parenthesis. The current candidate SHA-256 is
  `BFF7E4D1B8012926C563782047F2E42E4CDA224EA0B1F93CA1B10D9D150FE32D`; one focused disposable
  rerun is in progress. This is the first concrete source grammar defect identified from the later
  parser location; do not claim the migration parses until the run confirms it.
- The run on that candidate still failed with SQLSTATE `42601`, `internal_position=617219`, context
  `PL/pgSQL function inline_code_block line 5 at EXECUTE`; the offset maps to
  `private_writer_recover_sweep_core_v1` around the `FOREACH cid IN ARRAY ids` loop. Database
  source review checked the full function and found balanced block counts and valid FOREACH
  declaration, with no concrete syntax defect. The diagnostic formatter omitted PostgreSQL's
  message text, so cause remains `UNKNOWN`; no source fix is inferred from this second position.
  The E2E role confirmed the message is `syntax error at end of input`; the offset snippet centers
  on the global-key `FOREACH` loops. A follow-up source review found no defect in those loops. To
  test a bounded parser-robustness hypothesis without changing arithmetic, Codex parenthesized all
  four `CASE WHEN p_defer_events THEN 2 ELSE 0 END` expressions used by IF row/effect-cap predicates
  in this function. This is semantically equivalent source, not a proven cause. Current candidate
  SHA-256: `D5F22EAF09DA1B2A0ED4CC6D29F70860EF6D55459FF2EA1F381B932FA4C46525`; a focused disposable
  rerun with sanitized error message and context subsequently passed (see below).
- Focused disposable qualification command `uv run pytest -q tests/phase2/test_s13_current_turn_sql.py`
  passed with exit 0: three mapped tests passed in 20.51 seconds, covering kill-switch legacy OFF
  no-write/no-event, NULL-generation refusal ordering, and mismatched-generation refusal before
  locked permit. HEAD `3e12436bc874f6aa12b33cdee1ef6111ee33b25c`; migration SHA-256
  `D5F22EAF09DA1B2A0ED4CC6D29F70860EF6D55459FF2EA1F381B932FA4C46525`; test diagnostic SHA-256
  `98A4519BB7C9E1E4B17AF13661EEA4CC14CCB585B3BDCAEB65C0DDF63689841B`. Run used only the
  invocation-owned disposable PostgreSQL cluster and throwaway DB; no lane/business DB, COM, or
  existing container was touched. Fixture cleanup completed. This verifies three criteria only,
  not the full S13 suite or installed grants.
- The parser fix was one surplus closing parenthesis in the empty-plan `EXISTS` condition inside
  `revoke_stale_v1`; source semantics are unchanged. The broader function checks remain narrowly
  focused as described above. Current migration SHA-256 is
  `D5F22EAF09DA1B2A0ED4CC6D29F70860EF6D55459FF2EA1F381B932FA4C46525`.

## Next steps

1. Repeat the focused test-role run against the corrected candidate in its invocation-owned
   disposable database; fix any subsequent parser/runtime failures in source and repeat.
2. After the focused criteria pass and all S13 code is closed, run the complete mapped S13 suite,
   then obtain the required independent database/security reviews on the exact source.
3. Do not apply the candidate to a lane or non-disposable database before the accepted qualification
   and authorization gates.
