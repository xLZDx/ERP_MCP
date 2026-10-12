# CT14 feasibility spike: measured 1C capabilities on the disposable clone (2026-10-12)

Status: first measured pass, PARTIAL. Authority: explicit operator GO of 2026-10-12 for a spike on the disposable clone only. Not covered by the GO and not touched: staging, production, any real company base.

Target: `D:\ERP_MCP_Testbed\1c\reference\working\818HA_p2diff` (local file base, platform 1C:Enterprise 8.3.27.2342, COM connector `V83.COMConnector`, administrator test user from the DPAPI secret store; credentials were never printed). Tool: a clone-only script that refuses any path not ending in `818HA_p2diff`; the same pattern as `testlane/tools/edit_purchase_on_clone.py`. Document type: purchase receipt (`Документ.ПоступлениеТоваровУслуг`). Nothing was deleted or marked for deletion. No test suite, CI or mutation run was started.

## 1. Capability matrix

Labels: SUPPORTED = measured success on this channel and base type; UNSUPPORTED = measured refusal; INCONCLUSIVE = not measured or the measurement does not prove the capability.

| # | Capability (CT14) | Result | Measured evidence |
| --- | --- | --- | --- |
| 1 | Create a draft with a marker in one write | SUPPORTED (COM, clone) | A copy of an existing posted receipt was written in plain write mode; `Проведен` = false; the marker string in the standard comment field was read back identical. The marker is stored in the same write as the document. |
| 2 | Read back by reference | SUPPORTED (COM, clone) | The same reference returned the marker and the posted flag. |
| 3 | Post | SUPPORTED (COM, clone) | Posting write mode set `Проведен` = true. |
| 4 | Read movements by registrar | SUPPORTED (COM, clone) | `Хозрасчетный` rows with that registrar: 0 before posting, 2 after. Part B counted all registers with a recorder: one more accumulation register (`НДСПредъявленный`, 1 row). The movement collection on the loaded object is lazy (empty until read), so registrar queries are the reliable path. |
| 5 | Unpost and observe movement removal | SUPPORTED (COM, clone) | Unposting write mode set `Проведен` = false; the accounting rows for the registrar dropped from 2 to 0; the marker survived unposting. |
| 6 | Object data version moves on every write | SUPPORTED (COM, clone) | `ВерсияДанных` of the new object: draft `AAAABAAAAAA=`, after posting `AAAABQAAAAA=` (changed); the source document had `AAAAAgAAAFg=`. Compare-and-write on the version is therefore feasible as a read-side check. Part B measured the write side: an object loaded before another write was refused at write time by the platform with a version-mismatch error (optimistic lock), so a stale write fails without any extra code. |
| 7 | Exclusive data lock visible across sessions | SUPPORTED (COM, clone) | Session A took an exclusive lock on one document inside a transaction; session B asked for the same lock and was refused with a platform lock-conflict error. Caveat: both sessions ran from one process on a file base; behaviour for a client-server base is NOT measured. |
| 8 | List infobase sessions | SUPPORTED for listing | `ПолучитьСеансыИнформационнойБазы` returned the own COM session (number 1). With a single connection the list says nothing about foreign sessions. |
| 9 | Forced termination of a session | INCONCLUSIVE, NOT attempted | File-base single-writer sensitivity makes a forced kill unsafe to try without a dedicated isolated copy; CT14 therefore keeps forced termination DENIED for every channel and base type until it is measured. |
| 10a | Simultaneous completion of writes to different objects | OBSERVED, weak (COM, clone, file base) | Two separate processes each created, posted and unposted their own draft at the same time; both finished OK (4.1 s and 5.5 s). Serialization was not shown; two writers is a small sample. This is NOT the capability CT3 needs. |
| 10b | Safe execution on another target while a first write call is unresolved (hung, disconnected client) | INCONCLUSIVE, NOT measured | Never exercised: no unresolved call, no disconnected client, no foreign-session observation. Until measured the base-wide hold of CT3 stays in force and the CT3 clause that lets an unrelated target continue is not usable. |
| 11 | No payment side effects | SUPPORTED for the purchase receipt on the clone | Across every accumulation, accounting and information register that has a recorder, a posted receipt produced exactly: accumulation `НДСПредъявленный` 1 row and accounting `Хозрасчетный` 2 rows; no payment, bank or cash register row. Other document types are not covered. |
| 12 | Narrow-rights behaviour (a user that may write one document class only) | UNSUPPORTED with the standard roles; SUPPORTED on the clone with a custom extension role (section 6) | See section 4: an account built from the standard accounting roles can add, edit, post and unpost a receipt by right, but ALSO holds the add right on payment documents (payment order, cash disbursement, bank debit) and is blocked at read by record-level access restrictions until an access group is configured. A least-privilege role needs a dedicated role in a configuration extension; not measured. The administrator is never an acceptable write-service identity. |
| 13 | OData channel (Ivan, no client license) writes | INCONCLUSIVE, NOT attempted | Ivan currently serves the modified clone read-only through the OData publication; a write through that channel was not tried, so the only proven write channel is COM on a licensed machine. |
| 14 | Atomic marker field | SUPPORTED as a durable, queryable extension attribute (section 6); NOT immutable against API writers, so it is a hint verified by hash, not proof; the comment-field marker is not sufficient as recovery identity | The marker travels in the same write. Section 4 measured that a user edit of the comment makes the marker lookup return 0 while the document still exists, and that the comment cannot be compared for equality in a query (unbounded length; a substring of it can). Marker persistence is therefore not a reliable provenance mechanism. |

