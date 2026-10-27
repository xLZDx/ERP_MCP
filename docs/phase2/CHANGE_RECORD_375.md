# Change Record 375 - reviewed closed table from payload VAT codes to 1C enumeration values (draft)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session (module); tests written and run by the
  functional-test-reviewer agent.
- Adds `src/erp_mcp_private_writer/com_vat_table.py` and `tests/phase2/test_s14_com_vat_table.py`. No existing file changes.

## Change

- `VAT_RATE_CODE_TO_ENUM_VALUE`: `VAT0` to `НДС0` (0%), `VAT10` to `НДС_10` (10%), `VAT20` to `НДС18` (20%). The targets follow the
  displayed synonyms of Change Record 372, not the legacy value names (`НДС10` displays 8%, `НДС20` is unused).
- `vat_rate_binding(payload_path, property_path)` returns a `PayloadPropertyBinding` carrying that closed table, so any other code is
  refused with `COM_VALUE_NOT_MAPPED`.
- The table is a DRAFT until the clone crosswalk review accepts it. It is not wired into any binding set, the production binding set
  is still empty, and the writer stays UNQUALIFIED and disabled.

## Tests (agent-written and agent-run)

- New file: 33 passed. With the value-map and `vat_amount` contract files: 154 passed in one run (49 and 72 individually).
- They pin the exact targets, assert via the artifact synonyms that the targets are 0%, 10% and 20% (the legacy-name trap), assert
  that `НДС10` and `НДС20` are never targets, and cover refusal of unknown codes and digest equality through the real extraction
  paths. No mutation runs.

## Not established

- The eight-percent rate has no payload code; adding one needs a payload contract decision. NOT_RUN: the wider suite for this
  addition, reviewer consensus and GPT-PM review.
