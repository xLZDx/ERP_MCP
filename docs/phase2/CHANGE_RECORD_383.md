# Change Record 383 - COM draft executor: read-back comparison by destination type (GPT-PM M-01)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; code by the implementation-engineer agent; finding raised by the GPT-PM gate review of d91b819;
  probes by the coordinator on the disposable clone (rolled-back transactions only).
- Changes `src/erp_mcp_private_writer/com_draft_executor.py` and `tests/phase2/test_s14_com_draft_executor.py`. Follows Change Record 382.

## Finding fixed

- M-01 (MAJOR, valid): the read-back comparator allowed a stored number to equal an expected numeric-looking text, accepted a stored text for an
  expected number, and treated an expected empty text and a stored `None` as equal. Identity text such as a supplier document number `"00123"`
  stored as the number 123 therefore passed. Fixed by comparing by destination type.

## Change

- New `DraftDestinationSet.numbers` (unique header or line paths, disjoint from references, enumerations, dates and unverified paths). A number path
  takes canonical decimal text only; the stored value must be exactly int, float or Decimal (finite, not bool, not text, not `None`) and equal to the
  expected decimal value.
- Every other plain path is identity text: the payload value must be `str` and the stored value must be exactly a `str` equal to it (leading zeros kept,
  no stripping, no coercion). The empty-text-equals-`None` rule and the coercion branch are removed. Constants use the same two rules.
- Regression tests for `"00123"` versus stored 123 (mismatch with `document_ref`, unknown outcome), exact-text success, `""` versus `None`, and the number
  path matrix (int, float, `"123.450"` versus 123.45; text, bool, `None` stored are mismatches; non-decimal payload refused before COM).

## Tests and probes

- Agent-run: new test file 535 passed; with the value-map, VAT table and `vat_amount` contract files 689 passed; ruff clean; source ASCII. No mutation runs.
- Clone probes after the change (number paths declared for quantity, price, amount, VAT amount), rolled back, 0 leftover documents: administrator OK; `CT14_NARROW` OK.

## Not established

- Number precision beyond the measured shapes (a float with representation error fails safe as a mismatch). The executor is not wired into any gateway; production
  bindings stay empty; the writer stays UNQUALIFIED and disabled. NOT_RUN: GPT-PM review of the exact final head.
