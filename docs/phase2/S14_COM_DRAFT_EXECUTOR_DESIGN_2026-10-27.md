# S14 COM CREATE_DRAFT executor - design for the clone-only qualification (draft)

Date: 2026-10-27. Status: DRAFT for review. Scope: one operation, CREATE_DRAFT of a supplier receipt with one line, written to the
disposable clone. No posting, no update, no unpost, no production.

## 1. What exists and what is missing (FACT, from the repository at this head)

- Exists: payload contract with digest-bound `vat_amount` (CR-374); `PayloadPropertyBinding` with an optional closed `value_map`
  (CR-369/371); a reviewed closed VAT code table (CR-375); ephemeral COM value extraction and digest-only manifests
  (`com_manifest.py`); the STA lane that connects and checks user name and base fingerprint (`windows_com_lane.py`,
  `com_sta_lane.py`); a simulated write port (`simulated_write_port.py`).
- Missing: any code that performs the COM calls (create document object, set properties, write). There is no real COM write port
  and no production binding set (it is empty by design).

## 2. Proposed executor (new module, one responsibility)

`com_draft_executor`: `execute_create_draft(connection, values, destinations) -> ExecutorResult`, run on the STA worker.

1. Create a new document object of the reviewed document manager; refuse any manager other than the reviewed one.
2. For each `ComValueAssignment` set the property named by its reviewed destination; destinations come from the binding set, never
   from the payload. Header properties are set on the object; line properties on one added row of the goods section.
3. References (organization, counterparty, contract, currency, item) are resolved to 1C references before assignment (section 3).
4. Write with the plain write mode only. The call that stores a draft is the plain write; posting is never called.
5. Return only the new reference identity and a version/marker, never values. Any exception after the write call starts is
   `outcome_unknown`; any exception before it is a refusal with a stable code. Exceptions are classified by class, messages are not
   kept (the connection string and values must not leak).
6. Idempotency/marker: the clone extension `CT14Cust` already carries the change-id attribute (string 36) and the change-hash
   attribute (string 64) on the receipt. The executor writes the change id and the manifest hash there, so recovery can find a
   document by change id after an unknown outcome (the T16 recovery path already expects such a lookup).

## 3. Open design decisions (need an answer before code)

1. Reference format. The payload carries opaque identity text up to 128 characters for the five references. Nothing says whether
   that is a catalog code, a unique identifier or an external key. Options: (a) unique identifier string resolved through the
   catalog manager by identifier; (b) catalog code per catalog; (c) a gateway-issued key resolved through a read-only lookup.
   Recommendation: (a), because it is stable across renames and is what the read gateway returns; refuse anything that does not
   resolve to exactly one existing, not-deletion-marked element of the expected catalog.
2. Contract-to-counterparty consistency: refuse when the contract does not belong to the counterparty and organization.
3. Date and number: the receipt date is date-time; the payload date is a date. Proposal: date at start of day in the base time zone;
   incoming number refused above 30 characters, never truncated (CR-366).
4. Line VAT amount is copied from the approved payload (CR-374); the executor must not recompute. Totals: the write recomputes the
   document total (CR-371); the executor reads it back and refuses a draft whose total differs from the approved line sums.
5. Rights: the executor runs as the least-privilege user of the CT14 role (effective rights measured, CR-364: no delete, no
   interactive rights). Which concrete base user the lane uses for the clone is an operator-held credential; the executor never
   sees it.

## 4. Clone-only qualification plan

1. Unit tests with a fake COM object graph: property order, refusal before write, unknown outcome after the write call starts,
   no value or connection string in any exception, no posting call ever made (the fake fails the test if it is called).
2. Clone probe with the real lane and the least-privilege user inside a transaction that is rolled back: create the draft, read
   back totals and the marker, compare to the approved payload, roll back, verify nothing persisted (the method of CR-371/370).
3. A second probe that commits to the clone only; no deletion right exists, so the clone is re-created from the reference copy
   afterwards.
4. Review: python, security and silent-failure reviewers, then the GPT-PM gate on the exact head; the production binding set stays
   empty and the writer disabled until a separate decision.

## 5. Out of scope

Posting, unposting, updating a draft, any production base, enabling the writer in a gateway, changing the extension rights.
