# S11 source-evidence inventory: what the existing R2 modules really contain (2026-10-12)

Status: first pass, DRAFT. Scope: the claims in `PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` (section 3, section 6) about existing R2 modules under `src/business_ai_gateway/phase2/`. Method: direct reading and text search of the files at the head of `main` after commit `aff0e63`. Labels: FACT = seen in the cited file; INFERENCE = a consequence of facts; NOT_VERIFIED = not yet checked in this pass. No test, CI or mutation run was started; nothing was executed except text search.

## 1. Claims checked

| Plan claim | Result | Evidence |
| --- | --- | --- |
| There is no kill switch anywhere in `src` | FACT (for the searched patterns) | Case-insensitive search of `src` for `kill.?switch`, `killswitch`, `emergency_stop`, `STOP_EFFECTS` returned 0 matches. A differently named mechanism is not excluded by this search. |
| `aliases` resolves only `SupplierEntity`, by exact reference | FACT for the type; exact-reference part NOT_VERIFIED | `aliases.py` defines `class SupplierEntity` and `add_entity` refuses any other type (`if type(entity) is not SupplierEntity`). |
| `capture_permit` is bound to a request, process-local, and has no write mode | FACT | `CaptureMode` has exactly `READ_SNAPSHOT` and `READ_INCREMENTAL` (both reads); permits live in instance dictionaries (`self._permits`, `self._uses`, `self._by_key`). CORRECTION: earlier chat wording and plan rev 1-2 said the permit knows only `READ_SNAPSHOT`; the real set has two read modes. The plan text says "no write mode", which stays true. |
| `side_effect_boundary` admits only READ | FACT | The module header says "Only READ operations are allowed"; `OperationClass` already has `WRITE`, `POST`, `DELETE`, `RESET`, `ADMIN`, `UNCLASSIFIED`, each non-READ class maps to a refusal code (`WRITE_OPERATION`, `POST_OPERATION`, ...), and the registry already names `create_document`/`update_document` as WRITE and `post_document` as POST. INFERENCE: S12 needs a new evaluator for governed WRITE/POST, not new class names. |
| `audit_gate` keeps request ids in process memory | FACT | The header says "Offline, unwired, in-memory, EVALUATION_ONLY"; state is held in instance dictionaries (`self._acks`, `self._phase_mode`); a known request id is suppressed (`DUPLICATE_SUPPRESSED`). |
| `jobs_api` is a decision model whose job kinds map to reads | FACT for the kinds; "fakes" NOT_VERIFIED | `JobKind` = RESCAN, REPORT, RECONCILIATION, CAPTURE, RERUN: none is a change. |
| `reconciliation` is a six-column per-account calculation | FACT for the types | `BalanceSix`, `LedgerScope`, `LedgerRow`, `LedgerStatement`, `Comparison`, `Difference`. Multiset comparison of movements (plan CT6) is not present in this module: NOT_VERIFIED, to be built or confirmed. |
| `workbench_review` is discrepancy cards, not approval cards | INFERENCE | The module compares native and gateway values (`_delta(native, gateway)`) over epochs, ledgers and snapshots; no approval or change concept was seen in the names. Full read NOT_VERIFIED. |

## 2. Consequences for the plan

1. A change proposal, an approval record, a write grant, a kill switch, a call-ownership record and a 1C write port do not exist and must be written (plan CT1-CT15). What can be reused are patterns: the operation-class registry and refusal codes, the audit phase/acknowledgement flow, the permit issuance and use accounting, the reconciliation row types.
2. `side_effect_boundary` is the natural place to attach the governed WRITE/POST evaluator; its READ-only guarantees must stay under regression.
3. In-memory stores (`audit_gate`, `capture_permit`) cannot carry the durable intent, grant and budget state the plan needs: the ledger (CT2, CT5, CT13) is new.

## 3. Not covered yet

`workbench_review` full read, the `jobs_api` fakes, exact-reference behaviour of `aliases`, `safe_parser` limits for the xlsx/csv intake, the `drive_*` modules, `restore_verify` and `release_rollback` as patterns for ops. The next pass must close these before any component is reused.
