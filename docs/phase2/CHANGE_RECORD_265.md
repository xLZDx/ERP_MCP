# Change Record 265 — require an exact caller-class selector

## What changed

- `SqlChangeLedger.invoke` now accepts `as_class=None` for the documented default, or an exact built-in string matching the caller-class identifier syntax.
- Empty values, non-strings, `str` subclasses, and objects with caller-defined equality are rejected as `ACTOR_INVALID` before opening a transaction or issuing SQL.
- The constructor now accepts only exact built-in actor-map keys from `CLASSES` and exact built-in identifier strings for mapped database roles (with `None` retained as the unmapped value).
- Expanded `S13-SQL-PORT-ACTOR-SELECTOR-01` and added `S13-SQL-PORT-ACTOR-MAP-01` for these cases; both retain `NOT_RUN` state.

## Why

Caller-class selection chooses the database role mapped by the adapter. Authorization must compare only plain built-in strings against the immutable function allowlist and actor map; arbitrary Python equality behavior must not influence that decision. `None` remains the sole omitted-selector value and selects the first class in the route specification.

## Evidence and limits

- Implementation: `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py:318-322,337-348`.
- Qualification criteria: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md:1140-1142`.
- This is a source change only. Functional qualification has not run; no tests, checks, build, CI, database operation, migration, COM call, staging, commit, or push was performed.
- The containing SQL ledger file had pre-existing modifications before this turn; this record covers only the constructor and selector validation changes above.
- Current full-file SHA-256 (includes those pre-existing modifications): `F2C653E134E59FBA131AA76D245C2283067C85B2B2244705445B5E78EA2D05B5`.

## Ownership and next gate

Accountable task owner: operator. Executor: Codex. After coding is complete, `functional-test-reviewer` owns the mapped selector cases, including a custom object whose equality method would otherwise match an allowed class. Runtime evidence remains `NOT_RUN` until that post-coding test phase.
