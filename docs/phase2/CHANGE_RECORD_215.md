# Change Record 215 — reject overflowing JSON floats at private ingress

## What changed

- The private-ingress JSON decoder now rejects floating-point tokens that parse to `NaN` or either infinity, including exponent overflow such as `1e9999`.
- Added a qualification scenario requiring rejection before dispatch, lookup or verifier calls while preserving finite-number parsing.

## Why

`json.loads(parse_constant=...)` rejects explicit non-standard `NaN` and `Infinity` tokens, but its default float parser can convert a valid-looking exponent outside binary-float range to infinity. Letting that value reach typed payload parsing or digest construction creates inconsistent and non-standard JSON behavior at a trust boundary.

## Evidence and verification state

- Changed code: candidate `src/erp_mcp_private_writer/private_ingress.py`, `_read_bounded_json` and `_parse_finite_json_float`.
- Qualification contract: `docs/phase2/S12_S13_DISPOSABLE_QUALIFICATION_PREREQUISITES_2026-10-23.md`, `S13-PRIVATE-INGRESS-JSON-NUMBER-01`.
- Source SHA-256 after this change: `2BAE3A9484414054D00BC9E92DB1578B9F9D06934C496A53D798259CF88A1942`.
- Source inspection only. No tests/checks/build, listener startup or runtime qualification was run. Qualification remains `NOT_RUN`.

## Ownership and next step

Accountable owner: operator. Executor: Codex. Next: continue S13 source closure; after code completion, have the functional/E2E roles prove malformed numeric input is refused before any service/verifier call and finite payloads retain their existing digest contract.
