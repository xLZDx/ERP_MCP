# Change Record 374 - the line VAT amount is part of the approved payload

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; code by the implementation-engineer agent and the coordinator; tests written and
  run by the functional-test-reviewer agent.
- Decision basis: option C of Change Record 373. The question was auto-answered with the recommended option because the operator
  sent no message within the policy window (logged by the question policy); the operator may revert it.

## Change

- `Line` gets a required `vat_amount` (non-negative canonical decimal text like `amount`; zero allowed) in
  `src/business_ai_gateway/phase2/change/proposal.py`: the dataclass, `_LINE_KEYS`, `_parse_lines`, `payload_to_dict`. It is
  therefore in the canonical payload and in the payload digest the approver signs.
- Consumers updated: `src/business_ai_gateway/phase2/simulation/clone_1c.py`, `src/erp_mcp_private_writer/com_manifest.py`
  (`_DRAFT_LINE_FIELDS`, write-port rebuild), `src/business_ai_gateway/phase2/simulation/synthetic_data.py` (derives the amount
  from the synthetic VAT code with the VAT-inclusive formula, two places, same random draw order as before), the contract draft
  `docs/phase2/S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md`.
- Defect found by the test agent and fixed here: `Line` accepted `None` for `price`, `amount` and now `vat_amount`, because the
  check compared `None != None`. A new `_is_canonical_decimal` refuses anything that is not a canonical `str`.
- The SQL files were checked for line-field handling: none (the `amount` hits are budget grants, not lines).

## Tests (agent-written and agent-run)

- New file `tests/phase2/test_s14_vat_amount_contract.py`: 72 passed (digest changes with `vat_amount`; binding coverage; write-port
  refusals; canonicalization on both paths; boundary and invalid values; generator payloads round-trip through the real parser;
  same seed gives identical payloads).
- Full `tests/phase2` after the fixes (saved output line): 7154 passed, 602 skipped, 13 errors, 159 subtests passed. The first run,
  before the generator and `None` fixes, had 32 failed and 26 errors.
- The 13 errors are the documented direct-run harness scripts (`fixture 'db'`/`'led' not found`), the same set as the earlier
  baseline. The 602 skips are unchanged and almost all need `ERP_PHASE2_TEST_DSN`, so the SQL digest tests did not run.

## Not established

- NOT_RUN: Postgres-backed digest tests, mutation runs, reviewer consensus, GPT-PM review. The VAT code table (code to
  enumeration value, Change Record 372) is not wired in yet; the production binding set is still empty and the writer stays
  UNQUALIFIED and disabled.
