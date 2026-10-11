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
| 4 | Read movements by registrar | SUPPORTED (COM, clone), accounting register only | Count of `Хозрасчетный` rows with that registrar: 0 before posting, 2 after posting. Other registers (accumulation, information, payments) were NOT counted. |
| 5 | Unpost and observe movement removal | SUPPORTED (COM, clone) | Unposting write mode set `Проведен` = false; the accounting rows for the registrar dropped from 2 to 0; the marker survived unposting. |
| 6 | Object data version moves on every write | SUPPORTED (COM, clone) | `ВерсияДанных` of the new object: draft `AAAABAAAAAA=`, after posting `AAAABQAAAAA=` (changed); the source document had `AAAAAgAAAFg=`. Compare-and-write on the version is therefore feasible as a read-side check; a version-conditioned write was NOT measured. |
| 7 | Exclusive data lock visible across sessions | SUPPORTED (COM, clone) | Session A took an exclusive lock on one document inside a transaction; session B asked for the same lock and was refused with a platform lock-conflict error. Caveat: both sessions ran from one process on a file base; behaviour for a client-server base is NOT measured. |
| 8 | List infobase sessions | SUPPORTED for listing | `ПолучитьСеансыИнформационнойБазы` returned the own COM session (number 1). With a single connection the list says nothing about foreign sessions. |
| 9 | Forced termination of a session | INCONCLUSIVE, NOT attempted | File-base single-writer sensitivity makes a forced kill unsafe to try without a dedicated isolated copy; CT14 therefore keeps forced termination DENIED for every channel and base type until it is measured. |
| 10 | Concurrent writes of different objects by separate sessions | INCONCLUSIVE, NOT measured | Needs two writers at the same moment; not run in this pass. |
| 11 | No payment side effects | INCONCLUSIVE | Only the accounting register was read; payment registers and bank/cash documents were not inspected. |
| 12 | Narrow-rights behaviour (a user that may write one document class only) | INCONCLUSIVE, NOT measured | Only the administrator test user was used; no restricted role exists on the clone yet. |
| 13 | OData channel (Ivan, no client license) writes | INCONCLUSIVE, NOT attempted | Ivan currently serves the modified clone read-only through the OData publication; a write through that channel was not tried, so the only proven write channel is COM on a licensed machine. |
| 14 | Atomic marker field | SUPPORTED for the standard comment field | The comment field is free text and can be overwritten by a user; a dedicated attribute or a registered side table would be stronger. This pass proves only that the marker travels in the same write. |

## 2. Consequences for the plan

1. The create, read, post, movements-read and unpost cycle is feasible through COM on a licensed machine; plan CT3/CT8/CT14 assumptions for create/post/unpost hold on the clone. This is a feasibility fact for a disposable file base, not a production permission.
2. The write channel must be the COM connector on a licensed host; the OData channel stays a read channel until item 13 is measured. This affects the S12 topology (private write service on the licensed machine).
3. The marker in the comment field is user-editable: the plan must either add a dedicated attribute through a controlled configuration change or treat the marker as a hint verified by the full movement-and-field reconciliation (R-a), never as proof.
4. Lock and version evidence (items 6-7) support the plan's per-target lock and compare-and-write design, with the stated file-base caveat. Forced termination, concurrency, payment side effects and narrow rights stay open and block those parts of the S12 freeze.
5. The spike left one extra DRAFT receipt (marker `CT14-3b8ed340807f`, unposted) on the clone. It is on the disposable copy only and was not deleted.

## 3. Still to measure before this matrix can close

Items 9-13, the non-accounting registers for item 4, a version-conditioned write for item 6, and the lock behaviour on a client-server base. Each needs its own permission scope if it changes anything beyond the clone.
