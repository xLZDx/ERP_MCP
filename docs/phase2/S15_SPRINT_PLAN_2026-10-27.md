# S15 verification and reconciliation - sprint plan (draft, rev 2) - 2026-10-27

Status: DRAFT planning artifact. It does not alter `governance/GATE_MANIFEST.json`, pass any gate, qualify or enable the writer, or authorize
any COM write or production activity. Nothing below is implemented unless a cited change record says so.

## 1. Authority and sources

- Sprint and story IDs: `S11_OPERATION_RULES_AND_STORY_REGISTER_2026-10-12.md` (S15 = V2-S15-01 .. V2-S15-05: verifier, independent oracle,
  A-to-B comparison, bidirectional ledger-to-1C check, negative-control set). The register line carries names only, so the pairing of names to
  numbers 01..05 is an ordered reading (INFERENCE) and is to be confirmed against the register before the sprint starts.
- Scope text: `S14-S19_SPRINT_PLANS_AND_ACCEPTANCE_MAP_2026-10-17.md` (S15 row) and `PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` section "S15"
  (lines 188-199) with the scenario table E1..E47.
- Entry facts: `S14_COM_DRAFT_EXECUTOR_DESIGN_2026-10-27.md`, `CHANGE_RECORD_379.md` .. `383.md`,
  `artifacts/CT14_EXECUTOR_CLONE_FACTS_2026-10-27.json` ("the facts file").
- Not re-read for this plan: the full S11 test package and the gate manifest. Scenario wording is from the plan's E-table only.

### 1.1 Governing-document conflict (must be decided)

- PLAN_V2 decision D2 defines the v2.0 catalogue as purchase document creation, a contract update by a field allow-list, and post/unpost, and the
  S15 exit criteria list E1, E2, E9, E10, E12, E25, E26, E37, E43.
- The 2026-10-17 map states that the v2.0 write catalogue is purchase receipt draft/create, post and unpost only, with contract update excluded.
- These two statements conflict on contract update (E2). This plan treats the v2.0 write catalogue of the 2026-10-17 map as governing, pending an
  explicit operator / GPT-PM decision. Resolving it requires an amendment of PLAN_V2 (or of the 2026-10-17 map). Decision owner: operator.
- Independently of that conflict, E1 (post step), E10, E26 and E37 need post/unpost evidence that does not exist (see A14); they are DEFERRED in
  section 7.

## 2. Entry state (FACT from the cited records)

- S14 delivered `src/erp_mcp_private_writer/com_draft_executor.py` with fake-COM tests (535 passed in CR-383; 689 with the value-map, VAT table and
  `vat_amount` contract files) and rolled-back probes on the disposable clone `818HA_p2diff` as administrator and as least-privilege `CT14_NARROW`.
- The executor does CREATE_DRAFT of a supplier receipt with one line only. Posting, unposting and update are out of scope (design section 5).
- It is not wired into any gateway; the production binding set is empty; the writer is UNQUALIFIED and disabled. CR-382/383 record the GPT-PM review
  of the exact final head as NOT_RUN; CR-383 records a GPT-PM gate review of d91b819 (finding M-01, fixed). A later GPT-PM review is not recorded.
- S13 formal acceptance state after 2026-10-17 is UNKNOWN.

## 3. Dependencies, order and fallback

- Upstream: S12 interface and S13 ledger (2026-10-17 map: "Requires S13 and S14"). Moved here from the acceptance criteria: the ledger<->1C check
  (E15-4) depends on the S13 ledger and its anchor.
- Fallback: if S12/S13 are not accepted when S15 code is complete, S15 is delivered against a fake ledger/interface and is recorded as such; the
  affected acceptance rows stay NOT_RUN against the real ledger. S15 is not closed as fully accepted in that case.
- Fixture-provisioning prerequisite (blocks the clone assertions of E15-1, E15-3, E15-4): the S14 probes were rolled-back transactions and left 0
  documents (CR-380..383), and an uncommitted rolled-back document is invisible to a separate connection. S15 therefore needs either seeded
  committed documents on the clone or a documented clone re-creation procedure from the reference copy (design section 4 item 3: no delete right
  exists, so the clone is re-created). Owner: not recorded (UNKNOWN). After each re-creation the A/B baseline of unrelated differences must be
  re-captured. Until this exists every clone-based assertion is NOT_RUN; synthetic-fixture assertions are unaffected.
