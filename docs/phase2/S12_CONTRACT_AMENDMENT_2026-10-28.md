# S12 contract amendment (2026-10-28)

Amends the frozen S12 interface contract (`S12_INTERFACE_CONTRACT_DRAFT_2026-10-12.md` section 10, error registry; `S12_CONTRACT_FREEZE_V2_2026-10-16.md`). Authority: operator decisions of 2026-10-28 (G1, G2) from `S12_OFFLINE_QUALIFICATION_REPORT_2026-10-28.md`. Scenario ids E6 and E24. The approval digest format (`S12-APPROVAL-2`) and the SQL ledger are not changed.

## What changed

1. Registry grows from 36 to 39 codes (appended, existing order kept):
   - `AMOUNT_INCONSISTENT` (FIX_REQUEST): a line amount or VAT amount disagrees with quantity, price and rate.
   - `PERIOD_CLOSED` (CONTACT_OPERATOR): at `begin_apply` the authenticated target read observed a closed accounting period.
   - `GRANT_EXHAUSTED` (CONTACT_OPERATOR): the grant has nothing left (`reserved + consumed >= limit`) and a positive amount was requested.
2. `BUDGET_EXCEEDED` is kept for every other budget refusal: a positive request larger than a non-zero remainder, a request outside the grant window, an unknown or inactive grant, and the fail-closed `NOT_CHECKED`. A zero-amount request on a full grant is still accepted.
3. New `BudgetCheck.EXHAUSTED`; claim/validate guards map it to `GRANT_EXHAUSTED`. `policy.reserve` returns `GRANT_EXHAUSTED` in the exhausted case.
4. New `BeginApplyEvidence.period_closed` (default False) and guard `period_open`, placed in T6 immediately before `state_digest_equal`. Only a positively observed closed period gives `PERIOD_CLOSED`; any other business-state change (including a period status not observed) stays `DIGEST_MISMATCH`.
5. Amount consistency in `parse_proposal` / `parse_writer_payload` (shared `_parse_draft`), per line, Decimal-exact, half-up rounding to 0.01 (money context with 80 digits, no precision loss):
   - `amount == round(quantity x price, 2)`;
   - for `vat_rate_code` in {`VAT0`: 0, `VAT10`: 10, `VAT20`: 20} (mirror of the S14 closed VAT table): `vat_amount == round(amount x rate / (100 + rate), 2)` (VAT-inclusive convention, document total = amount);
   - a code outside the table has no known rate: only the amount rule applies (the COM writer refuses unmapped codes).
   Mismatch returns `Refusal(AMOUNT_INCONSISTENT, "propose")`, after structure and scope checks and before reference-scope and shape refusals.

## Why

E6 requires a total different from lines + VAT to be refused; E24 requires distinct codes for a closed period and an exhausted grant. Previously both were only digest-bound or mapped to other codes.

## Open decision for the operator

The payload carries no includes-VAT flag. The rule above uses the VAT-inclusive formula because every S12/S14 fixture and the synthetic generator already use it. It requires the writer to set the 1C includes-VAT flag TRUE (S15 `ExpectedReceipt.includes_vat=True`); the measured clone default is FALSE (total = amount + VAT). If the exclusive convention is wanted instead, change the divisor in `_line_amounts_consistent` to 100 and update fixtures.

## Backward compatibility

- Proposals with consistent amounts are unaffected; digests are unchanged. Previously accepted inconsistent proposals are now refused.
- Code values are strings; consumers switching on the 36 codes see three new values. Callers that received `BUDGET_EXCEEDED` for a fully spent grant now receive `GRANT_EXHAUSTED`.
- SQL: migrations (`004`, `008`, `027`) still raise `BUDGET_EXCEEDED` for an exhausted grant. They are applied and were not edited; a new migration is needed if the ledger must emit `GRANT_EXHAUSTED`. NOT DONE.
- `period_closed` has no producer yet: the real period state comes from the 1C read (NOT_RUN).

## Existing tests whose expectations must change

- `tests/phase2/test_change_offline.py`: the registry test around line 194-195 (`CONTRACT_ERROR_CODES`, `== 36`); the budget parametrizations at lines 587-589, 699-701 and 808 only if they use an exhausted grant (EXCEEDED mapping is unchanged); the randomized evidence test near line 2132 (`list(BudgetCheck)` now includes EXHAUSTED).
- `tests/phase2/test_s12_exit_scenarios_offline.py`: `budget_check` helper (line 136-144, map `GRANT_EXHAUSTED` to `BudgetCheck.EXHAUSTED`); `test_e24_queued_expiry_period_change_and_exhausted_grant_are_refused_with_zero_port_calls` (expects `BUDGET_EXCEEDED` and `DIGEST_MISMATCH`; now `GRANT_EXHAUSTED` and, with `period_closed=True`, `PERIOD_CLOSED`); `test_e6_closed_period_shows_up_as_a_changed_business_state_digest_and_blocks_before_the_port`; `test_e6_total_amount_is_carried_exactly_as_the_approver_saw_it` (amount 999.00 is now refused with `AMOUNT_INCONSISTENT`); `test_e6_vat_rates_are_accepted_as_data_and_are_bound_into_the_approval_digest` (VAT10 1.91, VAT20 3.50 stay valid; the `vat_amount="9.99"` tweak and VAT0 with amount 21.00 and vat 0 are fine, the 9.99 case is now refused); `test_e6_mixed_vat_in_one_document_is_not_an_admitted_shape` (still SHAPE_NOT_QUALIFIED if consistent); the SCENARIO_MAP not_run notes at lines 1154 and 1229; the boundary at line 593 (check the grant used).
- `tests/phase2/test_change_offline.py` line 316 area (`price="0", amount="0.00", vat_amount="0.000"`): still consistent.
- Tests that call the parser with hand-set amounts: `tests/phase2/test_s14_vat_amount_contract.py` (`_raw` helper: amount 21, VAT20 default 3.5 is consistent; any case passing a different `vat_amount` through the parser, e.g. the vat_amount sweep tests, now gets a refusal), and `tests/phase2/test_s14_vat_amount_sql_digest.py` (same helper shape). Tests that build `Line(...)` directly are unaffected.
- New tests needed: AMOUNT_INCONSISTENT (amount, VAT, rounding half-up, unmapped code, 48-digit product), GRANT_EXHAUSTED vs BUDGET_EXCEEDED boundary, PERIOD_CLOSED at T6 with and without a digest change.

## Review resolutions (CR-395)

- Period evidence fails closed: `BeginApplyEvidence.period_observed_open` must be True; `period_closed` True gives PERIOD_CLOSED, a missing observation gives DIGEST_MISMATCH.
- Unknown `vat_rate_code` values are refused as AMOUNT_INCONSISTENT. VAT-on-top documents (vat_amount = amount x rate / 100) are unsupported and refused the same way. The production binding must set the includes-VAT constant TRUE.
- The SQL layer (db/phase2 reservation/claim raising BUDGET_EXCEEDED for an exhausted grant) is explicitly OUT of scope of this amendment. It needs a new migration (backlog item); the Python policy and the SQL ledger intentionally differ until then.
- Executor refusal mapping lives in `src/erp_mcp_private_writer/refusal_mapping.py`.
- Missing producers: `BudgetCheck.EXHAUSTED` and the period observation have no real producer yet.
