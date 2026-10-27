# Change record 188 — enforce the measured writer line-count bound

## What changed

`parse_writer_payload()` now rejects a `CREATE_DRAFT` whose normalized payload has more lines than
`MEASURED_SHAPE_MAX_LINES` before it can be passed to the private writer.

## Why

The private-writer boundary added in change 186 reused the shared typed parser and payload digest,
but did not apply the proposal parser's measured-shape ceiling. The frozen S12 scope is one
qualified receipt shape, and the shared source defines the currently measured maximum as one line.
An approved digest must not turn a wider, unqualified draft into an admissible private-writer call.

## Affected contract and paths

- `src/business_ai_gateway/phase2/change/proposal.py` — `parse_writer_payload()` applies
  `MEASURED_SHAPE_MAX_LINES` after typed parsing and before returning the payload.
- `docs/phase2/S12_CONTRACT_FREEZE_V2_2026-10-16.md`, §1 — v2.0 is limited to one qualified
  receipt shape.
- `src/business_ai_gateway/phase2/change/proposal.py`, `MEASURED_SHAPE_MAX_LINES` and
  `_shape_refusal()` — shared measured line-count ceiling.

## Decisions and boundaries

- The check runs after `_parse_draft()` so it counts normalized typed lines, and before any private
  writer admission or physical call.
- This check does not qualify a currency, 1C property/section mapping, target precondition, or
  effective right. Those still require the authenticated clone mapping and S12/S13 qualification.
- It does not enable the S13 selector or any physical write.

## Verification state

- Manually inspected the parser return branches and confirmed POST/UNPOST retain their empty-object
  contract.
- No tests/checks, build, SQL parsing, migration, database operation, COM operation, service
  restart, listener, staging, commit, or push was run. Behavioral acceptance remains `NOT_RUN`.

## Remaining acceptance and ownership

This closes the local code omission for the shared maximum line count only. Currency and physical
mapping qualification remain open. The operator is accountable task owner; Codex is executor; the
Ivan stack is the technical owner of the existing remote host boundary. Next: continue a
contract-backed source closure pass and keep dispatch disabled until the authenticated clone map,
writer identity, and atomic target-version precondition are qualified.