- Epic order: E15-2 (oracle and typing table) -> E15-1 (verifier, uses the oracle) -> E15-5 (negative controls, need verifier and oracle) ->
  E15-3 (A<->B, needs baseline and fixtures) -> E15-4 (ledger<->1C, needs S13 or the fake). E15-3 and E15-4 may proceed in parallel once the
  prerequisites hold.

## 4. Goal and non-goals

Goal (plan, S15): expectation versus fact, base versus base, ledger versus 1C in both directions, an independent oracle, negative controls; the G8
label stays "machine verified, not accountant attested".

Non-goals: enabling the writer; executing post/unpost; production activity; Drive intake; approval UI (S16); gates G1-G7.

## 5. Open assumptions changed or created by the S14 real-1C facts

Source column: "facts" = the facts file (and the CR cited); "CR-xxx only" = stated in that change record without the facts file; "design" = the S14
design. All measured statements apply to clone `818HA_p2diff` only.

| # | Statement | Source | Effect on S15 |
|---|---|---|---|
| A1 | Enumeration assigned as text: no error, stored EMPTY (also for a nonsense string); assigned as an enumeration object: stored correctly. | facts (write_requirements); CR-380 | Verifier reads back enumerations and compares to the oracle; "no write error" is not evidence. |
| A2 | Date attribute assigned ISO text is stored as the empty date silently; Python datetime assigned over pywin32 is converted unpredictably (any shift); Python-read dates are tz-shifted; dates must be read as `XMLString` text. | facts (dates); CR-381 | Verifier/oracle read dates as text only; an empty date or any shift is a distortion to detect. |
| A3 | The document's own date time of day is stored as 07:00:00 for assigned 00:00:00, 01:00:00, 04:30:00, 05:00:00, 12:00:00 and 23:59:59; calendar day kept; reason UNKNOWN. | facts (dates); CR-381, CR-382 | Oracle compares the document's own date by calendar day only on this clone. Behavior on other bases: UNKNOWN. |
| A4 | A document write referencing a non-existent element succeeds silently. | facts (phantom_references_on_write) | Verifier proves each reference resolves to an existing element (lookup object not None, not deletion-marked) in the expected catalog. |
| A5 | Includes-VAT flag defaults false: total = line amount + line VAT (20 + 1.82 = 21.82); true: total = line amount; the platform does not compute line VAT. | facts (totals); CR-374/371/380 | Oracle total rule takes the flag and the approved `vat_amount` as inputs and never recomputes VAT. |
| A6 | Numbers assigned as text are accepted and stored as numbers (coerced). CR-383: number paths compare as exact int/float/Decimal against canonical decimal text; every other plain path is identity text compared as exact `str` ("00123" stored as 123 is a mismatch). | facts (numbers_assigned_as_text); CR-383 only (comparator rules) | Because numeric text is coerced by 1C, the identity-text control "00123" versus 123 applies only to a field the 1C type stores as a string. Number precision beyond measured shapes: UNKNOWN. |
| A7 | Role `CT14Писатель`: `role_read_added` = Организации, Контрагенты, Валюты, Номенклатура (four catalogs); effective rights 57 objects, 0 mismatches, 0 extra, 0 forbidden; narrow-user lookup: existing -> object not None and deletion mark false; random GUID -> object None. | facts (least_privilege_run); CR-381 | A reader under the writer role can resolve references in those four catalogs only. Rights for anything else (registers, movements) are UNKNOWN. |
| A8 | `GetRef` with a Python str raises; with a UUID object built through `NewObject` works; non-existent GUID gives a non-empty ref whose object is None; a GUID of another catalog in the wrong manager gives object None; a document ref reads back via `connection.String(value)`. | facts (reference_semantics) | Reference comparison uses canonical GUID text; lookup uses the expected catalog manager. Whether all payload producers emit canonical GUIDs is UNKNOWN (design 3a). |
| A9 | The executor's read-back lives inside the writer and reports `unverified_paths`; numeric/string line values were compared only against measured shapes on this clone. | CR-381, CR-382 only | Writer read-back is not the S15 verifier. Paths in `unverified_paths` are unverified unless the oracle covers them. |
| A10 | The clone extension `CT14Cust` has a change-id attribute (string 36) and a change-hash attribute (string 64) on the receipt; the executor writes change id and manifest hash and reads them back. | design section 2 item 6; CR-379/380 only | The ledger<->1C check by marker is feasible for receipts on the clone. Whether the stored hash equals the "content hash" meant by S15 is UNKNOWN; marker mechanism on A/B/target bases is UNKNOWN. |
| A11 | Write-call or read-back failure gives `COM_WRITE_OUTCOME_UNKNOWN` / `COM_WRITTEN_READBACK_MISMATCH` with `outcome_unknown=True`; `document_ref` is carried only after the reference is known; a retry must search by the change-id marker first. | CR-379, CR-380, CR-382 only | 1C->ledger reconciliation must find a document by change id after an unknown outcome. |
| A12 | `expected_total` numeric comparison and posted / deletion-mark read-back exist; the failing branches were not exercised against real 1C. | CR-382 only | Clone evidence for those branches is NOT_RUN unless produced in S15. |
| A13 | Probes were rolled back; a commit probe would need the clone to be re-created afterward. | CR-380..383; design section 4 | See fixture prerequisite in section 3. |
| A14 | No fact in the files read concerns registrar movements of posted documents, document version read-back, or post/unpost on the clone. | absence of evidence in the files read | Movement-level and post/unpost oracle rules have no measured source: UNKNOWN. |

