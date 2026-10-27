# Change Record 369 - closed value vocabulary for enumeration bindings

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session (code); tests written and run by the
  functional-test-reviewer agent.
- Changes `src/erp_mcp_private_writer/com_manifest.py` and adds `tests/phase2/test_s14_com_value_map.py`.

## Change

- `PayloadPropertyBinding` gets an optional `value_map` (a tuple of payload value / 1C value pairs). It is validated at
  construction (non-empty, pairs of printable stripped strings, unique sources, else `COM_VALUE_MAP_INVALID`) and applied by
  `translate()`; a payload value outside the table, or a non-string, is refused with `COM_VALUE_NOT_MAPPED`.
- Translation happens in the single place that pairs bindings with payload values, so the digest manifest and the ephemeral COM
  values both carry the translated 1C value and stay consistent. Bindings without a map behave as before.
- Why: Change Records 367 and 368 found that `vat_rate_code` is free identity text; a closed vocabulary at the binding boundary
  prevents an arbitrary string from reaching the enumeration.
- The production binding set is still empty and the writer stays UNQUALIFIED and disabled; no VAT table is wired in yet.

## Tests (agent-written and agent-run)

- New file: 38 tests (mapped codes, digest consistency between manifest and ephemeral value, unmapped codes on all three paths,
  contract refusal of empty and 33-character codes, 17 invalid-map cases, unchanged behavior without a map).
- Runs reported by the agent: new file 38 passed; new file plus the existing binding test 43 passed; all 14 test files that import
  `erp_mcp_private_writer`: 132 passed, 85 subtests passed, 0 failed.

## Not established

- NOT_RUN: mutation runs (not performed by decision), wider suite, reviewer consensus and GPT-PM review of this change.
- The VAT table itself, the amount recomputation behavior and any COM write remain open.
