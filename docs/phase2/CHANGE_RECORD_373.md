# Change Record 373 - how the line VAT amount could be produced (options and measurement)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session. Documentation and evidence only.
- A read-only COM query on the local disposable clone `818HA_p2diff`; only counts and a maximum difference are recorded.

## Measurement (FACT: tool output of this run, exit code 0)

For receipt lines with the flag "amount includes VAT" set, the formula `round(amount * rate / (100 + rate), 2)` (half up) was
compared with the stored line VAT amount, using rate 20 for `НДС18` and rate 8 for `НДС10` (Change Record 372):

| Value | Lines | Exact | Within 0.01 | Over 0.01 | Stored zero | Max difference |
|---|---|---|---|---|---|---|
| `НДС18` (20%) | 751 | 713 | 31 | 6 | 1 | 12.50 |
| `НДС10` (8%) | 4 | 3 | 1 | 0 | 0 | 0.01 |

So the formula reproduces 95% of the lines exactly and 99% within one cent; 6 lines differ by more (up to 12.50), so the stored
amounts there were edited by hand or computed under another rule. The formula is a good default, not the platform's rule.

## Options (DECISION, not made here)

- A. The writer computes the line VAT amount from the reviewed rate with the formula above. Risk: a financial number the
  approver never saw enters the draft, and 1% of real lines would differ from what an accountant entered.
- B. The writer leaves it at zero and the draft is marked as needing completion. Risk: a draft with wrong VAT that a person must
  fix; posting such a document would book no VAT.
- C. The payload carries the line VAT amount (a new field in the approved, digest-bound payload), so the reviewer approves the
  exact figure and the writer only copies it. Risk: a payload contract change that touches the proposal model, digest and tests.
- Recommendation: C. Every amount that reaches the books should be inside what the approver saw and the digest covers; A and B
  put a number outside it.

## Not established

- UNKNOWN: the platform form's own rounding rule, behavior with the flag unset, other bases. NOT_RUN: any test, GPT-PM review.
