# Change Record 371 - reviewer fixes for the value vocabulary and a write-time recomputation probe

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; executor: Claude Code session (code and probe); tests written and run by the
  functional-test-reviewer agent; review by the python-reviewer agent.
- Changes `src/erp_mcp_private_writer/com_manifest.py`, extends `tests/phase2/test_s14_com_value_map.py`.

## Reviewer findings (python-reviewer, static read of Change Record 369): 0 BLOCKER, 0 MAJOR, 2 MINOR

- MINOR 1, many-to-one maps accepted (two payload codes to one 1C value): fixed. Duplicate targets now raise
  `COM_VALUE_MAP_INVALID`.
- MINOR 2, guards without tests (`str` subclass values, tuple or str subclasses in the map, a `None` leaf): tests added. The
  agent reports that the payload contract already refuses a str subclass and a `None` comment before `translate`, so those cases
  reach the guard only through a patched seam; the natural-path tests assert refusal, not the specific code.

## Tests (agent-run)

- Both value-map and binding test files: 54 passed, 0 failed, 0 skipped. No mutation runs.

## Write-time probe on the disposable clone (FACT: tool output, exit code 0)

- A draft receipt (one goods row: quantity 2, price 10, amount 20, ten-percent VAT value) was written inside a transaction and
  then rolled back in a `finally` block. A follow-up query found 0 documents with the probe number, so nothing persisted.
- After the write: VAT amount 0.0, line amount 20.0, document total 20.0.
- So the write recomputes the document total from line amounts, but the line VAT amount stays zero. The payload carries no VAT
  amount, so a draft written exactly from the payload has a zero VAT amount in the line. Whether that is acceptable, or the
  binding set must also set the line VAT amount (computed from the reviewed rate), is a design decision for the next step.
- First attempt failed on a reserved word used as a query alias and a missing connection-global function; neither wrote anything.

## Not established

- UNKNOWN: posting behavior, the production base, and concurrent users. NOT_RUN: wider suite, GPT-PM review of this change.
