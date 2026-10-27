# Change Record 382 - COM draft executor: fixes from two independent reviews of CR-381

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; code by the implementation-engineer agent; reviews by the silent-failure-hunter and
  python-reviewer agents (0 BLOCKER); probes by the coordinator on the disposable clone (rolled-back transactions only).
- Changes `src/erp_mcp_private_writer/com_draft_executor.py`, `tests/phase2/test_s14_com_draft_executor.py` and
  `docs/phase2/artifacts/CT14_EXECUTOR_CLONE_FACTS_2026-10-27.json`. Follows Change Record 381.

## Review findings fixed

- Plain values are type-checked before any COM access (str, int, bool, finite float or Decimal); date-shaped values on unverified paths are
  refused; `ExecutorResult.unverified_paths` shows which paths were not read back.
- Every 1C date (header, line, the document's own) is built and checked with `XMLString` before the document is created, so a bad cast is a
  clean refusal instead of a persisted bad draft.
- Enumeration member names starting with an underscore are refused and each member is verified before create.
- After the document reference is known, later failures carry `document_ref`; posted and deletion-mark flags are read back as False; new optional
  `expected_total` is compared numerically; property names are unique case-insensitively and reserved 1C names are refused.
- Docstring corrections: traceback frames keep the connection (caller drops the traceback), defaults cannot be proven by read-back, interrupts
  after the write become the unknown-outcome refusal, a retry must search by the change-id marker first.

## New fact (FACT, probe on the clone)

- The stored time of day of the document's own date is always 07:00:00 for assigned 00:00:00, 01:00:00, 04:30:00, 05:00:00, 12:00:00 and 23:59:59,
  with the calendar day kept. A reviewer's concern about a fixed -5 h offset crossing midnight is therefore not supported; the day-only
  comparison stays. The reason for the normalization is UNKNOWN.

## Tests and probes

- Agent-run: new test file 411 passed; with the value-map, VAT table and `vat_amount` contract files 565 passed; ruff clean; source ASCII.
  No mutation runs.
- Clone probes of the real executor after the fixes, rolled back, 0 leftover documents: administrator OK; least-privilege `CT14_NARROW` OK.

## Not established

- `expected_total`, posted and deletion-mark read-back paths ran against the real clone only through the default probe (flags False); a failing
  branch against real 1C was not exercised. The executor is not wired into any gateway; production bindings stay empty; the writer stays
  UNQUALIFIED and disabled. NOT_RUN: GPT-PM review of the exact final head.
