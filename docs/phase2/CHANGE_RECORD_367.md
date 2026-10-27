# Change Record 367 - VAT code to enumeration table (draft, unresolved entries marked)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session. Documentation only.
- Inputs: `src/business_ai_gateway/phase2/change/proposal.py` (the line field `vat_rate_code` is validated only as identity
  text of at most 32 characters) and `src/business_ai_gateway/phase2/simulation/synthetic_data.py` (`VAT_CODES`
  = `VAT0`, `VAT10`, `VAT20`, synthetic) and the enumeration values in
  `docs/phase2/artifacts/CT14_DRAFT_DESTINATION_TYPES_2026-10-27.json`.

## Findings (FACT)

- No closed vocabulary of VAT codes exists in the payload contract: any identity text up to 32 characters passes validation.
  The only codes in the repository are synthetic. A write port that passes the code to the enumeration by name would therefore
  accept arbitrary text.
- The enumeration `СтавкиНДС` of the clone has 20 values, including advance, import, "reverse taxation", and legacy variants.

## Draft table (INFERENCE; to be reviewed before it becomes a binding set)

| Payload code | Enumeration value | Status |
|---|---|---|
| `VAT0` | `НДС0` | unambiguous by name |
| `VAT20` | `НДС20` | unambiguous by name |
| `VAT10` | `НДС10` or `НДС_10` | UNRESOLVED: two near-duplicate values exist; no evidence which one this configuration uses for goods receipts |
| any other code | none | must be refused (`COM_VAT_CODE_NOT_MAPPED`), never passed through |

Advance, import and reverse-taxation values are deliberately absent: a purchase-receipt draft must not select them.

## Required change before qualification

- Add a closed vocabulary for `vat_rate_code` to the binding set (reject codes outside the table), and settle the `VAT10` entry
  against the configuration's own usage on the clone. This record changes no code.

## Verification state

- RUN: reading of the contract code and the saved enumeration list. NOT_RUN: any COM call, any test, GPT-PM review.
