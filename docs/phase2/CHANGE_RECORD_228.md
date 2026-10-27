# Change Record 228 — reject invalid explicit SQL caller selectors

## What changed

- `SqlChangeLedger.invoke` now selects the first function class only when `as_class is None`.
- An explicitly supplied empty string no longer falls through to a default role; it reaches the existing allowlist check and raises `ACTOR_INVALID` before opening a transaction.
- Added qualification case `S13-SQL-PORT-ACTOR-SELECTOR-01` for omitted/default, allowed explicit, and invalid explicit selectors.

## Why

The adapter's default role is a documented choice for an omitted selector. A falsey but explicitly supplied value is a malformed request and must not silently select a different privilege context. Rejecting it before transaction setup also makes the no-database-call boundary explicit.

## Affected contracts and paths

- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`
- `core/LESSONS_LOG.md`
- `docs/phase2/OPERATOR_BACKLOG.md`

## Verification state

The source file already contained pre-existing changes and the earlier change-record-227 edit when this one-line adjustment began; the immediate pre-edit SHA-256 was not captured. Source SHA-256 after the Change 228 selector edit and before the later slots addition for Change 227 configuration hardening: `DA8A794BDDC9DEEA3C97B9790D637D48CD9990F0C5D2573FEE42926676B84B0D`.

Source inspection only. Tests, checks, builds, database calls, migration application, COM activity, staging, commit, and push did not run. The new qualification case remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. After coding closes, `functional-test-reviewer` owns focused tests for role selection and zero database calls on invalid selectors. Continue source/grant closure before disposable installation or runtime qualification.