## 6. Epics and stories

Story IDs are the register's; story text is derived from the plan's S15 deliverables. Each acceptance criterion below is a testable assertion;
open questions are kept separate and listed in section 9.

### Epic E15-1 Verifier (V2-S15-01)

Assertions:
1. For any operation shape other than receipt CREATE_DRAFT (one line), the verifier returns a non-VERIFIED outcome. (Test: feed a post, an unpost and
   a multi-line shape; expect non-VERIFIED for each.)
2. Given a stored document whose field differs from the oracle's expected value, the result is not VERIFIED, for each field class: number,
   identity text, date, enumeration, reference, marker.
3. A date is compared as `XMLString` text; the document's own date by calendar day only (A2, A3). A stored empty date, or any one-day shift, is red.
4. An empty enumeration, a reference that does not resolve to an existing element, and a deletion-marked reference are each red (A1, A4).
5. Posted and deletion-mark flags read as True on an expected draft are red (A12).
6. An incomplete or failed read yields INCONCLUSIVE (not VERIFIED, not MATCH).
7. The result records the oracle version (see E15-2).
Open questions (not criteria): the status name for unsupported shapes; how the balance baseline "captured at apply time under the writer lock" applies
to CREATE_DRAFT; how document version is read back (UNKNOWN, A14).

### Epic E15-2 Independent versioned oracle (V2-S15-02)

Assertions:
1. Each verification result carries the oracle version; changing the version changes the recorded value.
2. An import-graph check shows that verifier and oracle modules do not import preview or normalization modules (plan S15).
3. The oracle's total rule takes the includes-VAT flag and the approved `vat_amount` as inputs; with the flag false the expected total is amount plus
   VAT (20 + 1.82 = 21.82), with true it equals the amount (A5).
4. The typing table (number / identity text / date / enumeration / reference per field) comes from an independently reviewed table, not derived from the
   writer's binding destination sets (`DraftDestinationSet` paths). Divergence test: when a field's type in the oracle table differs from the writer's
   destination set, the verification is red, and a test constructs that divergence and expects red.
5. Paths the executor lists in `unverified_paths` are either covered by an oracle rule or reported as unverified in the result (A9).
Open question: oracle rules for post/unpost have no measured evidence (A14); see the deferral in section 7.

### Epic E15-3 A<->B comparison (V2-S15-03)

Assertions:
1. Comparison runs through the test-lane read-only MCP; its result is labelled as a machine-read agreement, never a native 1C PASS.
2. Expected differences are compared as multisets (document ref, N movement lines, balance delta); an extra or a missing item is red (E1).
3. An unrelated baseline difference neither masks an expected effect nor imitates one (E43).
4. Incomplete data yields INCONCLUSIVE; amounts and names are hidden unless `show_values=true` is passed.
Open questions: which lanes are A and B (UNKNOWN); how the baseline is re-captured after clone re-creation (section 3).

### Epic E15-4 Bidirectional ledger<->1C check, R-c (V2-S15-04)

Assertions:
1. Ledger->1C: a ledger change whose change id has no matching document is reported (A10, A11).
2. 1C->ledger: a document without a marker, and an edit that left the marker unchanged but changed the content hash, are each detected (E12, E43).
3. The check runs at each of three triggers: startup, after a restore, and periodically; a test per trigger asserts that a run occurs (the interval is
   an open question).
4. Skew after restore (ledger older or newer than 1C; a valid but old chain) leaves applies blocked until the check is clean (E25).
5. A document found after an `outcome_unknown=True` result is classified by marker lookup with no resend (A11).
6. The "applies blocked" gate is inert while the writer is disabled: with the writer disabled, a dirty reconciliation does not change the behavior of
   any existing path (test: dirty state with writer disabled -> no new refusal on non-write paths).
