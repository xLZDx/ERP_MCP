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
| 12 | Narrow-rights behaviour (a user that may write one document class only) | UNSUPPORTED with the standard roles; INCONCLUSIVE for a custom role | See section 4: an account built from the standard accounting roles can add, edit, post and unpost a receipt by right, but ALSO holds the add right on payment documents (payment order, cash disbursement, bank debit) and is blocked at read by record-level access restrictions until an access group is configured. A least-privilege role needs a dedicated role in a configuration extension; not measured. The administrator is never an acceptable write-service identity. |
| 13 | OData channel (Ivan, no client license) writes | INCONCLUSIVE, NOT attempted | Ivan currently serves the modified clone read-only through the OData publication; a write through that channel was not tried, so the only proven write channel is COM on a licensed machine. |
| 14 | Atomic marker field | SUPPORTED for atomic persistence only; NOT sufficient as recovery identity | The marker travels in the same write. Section 4 measured that a user edit of the comment makes the marker lookup return 0 while the document still exists, and that the comment cannot be compared for equality in a query (unbounded length; a substring of it can). Marker persistence is therefore not a reliable provenance mechanism. |

## 2. Consequences for the plan

1. The create, read, post, movements-read and unpost cycle is feasible through COM on a licensed machine; plan CT3/CT8/CT14 assumptions for create/post/unpost hold on the clone. This is a feasibility fact for a disposable file base, not a production permission.
2. The write channel must be the COM connector on a licensed host; the OData channel stays a read channel until item 13 is measured. This affects the S12 topology (private write service on the licensed machine).
3. The marker in the comment field is user-editable: the plan must either add a dedicated attribute through a controlled configuration change or treat the marker as a hint verified by the full movement-and-field reconciliation (R-a), never as proof.
4. Lock and version evidence (items 6-7) support the plan's per-target lock and compare-and-write design, with the stated file-base caveat; the platform itself rejects a stale-version write. Forced termination and narrow rights stay open and block those parts of the S12 freeze; payment side effects and a first concurrency sample are measured for the purchase receipt only.
5. The spike left several unposted DRAFT receipt copies on the clone (the first marked `CT14-3b8ed340807f`, the later ones `CT14B-*`, `CT14C`, `W1`, `W2` and two comment-edit variants). They are on the disposable copy only and were not deleted or marked for deletion.

## 3. Still to measure before this matrix can close

Items 9, 10b, 13 and the custom-role part of 12 (a dedicated role in a configuration extension), a durable marker mechanism (an extension attribute or side register) for create and for update, foreign-session observation, and the lock behaviour on a client-server base. Each needs its own permission scope if it changes anything beyond the clone.

## 4. Part C measurements (2026-10-12, clone only)

Run on the same clone with the administrator test user plus one created infobase user `CT14_NARROW` (created on the clone; not deleted). No credential was printed.

- Marker loss: a draft was written with a marker in the comment; the lookup returned 1 hit; after a user-style edit of the comment the lookup returned 0 hits while the document remained readable by reference. A direct equality comparison on the comment is refused by the query engine (unbounded-length field); the lookup used a substring of the first 100 characters.
- Contract update on the catalogue, allowed attribute only (comment): the write succeeded; the data version changed; a stale-object write was rejected by the platform; the original text was restored and read back identical. No additional-property definitions exist in this base (count 0), so the appended-provenance-row idea for a contract has no usable mechanism here.
- Narrow account: assigned five standard roles (basic rights, add/change and read of accounting data, add/change and read of common accounting reference data) plus the external-connection role. Without the external-connection role the connection is refused ("External connection is not allowed for this 1C user"). By rights the account may read, add, edit, post and unpost a receipt, may edit a contract, may NOT delete either object (delete and interactive delete are false) but MAY mark a receipt for deletion interactively, and holds the add right on three payment document types. A real query as this user failed with a record-level data access restriction on reading receipts, so end-to-end narrow-account operation was not demonstrated.
- Consequences: (a) the standard roles are too broad for the write identity and too restricted by access groups to work as-is; a custom least-privilege role and its access configuration are required; (b) the marker must be a dedicated attribute or side register written by the writer in the same write, and recovery must never infer non-application from a missing marker alone; (c) a contract update has no measured provenance mechanism and stays outside the first S12 freeze.

## 5. Operation-by-channel qualification (scope decision for the S12 freeze)

| Operation | COM on a licensed host (clone) | OData (Ivan) |
| --- | --- | --- |
| Purchase receipt: create draft | feasible; blocked until least-privilege role and durable marker are qualified | OUT_OF_SCOPE v2.0 |
| Purchase receipt: post | feasible (effects measured for this type); same blockers | OUT_OF_SCOPE v2.0 |
| Purchase receipt: unpost | feasible; same blockers; dependency and period-closure safety not measured | OUT_OF_SCOPE v2.0 |
| Contract: update allowed attribute | write and stale rejection measured on the clone; NO provenance mechanism; least-privilege role unmeasured | OUT_OF_SCOPE v2.0 |
| Forced session termination | DENIED (not measured) | not applicable |

Topology decision recorded for review: the write channel is the COM connector on a licensed host with a private access path; OData stays a read channel and is not part of v2.0 writes. The contract update is kept out of the first S12 interface freeze until a durable provenance mechanism and a least-privilege role are measured under a separately authorized spike.
