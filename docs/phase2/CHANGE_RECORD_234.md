# Change Record 234 — keep writer marker checks outside metaclass hooks

## What changed

- Replaced `isinstance(writer, NonOperationalWritePort)` with identity membership in the concrete writer type's MRO, read through `type.__getattribute__`.
- Read the concrete class's own namespace through `type.__getattribute__` before checking its `operational` declaration.
- Extended `S13-OPERATIONAL-WRITER-COMPOSITION-01` with metaclass sentinels for `__instancecheck__` and `__getattribute__`.

## Why

The composition guard is intended to reject a non-operational writer without executing injected dependency behavior. Although method validation now uses static lookup, ordinary `isinstance` and `writer_type.__dict__` access can route through a custom metaclass. Using the base `type` implementation and checking the MRO avoids those user-defined hooks for the skeleton-exclusion and class-marker checks. This remains an accidental-skeleton guard, not build provenance, host authentication, key custody, or deployment authorization.

## Baseline and provenance

Before this focused edit, the target files were already untracked in a large pre-existing dirty worktree. Their observed current-turn starting hashes were:

- `src/erp_mcp_private_writer/runtime_composition.py`: `5C5FE006093AF213AF5780B67257D66E0EF5B40C965B9D7DC7A5B58C85E7F5B0`
- `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`: `C2A0BF53661B337153AAB3D5EE2250C89AB2675C90EDD8CB60DEE4854250FEBE`

Only the class-MRO/namespace lookup, this added qualification condition, and this detail record are attributable to this edit.

## Verification state

- Code is implemented; no test, check, build, SQL parse, migration, DB/COM call, staging, commit, or push was run.
- The composition acceptance remains `NOT_RUN`; the metaclass sentinel must be executed by the functional-test reviewer after coding closure.
- Source review of the immediately preceding static-method change found no material issue, but it did not cover this new metaclass edit. A fresh exact-diff review remains required before code closure.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Functional-test-reviewer owns the later qualification. Continue the S13 source closure; keep the operational COM writer disabled until the exact clone mapping and authenticated writer identity are available and reviewed.