## 2. Consequences for the plan

1. The create, read, post, movements-read and unpost cycle is feasible through COM on a licensed machine; plan CT3/CT8/CT14 assumptions for create/post/unpost hold on the clone. This is a feasibility fact for a disposable file base, not a production permission.
2. The write channel must be the COM connector on a licensed host; the OData channel stays a read channel until item 13 is measured. This affects the S12 topology (private write service on the licensed machine).
3. The marker in the comment field is user-editable: the plan must either add a dedicated attribute through a controlled configuration change or treat the marker as a hint verified by the full movement-and-field reconciliation (R-a), never as proof.
4. Lock and version evidence (items 6-7) support the plan's per-target lock and compare-and-write design, with the stated file-base caveat; the platform itself rejects a stale-version write. Forced termination and narrow rights stay open and block those parts of the S12 freeze; payment side effects and a first concurrency sample are measured for the purchase receipt only.
5. The spike left several unposted DRAFT receipt copies on the clone (the first marked `CT14-3b8ed340807f`, the later ones `CT14B-*`, `CT14C`, `W1`, `W2` and two comment-edit variants). They are on the disposable copy only and were not deleted or marked for deletion.

## 3. Still to measure before this matrix can close

Items 9, 10b and 13, a marker mechanism for a contract update, a marker integrity control against API writers, foreign-session observation, the cause of the earlier record-level read restriction, the same role on a client-server base, and re-measurement after a base configuration upgrade. Each needs its own permission scope if it changes anything beyond the clone.

## 4. Part C measurements (2026-10-12, clone only)

Run on the same clone with the administrator test user plus one created infobase user `CT14_NARROW` (created on the clone; not deleted). No credential was printed.

- Marker loss: a draft was written with a marker in the comment; the lookup returned 1 hit; after a user-style edit of the comment the lookup returned 0 hits while the document remained readable by reference. A direct equality comparison on the comment is refused by the query engine (unbounded-length field); the lookup used a substring of the first 100 characters.
- Contract update on the catalogue, allowed attribute only (comment): the write succeeded; the data version changed; a stale-object write was rejected by the platform; the original text was restored and read back identical. No additional-property definitions exist in this base (count 0), so the appended-provenance-row idea for a contract has no usable mechanism here.
- Narrow account: assigned five standard roles (basic rights, add/change and read of accounting data, add/change and read of common accounting reference data) plus the external-connection role. Without the external-connection role the connection is refused ("External connection is not allowed for this 1C user"). By rights the account may read, add, edit, post and unpost a receipt, may edit a contract, may NOT delete either object (delete and interactive delete are false) but MAY mark a receipt for deletion interactively, and holds the add right on three payment document types. A real query as this user failed with a record-level data access restriction on reading receipts, so end-to-end narrow-account operation was not demonstrated.
- Consequences: (a) the standard roles are too broad for the write identity and too restricted by access groups to work as-is; a custom least-privilege role and its access configuration are required; (b) the marker must be a dedicated attribute or side register written by the writer in the same write, and recovery must never infer non-application from a missing marker alone; (c) a contract update has no measured provenance mechanism and stays outside the first S12 freeze.

## 5. Operation-by-channel qualification (scope decision for the S12 freeze)

| Operation | COM on a licensed host (clone) | OData (Ivan) |
| --- | --- | --- |
| Purchase receipt: create draft | SUPPORTED on the clone (COM, file base) with the custom role and the extension marker attribute (section 6); marker is an untrusted label | OUT_OF_SCOPE v2.0 |
| Purchase receipt: post | SUPPORTED on the clone with the custom role (effects measured for this shape: accounting 2 rows, VAT accumulation 1 row) | OUT_OF_SCOPE v2.0 |
| Purchase receipt: unpost | SUPPORTED on the clone with the custom role; dependent documents and closed period not measured | OUT_OF_SCOPE v2.0 |
| Contract: update allowed attribute | write and stale rejection measured on the clone; NO provenance mechanism; the custom role was measured for the receipt only | OUT_OF_SCOPE v2.0 |
| Forced session termination | DENIED (not measured) | not applicable |

Topology decision recorded for review: the write channel is the COM connector on a licensed host with a private access path; OData stays a read channel and is not part of v2.0 writes. The contract update is kept out of the first S12 interface freeze until a durable provenance mechanism and a least-privilege role are measured under a separately authorized spike.

## 6. Configuration extension and least-privilege role (operator-authorized, clone only; 2026-10-12)

Authority: the operator's answer of 2026-10-12 (D5) permits a configuration extension only on the clone `818HA_p2diff`. A safety copy of the clone database was made first. Sources, scripts, the rights list and the full evidence are in `testlane/onec_extension/` (`STATUS.md`, `README.md`, `CT14Ext/`, `scripts/`); no credential is stored there.

