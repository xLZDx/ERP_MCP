# Change Record 380 - COM CREATE_DRAFT executor hardened by two reviews and by real-clone probes

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; code by the implementation-engineer agent; reviews by the silent-failure-hunter and
  python-reviewer agents; probes by the coordinator on the disposable clone (all in transactions that were rolled back).
- Changes `src/erp_mcp_private_writer/com_draft_executor.py` and `tests/phase2/test_s14_com_draft_executor.py`; adds
  `docs/phase2/artifacts/CT14_EXECUTOR_CLONE_FACTS_2026-10-27.json`. Follows Change Record 379.

## Review findings fixed (static reviews of commit 4ee91f6: 0 BLOCKER, 2+ MAJOR, several MINOR)

- Reference lookup passed a text GUID and treated an empty reference as the only "not found" case. Real behavior (measured): text is
  rejected by 1C; a non-existent GUID gives a non-empty reference whose object is `None`. Now: the UUID is built through the
  connection, existence is proved by the object lookup being non-`None`, then empty and deletion-mark checks.
- Document reference read-back used `str()` of a COM value (garbage); now `connection.String(...)` parsed as a UUID. The total is
  accepted only as int, float or Decimal and returned as non-exponent text.
- The write method is fetched and called in the same guarded step; `BaseException` in the post-write section becomes the
  unknown-outcome refusal; refusals survive copy and pickle with `outcome_unknown` intact; COM locals are released and no traceback
  frame keeps COM objects alive (weakref tests); 1C property names must be pairwise distinct; `change_id` must be a canonical UUID;
  `None` values are refused; the fakes are now strict.

## New findings from the real clone (FACT, artifact above), fixed in the same change

- The document's own date must be set or the write fails; it is a required argument now (`document_date`, naive `datetime`).
- An enumeration assigned as text raises nothing and is stored EMPTY (a silent false success); enumeration values are now assigned as
  enumeration objects, and every reference, enumeration and both markers are read back from the stored document. A mismatch is
  `COM_WRITTEN_READBACK_MISMATCH` with `outcome_unknown=True` and no result is returned.
- The includes-VAT flag defaults to false (total = amount + VAT); `DraftDestinationSet.constants` carries the reviewed flag value.

## Tests and probe

- Agent-run: the complete new test file 165 passed; with the value-map, VAT table and `vat_amount` contract files 319 passed; ruff
  clean; source ASCII. No mutation runs.
- Clone probe of the real executor (administrator account of the clone, transaction rolled back, 0 leftover documents): result
  OK, document total 20, document reference is a canonical GUID.

## Not established

- The probe used the clone administrator, not the least-privilege role; behavior under that role is UNKNOWN. Member names assumed
  for row count, row access and the enumeration name read-back worked in the probe only for this path; other 1C versions are UNKNOWN.
- Numeric and string line values are not compared on read-back. The executor is not wired into any gateway; the production binding
  set stays empty and the writer UNQUALIFIED and disabled. NOT_RUN: independent re-review of this batch, GPT-PM review.
