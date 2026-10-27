# Change Record 198 — stable bounded-timeout validation

## What changed

- Reordered finite/range validation in the PostgreSQL trust source, evidence attempt/key/registration/outcome adapters, production verifier, and admission store. Bounded numeric range checks now reject oversized integers before `math.isfinite` converts them to float.
- Valid timeout values and their bounds are unchanged; invalid values continue to use each adapter's existing stable `ValueError` code.

## Why

`math.isfinite()` may raise `OverflowError` when passed an arbitrarily large Python integer. That bypassed the documented constructor validation error on malformed deployment configuration. Checking the already-defined positive upper bound first preserves fail-fast behavior without leaking a conversion exception.

## Evidence and verification state

- Current source SHA-256: `postgres_evidence_trust.py` `0C7D32AE8D4591F2A4C3CCCAD5D20B70A57DC8AE2EFA92B70DBEDB998F8C9DB2`; `postgres_evidence_registrar.py` `6BD3772B4F7A3887EC07C67A0D2F4B7B5E40EE2E56CA31F6ECA1E1D004A036E1`; `postgres_outcome_provider.py` `11660F5F388CD12A2D9C7BCA5D525BEB34A7A8743F332A8354A8872E1DA883F0`; `evidence_key_resolver.py` `5556ED3F4623569E1C16010A0C3B4DB7C867BCD05274EBF3FB03056367AF6574`; `postgres_attempt_source.py` `2305F3F8BBA0BBC8FA5017373EE76D0B56479EE73339C655BED873B731B35CA1`; `production_evidence_verifier.py` `7CCF2EA7E95C23D98970DB9E2046A9A9DFCA435A182C15E332681F08A1E6E1CB`; `postgres_store.py` `C815952A065FA4CD1C56CB91A2FAE1E5BF9C9348DFBE253E28A6C42A743EE6C7`.
- `src/erp_mcp_private_writer/service.py` SHA-256 after stable barrier-timeout conversion: `0863FC3862BFD8F97E3D4C287ED58264B15C1EE046EFD4D04066BA9C11CF63D3`.
- Qualification plan `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md` current SHA-256: `D356AD6BD740DA6BC24E2B7C4BE262B6A59F73E1B97DFEF23AF08286FA4B37C6` (recomputed after the later S13 candidate cases were added).
- Source inspection only. Tests/checks/build, database operations, migration, staging, commit, push, and runtime qualification were not run.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: include oversized-integer timeout rejection and valid-boundary controls in the functional test cases after source coding closes; database and runtime qualification remain separate gates.
