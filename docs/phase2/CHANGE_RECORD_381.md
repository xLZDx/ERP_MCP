# Change Record 381 - COM draft executor: dates, VAT-line read-back, least-privilege role with Read on four catalogs

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; code by the implementation-engineer agent; role extension by an agent on the
  disposable clone only; probes by the coordinator on the clone (all in transactions that were rolled back).
- Changes `src/erp_mcp_private_writer/com_draft_executor.py`, `tests/phase2/test_s14_com_draft_executor.py`, the CT14 extension
  (`Configuration.xml`, four adopted catalog files, `Roles/CT14Писатель/Ext/Rights.xml`), `ct14_rights_allowlist.json`,
  `ct14_rights_state.json` and `docs/phase2/artifacts/CT14_EXECUTOR_CLONE_FACTS_2026-10-27.json`. Follows Change Record 380.

## Findings from the real clone (FACT, artifact above)

- A date attribute assigned an ISO text is stored as the empty date without an error; a Python datetime assigned over pywin32 is
  converted unpredictably; dates read back as Python values are time-zone shifted. The first real run of the hardened executor was
  refused by its own read-back (`COM_WRITTEN_READBACK_MISMATCH`), i.e. the read-back caught a real silent failure.
- A date built by the 1C type-description conversion from 14 digits is stored exactly. The configuration changes the time of day of the
  document's own date (set 12:00:00, stored 07:00:00) and keeps the calendar day; the cause is UNKNOWN.
- A document write with a reference to a non-existent element succeeds silently, so existence is proved by the executor itself.

## Changes

- `DraftDestinationSet.dates`: ISO date texts are validated before any COM access (round-trip, not the empty-date years), converted by
  the 1C conversion and compared on read-back as text; the document's own date compares the calendar day only. Python datetimes are
  never assigned (the strict fakes reject them).
- Also in the working tree from the previous batch: hardening of read-back for plain values and constants, and the document date.
- Role `CT14Писатель` got `Read` on Организации, Контрагенты, Валюты and Номенклатура (allowlist delta is exactly these four).
  Effective rights measured on the clone: 57 objects, 0 mismatches, 0 extra, 0 forbidden. A safety copy of the clone was made first.

## Tests and probes

- Agent-run: new test file 277 passed; with the value-map, VAT table and `vat_amount` contract files 431 passed; ruff clean; source ASCII.
  No mutation runs.
- Clone probes of the real executor, transaction rolled back, 0 leftover documents: administrator account result OK (total 20, document
  reference is a canonical GUID); least-privilege `CT14_NARROW` account result OK with the same values.

## Not established

- Why the configuration changes the time of day of the document's own date (UNKNOWN); the read-back ignores the time of day for that field only.
- Numeric and string line values are compared by the executor against measured shapes only on this clone and version.
- The executor is not wired into any gateway; the production binding set stays empty and the writer UNQUALIFIED and disabled.
  NOT_RUN: independent re-review of this batch, GPT-PM review.
