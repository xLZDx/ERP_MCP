# Change Record 231 — freeze SQL adapter function catalogs

## What changed

- Wrapped the legacy, lifecycle and opt-in S13 SQL function catalogs in read-only mapping proxies.
- Wrapped the SQL type-cast catalog in a read-only mapping proxy.
- Froze the lifecycle required-checkpoint-event catalog as a `frozenset`.
- Added qualification cases `S13-SQL-PORT-FUNCTION-CATALOG-IMMUTABILITY-01` and `S13-LIFECYCLE-REQUIRED-EVENT-SET-IMMUTABILITY-01` covering mutation rejection and preservation of routing/lifecycle classification.

## Why

`SqlChangeLedger.invoke` derives SQL routine names, caller classes, signatures, candidate-vs-legacy routing, and safe cast substitutions from module-level catalogs. Mutable dictionaries allowed item mutation of that dispatch surface after import, bypassing the adapter's constructor-time configuration freeze. The catalogs now reject item assignment/deletion. Lifecycle suffix classification also depends on an exact set of events that require checkpoint inclusion; a mutable set could alter that integrity rule at runtime, so it is now immutable.

## Affected contracts and paths

- `src/business_ai_gateway/phase2/change_ledger/sql_ledger.py`
- `src/business_ai_gateway/phase2/change_ledger/lifecycle.py`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`

The change affects in-process SQL adapter metadata and lifecycle classification only. It does not install or grant SQL routines, change an effective database role, enable S13, or prove a PostgreSQL-to-COM transaction boundary.

## Verification state and provenance

The SQL adapter was already modified in the worktree before this turn; its pre-edit whole-file hash was not captured. This turn's focused changes replaced mutable catalog literals with `MappingProxyType` wrappers and changed the required lifecycle event collection to `frozenset`. Current whole-file hashes include earlier worktree changes: `sql_ledger.py` SHA-256 `1460897AC8763C25F426B94D5C847FCDCB746C589E839219452FE9B45CDC58FD`; `lifecycle.py` SHA-256 `8E6B94DE917C21F7824C81B34B63DCC4F21F9602D44B1F8DD2C8114DA63F0D6E`; qualification prerequisites SHA-256 `D1F86DBE24363E35CC387545DE50E3D948783F9B05E19FC763CF33950FAD1D5A`.

No tests, checks, builds, CI, migrations, SQL parsing, database calls, COM calls, service restarts, staging, commits, or pushes ran. The new runtime qualification case remains `NOT_RUN` until source coding closes and the functional-test owner executes it.

## Local review

One actual read-only `code-reviewer` agent pass reviewed only the current-turn catalog/set immutability hunks and separated them from pre-existing worktree changes. It reported no material findings; it confirmed existing mapping operations remain compatible and the checkpoint event collection is used only for membership. Reviewer role: `code-reviewer`; configured role model/effort: GPT-6 Luna, low. No test source was edited or executed.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue S13 source closure; after coding completion, assign both cases to `functional-test-reviewer` and include catalog stability and candidate-route rejection in the mapped disposable qualification. Effective grants and installed candidate schema remain separate evidence gates.