Open questions: periodic interval; hash definition (A10); S13 state (dependency in section 3).

### Epic E15-5 Negative-control set (V2-S15-05)

Assertions:
1. Each data distortion of the plan set is detected: wrong account, wrong counterparty, wrong period, missing movement line, swapped Dt/Kt, distorted
   amount, extra document, duplicated identical movement row.
2. Each distortion derived from the S14 facts is detected: empty enumeration, empty date, any date shift, non-resolving reference, total off by the VAT
   amount, a draft that is posted or deletion-marked.
3. For every control a written note names the observable value that would differ if the guard were off (operator rule against mutation runs, plan
   line 329; no mutation runs and no deliberately broken implementations).
4. No control produces VERIFIED.
Plain limitation: the movement-level controls (account, Dt/Kt, period, missing/duplicated movement line, extra document) are exercised against the
oracle and the multiset comparison on synthetic fixtures only. No real-1C movement read is exercised in S15 as planned; that evidence is NOT_RUN
(A14).

## 7. Deferred and blocked scenarios

E2 (contract update), E10 (rollback), E26 (rollback impossible), E37 (stale post/unpost), and the post step of E1 are DEFERRED / blocked pending
post/unpost evidence (A14) and, for E2, pending resolution of the conflict in section 1.1. Decision owner: operator. A PLAN_V2 amendment is required
before S15 can claim those scenarios or drop them. S15 DoD does not pass them; it records them as NOT_RUN with this reason.

## 8. Requirements-derived test coverage map

Wording from the plan's E-table unless stated. Status of every row at the time of this plan: NOT_WRITTEN / NOT_RUN. "Synthetic" = fixture and
oracle level, no real-1C read.

| Req | Scenario / item | Stories | Assertion | Data source |
|---|---|---|---|---|
| I11 | E9 target-base distortions | 05, 02, 01 | each distortion red; no false VERIFIED | synthetic; field-level S14 shapes also on clone once fixtures exist |
| I11 | E43 unmarked doc, duplicated movement row, edit without marker change, unrelated A/B baseline difference | 04, 03, 05 | detected and classified; baseline neither masks nor imitates | synthetic + test-lane MCP |
| I11 | E12 out-of-band edit before/after verification | 04 | drift recorded by marker and content hash both ways; applies blocked until clean | ledger fixtures; real marker only on clone |
| I5, I7, I11 | E25 skew after restore | 04 | applies blocked until R-c and anchor clean; repeat of E3 returns no receipt for a nonexistent document | PostgreSQL ledger fixtures (S13 harness) or fake (section 3) |
| I6, I11, I15 | E1 invoice -> draft -> verify -> A<->B | 01, 02, 03 | A<->B differences equal expected multiset; fields/company/organization equal oracle | draft step only; post step DEFERRED |
| I3, I7, I11 | E2 contract update | - | DEFERRED (section 1.1, 7) | none |
| I6, I11 | E10, E26, E37 | - | DEFERRED (section 7) | none |
| 2026-10-17 map, S15 row | non-convertibility | UNKNOWN (story not stated) | scenario named in the map's S15 row; its definition is not in the files read; source: S14-S19 map, S15 evidence list | UNKNOWN |
| 2026-10-17 map, S15 row | empty draft movements | 01 | movement set of a draft is empty | synthetic only; no real-1C movement read (A14) |
| plan S15 | import graph: verifier independent of preview/normalization | 02 | import-graph check passes | source tree |
| oracle versioning | oracle version recorded in each result | 02, 01 | recorded version equals the oracle version | synthetic |
| plan S15 / MCP lane rules | INCONCLUSIVE on incomplete read | 01, 03 | incomplete read -> INCONCLUSIVE, not VERIFIED/MATCH | synthetic fault injection on the read path |
| MCP lane rules | amounts and names hidden by default | 03 | no values in output unless `show_values=true` | test-lane MCP |
| plan S15 | R-c triggers: startup, after restore, periodic | 04 | a run occurs at each trigger | ledger fixtures |
| A11 | unknown-outcome recovery by marker lookup | 04 | document found by change id after `outcome_unknown=True`; no resend | clone (needs fixtures) or fake |
| A7, A8 | reference resolves under the writer role | 01 | existing element -> found; random GUID -> not found, under `CT14_NARROW` | clone, read-only (needs no committed fixture beyond existing catalog elements; UNKNOWN whether they exist) |
| A12 | posted / deletion-mark flags and `expected_total` mismatch branches | 01, 05 | mismatch red | synthetic; real-1C failing branch NOT_RUN |
| A1, A2, A4, A5, A12 distortions | empty enumeration, empty date, any shift, non-resolving reference, VAT-offset total, posted/deletion-marked draft | 01, 02, 05 | each red | synthetic; clone read-back where fixtures exist |
| A6 | number vs identity text | 02, 05 | number paths exact numeric; string-typed field "00123" vs stored 123 red; divergence test E15-2 item 4 | synthetic |

