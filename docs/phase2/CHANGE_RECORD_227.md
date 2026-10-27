# Change Record 227 — freeze SQL ledger authorization configuration

## What changed

- `SqlChangeLedger` now freezes the connection reference, copied actor-to-role map, lifecycle-fence flag, and private-writer-schema flag after construction.
- The actor map uses a read-only mapping wrapper so callers cannot mutate role selection through the stored mapping.
- Lifecycle and private-writer flags require exact booleans; invalid truthy values fail with `S13_CONFIGURATION_INVALID`.
- Added the source-only qualification case `S13-SQL-PORT-CONFIG-IMMUTABILITY-01`, including caller-map isolation and zero database calls on rejected mutation.

## Why

The adapter's actor map chooses the PostgreSQL role assumed for each operation. Replacing that map after construction can change the effective privilege path without changing the adapter identity. Mutable route flags can likewise change which SQL routine is called after composition. These values are composition-time security configuration and must remain stable for the adapter lifetime.

## Affected contracts and paths

- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `core/LESSONS_LOG.md`
- `docs/phase2/OPERATOR_BACKLOG.md`

## Verification state

The SQL ledger source was already modified before this turn; its pre-edit hash is `NOT_RECORDED`. Source SHA-256 after the initial Change 227 configuration freeze and before the separate Change 228 actor-selector edit: `03D68DA386533B76602C8EF5EDEA85245D54F9BA68AA07D55CB794A027E54B29`. A follow-up added `__slots__` to close the instance-dictionary bypass after the selector change; current combined source SHA-256 is `28B1ADAF6159BDF6A27F4A16FEB7953F3DA8A378D8895745B32D7D3CDD1B44AB`.

Qualification prerequisite SHA-256: `B410A0B6FC5CFA54B867AD245F85BF4A393A915417405C96C9AC044BB4954862`.

Source inspection only. Tests, checks, builds, database calls, migration application, COM activity, staging, commit, and push did not run. The qualification case remains `NOT_RUN`; the current disposable PostgreSQL instance still has no candidate S13 schema or dedicated candidate roles.

## Ownership and next step

Accountable owner: operator. Executor: Codex. After coding closes, `functional-test-reviewer` owns focused behavior tests for mutation rejection and map isolation. Continue the source-to-SQL lock/grant crosswalk before candidate installation or runtime qualification.
