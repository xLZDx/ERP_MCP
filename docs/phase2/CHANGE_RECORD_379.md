# Change Record 379 - COM CREATE_DRAFT executor (fake-COM tested, not yet run against 1C)

## Ownership and scope

- Date: 2026-10-27. Accountable owner: operator; code by the implementation-engineer agent; review by specialist agents.
- Adds `src/erp_mcp_private_writer/com_draft_executor.py` and `tests/phase2/test_s14_com_draft_executor.py`; updates the design
  `docs/phase2/S14_COM_DRAFT_EXECUTOR_DESIGN_2026-10-27.md` (section 3a: decision record for the reference format).
- Decision record: the reference-format question (unique identifier, catalog code, or gateway key) was auto-answered with the
  recommended option (unique identifier) because the operator was silent; it can be reverted. Source evidence: the read gateway
  exposes `Ref_Key` (`Edm.Guid`) canonicalized with `uuid.UUID` (`server.py`).

## Change

- `execute_create_draft(connection, values, destinations, *, change_id, manifest_sha256)`: validates destinations and markers
  before any COM access; resolves the five references as canonical lower-case GUIDs through the reviewed catalog managers (empty
  reference and deletion mark refused); creates the document, sets header properties, one line row and the two marker attributes,
  then calls the plain write once. Posting is never referenced. Failures before the write call are refusals with
  `outcome_unknown=False`; a failure of the write call or of the read-back is `COM_WRITE_OUTCOME_UNKNOWN` with
  `outcome_unknown=True`. Refusal messages are the code alone, with no exception context kept.
- `DraftDestinationSet` carries the reviewed 1C names; nothing is derived from payload data.

## Tests (agent-written and agent-run, fake COM objects only)

- New file: 52 passed. With the value-map, VAT table and `vat_amount` contract files: 206 passed. Ruff clean on both new files
  (one reasoned `noqa: BLE001`). No real 1C, COM or docker was touched. No mutation runs.

## Not established

- UNKNOWN until the clone probe: the exact 1C member names for by-identifier lookup, document reference read-back and the total
  property (assumptions listed by the agent); whether a lookup of a non-existent GUID returns an empty or a phantom reference
  (the executor treats empty as not found; a phantom would need an existence check); real COM behavior of the plain write.
- The returned total is not compared to the approved line sums inside the executor.
- NOT_RUN: independent review, GPT-PM review, any run against the clone. The writer remains UNQUALIFIED and disabled.