Routing per the project workflow: code first; then `functional-test-reviewer` and `e2e-runner` write and run the complete set per epic and once more
at the end; the coordinator runs no tests. Specialist reviews on the exact final diff: code-reviewer and architect (oracle independence, interfaces),
database-reviewer (reconciliation, persisted state), reliability-reviewer (blocking gate, recovery, triggers), silent-failure-hunter (false-VERIFIED
paths), security-reviewer if read credentials change. GPT approves the exact head before push/PR.

## 9. Definition of Done

1. Stories V2-S15-01..05 have code; per-epic functional tests written and fully run by the test-owning agents, with exact head, commands, results.
2. Every control in the negative set is detected; no false VERIFIED.
3. Import-graph evidence for oracle independence; divergence test for the typing table.
4. R-c in both directions with all three triggers, on the S13 harness or recorded as delivered against a fake (section 3).
5. E2, E10, E26, E37 and the E1 post step are explicitly DEFERRED / blocked pending post/unpost evidence; decision owner: operator; a PLAN_V2
   amendment is required (section 7). They are recorded NOT_RUN, not passed.
6. Evidence separates synthetic results, clone-measured results and NOT_RUN items (real-1C movement read, post/unpost, other 1C versions,
   production COM). Output labelled "machine verified, not accountant attested"; no production-readiness claim.
7. Specialist reviews on the exact final diff leave no BLOCKER/MAJOR; GPT-PM APPROVE on the exact head before push/PR.
8. One PR; each commit carries a change record and a lessons-log entry.
9. Writer stays UNQUALIFIED and disabled; production binding set stays empty unless a separate decision changes this.

## 10. Rollout, rollback and migration

- Rollout: local test lanes and the disposable clone only; read-only against 1C except fixture provisioning (section 3).
- Rollback: reverting the sprint commits restores the S14 state.
- Schema/state: any ledger schema change or persisted reconciliation state follows expand/contract: add compatible structures first (old code keeps
  working), switch readers, remove old structures in a later change; the rollback of a step must leave the previous version functional. The concrete
  schema impact is UNKNOWN until S13 is checked. The "applies blocked" gate stays inert while the writer is disabled (E15-4 assertion 6).

## 11. UNKNOWN items

1. S13 formal acceptance status; S12 interface details.
2. Status name for unsupported shapes.
3. Reason for the 07:00:00 normalization and whether it applies on A/B or target bases.
4. Registrar movements of posted documents on the clone; post/unpost oracle evidence.
5. Document version read-back (how, and whether available through the gateway).
6. Whether the gateway can return per-registrar movement lines.
7. Time-zone and period handling in comparisons (as_of / period offsets) for S15 reads.
8. Whether the stored change hash equals the R-c content hash; marker mechanism on A/B/target bases.
9. Verifier account rights beyond the four catalogs (registers, movements).
10. Whether lanes A and B are the clone and its reference copy.
11. Whether every payload producer emits canonical GUID references.
12. Number precision beyond measured shapes; other 1C versions.
13. Failing `expected_total`, posted and deletion-mark branches against real 1C.
14. Fixture-provisioning owner and procedure; fixtures for dependent documents, closed period, second organization, blocked-call harness (no owner
    in the S11 test design).
15. Definition and story of the "non-convertibility" scenario.
16. Periodic R-c interval; baseline capture for CREATE_DRAFT.
17. Whether a GPT-PM review of the exact final S14 head exists.
18. Owners of the licensed clone/channel and target operations.

## Operator decisions recorded 2026-10-27

These answers were given through the question tool; the recommended option was chosen each time (the question policy accepts the recommended option when the operator is silent for 5 minutes, so treat them as revisable by the operator).

- Deferred scenarios (E2, E10, E26, E37 and the E1 post step) stay DEFERRED outside the v2.0 scope; PLAN_V2 is not amended.
- Clone fixtures: a documented procedure re-creates the clone from the reference copy; the A/B baseline is re-captured after every re-creation. Fixture owner remains UNKNOWN until assigned.
- S13 is not formally accepted without evidence; S15 uses fake interfaces for S12/S13 and the affected checks stay NOT_RUN.
