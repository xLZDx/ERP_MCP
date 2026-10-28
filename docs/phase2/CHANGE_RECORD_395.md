# Change record 395 - S12 contract amendment: amount consistency and distinct refusal codes

## What changed

- `src/business_ai_gateway/phase2/change/errors.py`: codes `AMOUNT_INCONSISTENT`, `PERIOD_CLOSED`, `GRANT_EXHAUSTED` (registry 36 to 39) with fixed messages and next actions.
- `types.py`: `BudgetCheck.EXHAUSTED`.
- `policy.py`: `reserve` returns `GRANT_EXHAUSTED` when the grant has no remainder and the amount is positive.
- `transitions.py`: `_budget_error` maps EXHAUSTED; `BeginApplyEvidence.period_closed`; guard `period_open` before `state_digest_equal` in T6.
- `proposal.py`: `_line_amounts_consistent` (Decimal-exact, half-up to 0.01, VAT-inclusive, closed VAT0/10/20 table) applied in `_parse_draft`, so `parse_proposal` and `parse_writer_payload` both refuse with `AMOUNT_INCONSISTENT`.
- `docs/phase2/S12_CONTRACT_AMENDMENT_2026-10-28.md`: the amendment, open VAT-convention decision, list of tests that must change.

## Why

Operator decisions of 2026-10-28 (G1 amounts, G2 codes) from the S12 offline qualification report; exit scenarios E6 and E24.

## Affected contracts and paths

Error registry, T6 guard list, budget check vocabulary, proposal parsing, S14 writer payload parsing (`erp_mcp_private_writer/service.py` treats any `Refusal` as `PAYLOAD_INVALID`; unchanged). Approval digest and SQL are not changed. SQL migrations still emit `BUDGET_EXCEEDED` for an exhausted grant (applied migrations not edited).

## Verification state

Byte-compiled the five changed modules and `ruff check --select F,E9` passed. A direct import check confirmed 39 codes and the consistency function on four sample lines. The test suite was NOT run (coordinator rule); existing tests listed in the amendment will need updating, and new tests are required. Full `ruff check` reports pre-existing style findings across the package (not introduced here).

## Verification (added at commit time)

- Agent-run by the functional-test-reviewer: 2143 passed, 6 skipped, 0 failed across 50 files (every test_change_*, test_s12_*, test_s14* and every file importing phase2.change, phase2.simulation or erp_mcp_private_writer), PostgreSQL 16.14 on a task-owned container (removed). The 6 skips are the dump/restore tests that need r2-s13-dump-* containers (NOT_RUN). No mutation runs.
- Tests changed: registry count 36 to 39; E6/E24 rewritten to the new codes; VAT sweep tests use rate code VATX (amount check only); new tests/phase2/test_s12_amendment_395_offline.py (75 tests). The synthetic generator now rounds amounts half up to 0.01 so its output passes the new rule.

## Operator-facing assumption recorded

- The amount rule assumes the VAT-inclusive convention: any production binding must set the 1C "amount includes VAT" constant to TRUE. A binding with FALSE would make the stored total differ from the line amount; the S15 oracle already computes expected totals from that flag. Not yet enforced mechanically (binding set is empty).

## Still open

- SQL migrations still raise BUDGET_EXCEEDED for an exhausted grant (a new migration would be needed); nothing yet produces period_closed from a real 1C read; no independent review of this diff yet; GPT-PM NOT_RUN.

## Review resolutions

- BEGIN_APPLY period evidence now fails closed. `BeginApplyEvidence.period_observed_open` (default False) must be True to proceed. A positive closed observation (`period_closed` True) is refused as PERIOD_CLOSED; an absent observation is refused as DIGEST_MISMATCH (the existing code for an unobserved business-state change).
- A `vat_rate_code` outside the closed table (VAT0, VAT10, VAT20) is refused as AMOUNT_INCONSISTENT. `vat_rate_percent_table()` exposes the engine table as pure data so a test can compare it with `erp_mcp_private_writer.com_vat_table` (VAT20 maps to the legacy 1C value name `НДС18`, which holds 20 percent, per that module).
- Decimal `ArithmeticError` can no longer escape `parse_proposal` or `parse_writer_payload`; it returns the SCHEMA_INVALID bad-input refusal.
- `erp_mcp_private_writer.refusal_mapping.map_executor_refusal(code, outcome_unknown)` is the production mapping from executor refusals to `CALL_UNKNOWN` or `REFUSED_BEFORE_WRITE`. Any ambiguity or unknown code stays `CALL_UNKNOWN`.
- Out of scope, backlog: the SQL layer (db/phase2 reservation/claim raising BUDGET_EXCEEDED for an exhausted grant) needs a new migration; until then the Python policy and the SQL ledger intentionally differ.
- VAT-on-top documents (vat_amount = amount x rate / 100) are unsupported and refused as AMOUNT_INCONSISTENT.
- The production binding must set the includes-VAT constant TRUE.
- Producers still missing: nothing yet produces `BudgetCheck.EXHAUSTED` or the period observation (`period_closed` / `period_observed_open`) from a real read.