What was built: extension `CT14Cust` (purpose Customization, no handlers, no modules) adopting `ПоступлениеТоваровУслуг` with two attributes `CT14ИдентификаторИзменения` (string 36, indexed) and `CT14ХешИзменения` (string 64), the role `CT14Писатель`, and 52 empty adopted base objects that the role needs (an extension role can grant rights only on objects the extension itself adopts). Applying it needed the extension's unsafe-action warning flags switched off through COM; the first extension (`CT14Ext`, purpose AddOn) was not visible to sessions and was deactivated, not deleted. Designer in batch mode can block on a modal error dialog.

Measured as the infobase user `CT14_NARROW` holding only `CT14Писатель` plus the external-connection role:

| Capability | Result | Evidence |
| --- | --- | --- |
| Marker written in the same write as a new draft; written through COM property access | SUPPORTED | read back equal; document not posted |
| Equality query by the attribute | SUPPORTED | count 1; the old comment text finds 0 after a comment edit |
| Marker survives a user edit of the comment | SUPPORTED | marker count stays 1 |
| Marker immutable for a non-writer user | UNSUPPORTED | a user with only standard roles rewrote the value through the API (restored by the administrator); attribute View/Edit rights govern the interface only and are ignored by API writes, so only a before-write handler (not built) or a consumer-side hash check can detect tampering |
| Create draft, post, read movements and lines, unpost | SUPPORTED | accounting 2 records and VAT accumulation 1 record; marker intact |
| Stale-version rejection | SUPPORTED | "Operation cannot be performed due to version mismatch or lack of database record" |
| Add payment documents denied | SUPPORTED | add right false for 7 payment document types; creating a payment order and a cash disbursement gave "Access violation" |
| Delete denied | SUPPORTED | delete and the interactive delete and mark rights are false; the object delete call gave "Access violation" |
| Administration and catalog change denied | SUPPORTED | all false |
| Record-level read restriction seen earlier | NOT REPRODUCED | neither the custom nor the standard roles hit it in this run; the cause is unknown |

Minimal rights of `CT14Писатель` (53 rights entries, one per adopted object: the receipt document plus 52 empty adoptions; found by about 40 one-right-at-a-time rounds; Read rights were added only after a real denial and not pruned): document `ПоступлениеТоваровУслуг` Read, Insert, Update, Posting, UndoPosting; sequence `ДокументыОрганизаций` Read and Update (post fails without Update); Read only on one more document, 3 catalogs, 2 constants, the accounting register, 19 accumulation registers and 21 information registers; Get on 4 session parameters. No delete, no interactive right, no administration, no write on any payment document.

Consequences for the plan: (1) the purchase-receipt create/post/unpost slice now has a measured least-privilege identity on the clone, so the CT14 item 12 blocker is resolved for this slice on a file base; (2) the marker is durable and queryable but not tamper-proof against an API writer, so CT2 must keep treating it as a hint verified by the content hash (R-c) and must never infer non-application from its absence (already the rule); a tamper-detecting before-write handler is a possible hardening that needs its own decision because the plan excludes handlers; (3) the extension and its 53 adopted objects (52 empty adoptions plus the document) can drift when the base configuration is upgraded, so the rights matrix must be re-read periodically (TM20); (4) the contract update still has no marker mechanism and stays outside the first freeze; (5) all of this is measured on the disposable clone only, nothing is authorized for staging or production.

Left on the clone: the deactivated first extension `CT14Ext`, several unposted draft receipts (one with a deliberately tampered marker that the administrator restored), the infobase user `CT14_NARROW` and its user-catalog item. Nothing was deleted.

Rights reconciliation (GPT-PM finding S11-R02, resolved 2026-10-12): three representations were compared. (1) Adopted objects: 53 (the receipt document that carries the two attributes plus 52 empty adoptions; the earlier figure of 52 counted only the empty ones). (2) The committed `Rights.xml` first had 55 entries: the 53 objects plus two attribute entries granting View and Edit true. Those two entries were stored but not effective, because child-object rights follow the parent when independent rights of child objects are off. They were removed, the extension version string was set to `1.0.0-ct14-spike`, the extension was reloaded and updated, and the live role dump now equals the committed file (53 entries). (3) Effective rights read from 1C for `CT14_NARROW` holding only `CT14Писатель` plus the external-connection role equal the committed file: delete and every interactive right are false, and View and Edit on both marker attributes are false for this role. The standard accounting roles inherit View and Edit true on the attributes from the document update right and any API writer can change the marker, so the marker remains an untrusted label. SHA-256 of the final `Rights.xml`: `e9296a472dc320c18fccf3a2831d2f549737cb124438bc2c32116ee8b1b8f785`. A static comparison `testlane/onec_extension/scripts/ct14_compare_rights.py` checks the committed rights against `scripts/ct14_rights_allowlist.json` (53 objects) without COM or credentials. The full chain (draft with marker, post, read movements, unpost) was re-run after the redeploy and returned ok.
