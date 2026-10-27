# S15 verification and reconciliation - sprint plan (draft) - 2026-10-27

Status: DRAFT planning artifact. It does not alter `governance/GATE_MANIFEST.json`, pass any gate, qualify or enable the writer, or authorize
any COM write or production activity. Nothing below is implemented unless a cited change record says so.

## 1. Authority and sources

- Sprint and story IDs come from `S11_OPERATION_RULES_AND_STORY_REGISTER_2026-10-12.md` (S15 = V2-S15-01 .. V2-S15-05: verifier, independent
  oracle, A-to-B comparison, bidirectional ledger-to-1C check, negative-control set). The numeric suffix below follows the order of that list;
  the register line carries no per-story text, so the story-to-ID pairing is an ordered reading (INFERENCE).
- Scope text: `S14-S19_SPRINT_PLANS_AND_ACCEPTANCE_MAP_2026-10-17.md` (S15 row) and `PLAN_V2_CONTROLLED_CHANGE_2026-10-11.md` section "S15"
  (lines 188-199) and scenario table E1..E47.
- Entry facts: `S14_COM_DRAFT_EXECUTOR_DESIGN_2026-10-27.md`, `CHANGE_RECORD_379.md` .. `383.md`,
  `artifacts/CT14_EXECUTOR_CLONE_FACTS_2026-10-27.json` (called "the clone facts" below).
- Not re-read for this plan: the full S11 test package and gate manifest. Scenario wording is taken from the plan's E-table only.

## 2. Entry state (FACT from the cited records)

- S14 delivered `src/erp_mcp_private_writer/com_draft_executor.py` with fake-COM tests (535 passed in CR-383; 689 with the value-map, VAT table and
  `vat_amount` contract files) and rolled-back probes on the disposable clone `818HA_p2diff` as administrator and as least-privilege `CT14_NARROW`.
- Scope of the executor: CREATE_DRAFT of a supplier receipt with one line only. Posting, unposting and update are out of scope (design section 5).
- The executor is not wired into any gateway; the production binding set is empty; the writer is UNQUALIFIED and disabled. GPT-PM review of the exact
  final head is recorded as NOT_RUN in CR-382/383 (a GPT-PM gate review of d91b819 raised M-01, fixed in CR-383; the review of the final head is
  not recorded in the files read).
- The S14 plan row requires CT14-approved channel evidence and keeps production COM `NOT_RUN`; S15 depends on S13 and S14 (plan 2026-10-17).
  S13 formal acceptance state after 2026-10-17 is UNKNOWN (not in the files read).

## 3. Goal and non-goals

Goal (plan, S15): expectation versus fact, base versus base, ledger versus 1C in both directions, an independent oracle, negative controls; the G8
label stays "machine verified, not accountant attested".

Non-goals: enabling the writer; post/unpost execution (S15 only verifies operation shapes that have measured oracle/read-back evidence, per the
2026-10-17 plan); production activity; Drive intake; approval UI (S16); gates G1-G7.

## 4. Open assumptions changed or created by the S14 real-1C facts

Each row: prior assumption area, what the clone facts show, effect on S15. All "clone" statements are measured on `818HA_p2diff` only.

| # | Fact (source) | Effect on S15 design / tests |
|---|---|---|
| A1 | Enumeration assigned as text: no error, stored EMPTY, also for nonsense text; assigned as enumeration object: stored correctly (facts: write_requirements; CR-380) | The verifier must read back enumeration fields and compare to the oracle; "no error on write" is not evidence. Negative control: empty enumeration after a successful write must be red. |
| A2 | Date attribute assigned ISO text: stored as empty date silently; Python datetime assigned over pywin32 is shifted; Python-read dates are tz-shifted; dates must be read as `XMLString` text (facts: dates; CR-381) | Verifier/oracle must read dates as text, never as Python datetimes. Negative control: empty-date result and one-day shift must be detected. |
| A3 | The document's own date time-of-day is always 07:00:00 on the clone for assigned times 00:00:00..23:59:59; calendar day kept; reason UNKNOWN (facts: dates; CR-381, CR-382) | Oracle comparison of the document's own date must be day-only; time-of-day must not be an oracle field on this clone. Whether the same normalization holds on other bases (A/B, target) is UNKNOWN. |
| A4 | A write with a reference to a non-existent element succeeds silently (facts: phantom_references_on_write) | Verifier must prove every reference resolves to exactly one existing, not-deletion-marked element; a document pointing at a phantom must not be VERIFIED. |
| A5 | Includes-VAT flag defaults false: total = line amount + line VAT (20 + 1.82 = 21.82); true: total = line amount; the platform does not compute line VAT (facts: totals; CR-374/371/380) | Oracle totals rule must take the flag and the approved `vat_amount` as inputs; the oracle must not recompute VAT. |
| A6 | Read-back typing: numbers compared as exact int/float/Decimal against canonical decimal text; other plain paths are identity text compared as exact `str` (leading zeros kept, `""` is not `None`); "00123" stored as 123 is a mismatch (CR-383) | Oracle field typing (number vs identity text) must be declared per field and match the destination sets; identity-text negative control "00123" vs 123 is mandatory. Precision beyond measured shapes is UNKNOWN (a float with representation error fails safe). |
| A7 | Least-privilege role `CT14Писатель` has `Read` on Организации, Контрагенты, Валюты, Номенклатура (allowlist delta exactly these four); effective rights 57 objects, 0 mismatches/extra/forbidden; narrow user lookup: existing -> object not None; random GUID -> object None (facts: least_privilege_run; CR-381) | Any S15 reader that runs under the writer role may resolve references in those four catalogs only. Rights beyond these (e.g. movement/registers read) are UNKNOWN; the verifier's read path must be separate (see A9). |
| A8 | Reference semantics: `GetRef` with a Python str raises; with a UUID object built via `NewObject` works; non-existent GUID gives non-empty ref whose object is None; GUID of another catalog in the wrong manager gives object None; document ref value reads back via `connection.String(...)` (facts: reference_semantics) | Reference comparison uses canonical lower-case GUID text from `connection.String`; lookup uses the expected catalog manager. Whether every payload producer emits canonical GUIDs is UNKNOWN (design 3a). |
| A9 | The executor read-back is inside the writer (CR-380..383) and returns `unverified_paths`; numeric/string line values were compared only against measured shapes on this clone (CR-381) | Writer read-back is not the S15 verifier. S15 needs an independent oracle (plan, S15 deliverable) and must not import preview/normalization code (import-graph check). Paths listed in `unverified_paths` must be treated as unverified by S15 unless the oracle covers them. |
| A10 | Marker attributes: clone extension `CT14Cust` has a change-id attribute (string 36) and a change-hash attribute (string 64) on the receipt; executor writes change id and manifest hash; read back (design section 2 item 6; CR-379/380) | Ledger<->1C check by marker and content hash is feasible for receipts on the clone. Whether the content hash stored equals the S15 "content hash" definition is UNKNOWN. Marker mechanism for A/B target bases is UNKNOWN. |
| A11 | Unknown outcome: failure of the write call or read-back gives `COM_WRITE_OUTCOME_UNKNOWN` / `COM_WRITTEN_READBACK_MISMATCH` with `outcome_unknown=True`; retry must search by change-id marker first (CR-379, CR-382) | Reconciliation 1C->ledger must find a document by change id after an unknown outcome and classify it (exists / absent / mismatching). Document ref in the failure result is available only after the reference is known (CR-382). |
| A12 | Totals: the executor can compare `expected_total` numerically, and posted / deletion-mark flags are read back as False; the failing branches were not exercised against real 1C (CR-382) | The failing branches need S15 clone evidence or must be recorded NOT_RUN. |
| A13 | Probes and any clone write were rolled back; second commit-probe plan: no deletion right exists, clone is re-created from the reference copy (design 4) | Whether a committed document exists on the clone for S15 oracle/reconciliation tests is UNKNOWN; S15 needs a committed-document fixture or a documented re-creation procedure. |
| A14 | The registrar-movement side: S14 facts concern only a draft; "empty draft movements" is listed as an S15 evidence item (plan 2026-10-17). No fact in the files read about movements of posted documents on the clone. | Movement multiset comparison for posted documents has NO measured source: UNKNOWN. |

## 5. Epics and stories

Story IDs are the register's; story text is derived from the S15 deliverables in the plan (section "S15") and is an ordered reading.

### Epic E15-1 Verifier (V2-S15-01)

Story: as the control plane, after a write I read the target document through the approved read path and compare it with the expectation, so that
a write is VERIFIED only when the independent oracle agrees.

Acceptance criteria:
1. The verifier supports only operation shapes with measured oracle/read-back evidence; currently the measured shape is receipt CREATE_DRAFT with one
   line (S14). Any other shape yields no VERIFIED (refusal or NOT_SUPPORTED; exact status name UNKNOWN until S12 interface is checked).
2. Fields, document version and registrar movements are compared; for drafts the movement set is expected empty (plan 2026-10-17: "empty draft
   movements").
3. Dates are read as `XMLString` text; the document's own date compares by calendar day only (A2, A3).
4. Enumerations, references and both markers are read back from the stored document; empty enumeration, phantom or deletion-marked reference is red (A1, A4).
5. Number fields are compared as numbers; identity text as exact text (A6).
6. The balance baseline is captured at apply time under the writer lock (plan S15 deliverable); how this is realized for CREATE_DRAFT is UNKNOWN.
7. Unknown or incomplete read yields INCONCLUSIVE/blocked, never VERIFIED.

### Epic E15-2 Independent versioned oracle (V2-S15-02)

Story: as the reviewer, I need an oracle versioned and structurally independent of preview/normalization code, for every G8 operation.

Acceptance criteria:
1. Oracle is versioned; version is recorded with each verification result.
2. Import-graph check proves the verifier/oracle does not import preview or normalization modules (plan S15, S11 test package import-graph evidence).
3. Oracle rules include includes-VAT total rule and approved `vat_amount` as input (A5).
4. Field typing table (number / identity text / date / enumeration / reference) is explicit and reviewed (A6).
5. Oracle covers every path the executor lists as unverified, or those paths are reported as unverified (A9).
6. "Every G8 operation" covers only the v2.0 write catalogue (draft/create, post, unpost); oracle rules for post/unpost lack measured evidence (A14) and
   are recorded NOT_RUN/UNKNOWN until measured.

### Epic E15-3 A<->B comparison (V2-S15-03)

Story: as the reviewer, I compare two bases against a recorded baseline of unrelated differences, with an expected difference set as multisets.

Acceptance criteria:
1. Comparison is built on the test-lane MCP (read-only, two copies of one 1C base through their Release 1 gateways; MATCH means numeric agreement of
   two machine reads, never native 1C PASS - MCP server instructions).
2. Expected differences are a multiset (document ref, N movement lines, balance delta); an extra or missing item is red (E1).
3. Unrelated baseline differences neither mask nor imitate the effect (E43).
4. Amounts and names are hidden unless explicitly requested; incomplete data yields INCONCLUSIVE, not agreement.
5. Whether lane B is the clone `818HA_p2diff` and lane A its reference copy is UNKNOWN (not stated in the files read).

### Epic E15-4 Bidirectional ledger<->1C check, R-c (V2-S15-04)

Story: as the operator, I want a reconciliation by marker and content hash in both directions that blocks applies until clean.

Acceptance criteria:
1. Ledger->1C: every ledger-recorded change has a matching document by change id (A10, A11).
2. 1C->ledger: a document without a marker, an edit that left the marker unchanged (detected by content hash), and a missing movement are detected (E12, E43).
3. Runs at startup, after a restore and periodically (plan); the periodic interval is UNKNOWN.
4. Skew after restore (ledger older/newer than 1C, valid but old chain) blocks applies until R-c and anchor check are clean (E25).
5. Depends on S13 ledger; S13 acceptance state UNKNOWN (section 2).
6. Unknown-outcome recoveries (`outcome_unknown=True`) are resolved by marker lookup, with no blind retry (A11).

### Epic E15-5 Negative-control set (V2-S15-05)

Story: as the gate reviewer, I need an enumerated data-level control set where every distortion is detected and none gives a false VERIFIED.

Acceptance criteria:
1. Plan set: wrong account, wrong counterparty, wrong period, missing movement line, swapped Dt/Kt, distorted amount, extra document, duplicated
   identical movement row (plan S15); E9 adds wrong-account/counterparty/period variants as data distortions.
2. Added from S14 facts: empty enumeration, empty date, one-day date shift, phantom reference, stored number vs identity text ("00123" vs 123),
   total off by the VAT amount (includes-VAT flag mismatch), draft unexpectedly posted or deletion-marked (A1-A6, A12).
3. Controls are distortions of data/input, not of code; mutation runs and deliberately broken implementations are banned by operator decision
   2026-10-09 (plan line 329), so each assertion carries a written justification of the observable value that would differ if the guard were off.
4. Every control detected; no false VERIFIED.

## 6. Requirements-derived test coverage map

Scenario wording from the plan's E-table. "Boundary" is where the assertion must be observed. Status for all rows: NOT_WRITTEN / NOT_RUN at the time of this plan.

| Req (plan) | Scenario | Stories | Assertion (observable) | Source of expected data |
|---|---|---|---|---|
| I11 | E9 target-base distortions | 05, 02, 01 | each enumerated distortion red; no false VERIFIED | synthetic distortions on the test lane; clone only for S14-measured shapes |
| I11 | E43 unmarked doc, duplicated movement row, edit without marker change, unrelated baseline A/B difference | 04, 03, 05 | all detected and classified; baseline neither masks nor imitates | synthetic + test-lane MCP |
| I11 | E12 out-of-band edit before and after verification | 04 | drift recorded by marker and content hash in both directions; applies blocked until clean | ledger fixtures; real 1C marker only on clone |
| I5, I7, I11 | E25 skew after restore | 04 | applies blocked until R-c and anchor clean; repeat of E3 returns no receipt for a nonexistent document | PostgreSQL ledger fixtures (S13 harness) |
| I6, I11, I15 | E1 invoice to draft, verify, post, A<->B | 01, 02, 03 | A<->B differences equal expected multiset; fields/company/organization equal oracle | S14 draft path only; post step NOT_RUN/UNKNOWN (A14) |
| I3, I7, I11 | E2 contract update | - | contract update is excluded from the v2.0 write catalogue (plan 2026-10-17); scenario listed in S15 acceptance by the plan, treatment UNKNOWN | UNKNOWN |
| I6, I11 | E10 rollback (unpost, correct draft) | 01, 02 | effect neutralised by own movements; no "balance as before" claim | requires post/unpost evidence: NOT_RUN |
| I6, I11 | E26 rollback impossible | 01 | `ROLLBACK_REFUSED` with reason, distinct from FAILED_VERIFY; original not damaged | needs dependent-document / closed-period clone fixtures (no owner per S11 test design) |
| I6, I11 | E37 stale post/unpost | 01 | refused without modifying target | needs post/unpost evidence: NOT_RUN |
| import graph | verifier independent of preview/normalization | 02 | import-graph check passes | source tree |
| empty movements | draft has no registrar movements | 01 | movement set empty for draft | clone, measured-shape only; no fact in the files read (A14) |
| S14 facts | A1-A6 distortions (section 5, E15-5 item 2) | 01, 02, 05 | each red | clone read-back; unit fixtures |

Agent routing per project workflow: code first, then `functional-test-reviewer` and `e2e-runner` write and run the complete test set for each epic and
once more at the end; the coordinator runs no tests. Specialist reviews: code-reviewer/architect (oracle independence), database-reviewer
(reconciliation), silent-failure-hunter (false-VERIFIED paths), security-reviewer if read credentials change. Final GPT review on the exact head.

## 7. Definition of Done

1. All five stories (V2-S15-01..05) have code, and per-epic functional tests written and fully run by the test-owning agents with exact head,
   commands and results recorded.
2. Every control in the enumerated negative set is detected; no false VERIFIED (plan exit criteria).
3. Import-graph evidence for oracle independence.
4. R-c both directions with applies blocked on dirty reconciliation, on the S13 PostgreSQL harness.
5. Evidence states which results are synthetic, which are clone-measured, and which are NOT_RUN (post/unpost, production COM, other 1C versions).
   Output labelled "machine verified, not accountant attested"; no production-readiness claim.
6. Relevant specialist reviews on the exact final diff with no BLOCKER/MAJOR left; GPT-PM APPROVE on the exact head before push/PR.
7. One PR for the sprint; each commit carries a change record file and a lessons-log entry.
8. Writer remains UNQUALIFIED and disabled; production binding set remains empty unless a separate decision changes this.

## 8. Rollout and rollback

- Rollout: local test lanes and the disposable clone only; read-only against 1C. No production base, no enabling of the writer.
- Rollback: S15 adds verification code and reads only; reverting the sprint commits restores the S14 state. Any clone write required for fixtures is
  by rolled-back transaction, or the clone is re-created from the reference copy (design 4, item 3).

## 9. UNKNOWN items

1. S13 formal acceptance status and whether shared admission/recovery/provider requirements are met.
2. Exact status names for unsupported shapes and the S12 verifier interface.
3. Whether the story-to-ID pairing (01..05) matches the register's per-story text.
4. Reason for the 07:00:00 time-of-day normalization and whether it applies on A/B or target bases.
5. Behavior of registrar movements for posted documents on the clone (no measured fact); post/unpost oracle evidence.
6. Whether the stored change hash equals the content-hash definition used by R-c; marker mechanism on A/B/target bases.
7. Registers/movement read rights for the verifier's account (the role has Read on four catalogs only).
8. Whether lanes A and B correspond to the clone and its reference copy.
9. Whether every payload producer emits canonical GUID references.
10. Number precision beyond measured shapes; other 1C versions.
11. Failing branches (`expected_total`, posted, deletion-mark) against real 1C.
12. Whether a committed-document fixture exists on the clone; fixtures for dependent documents, closed period, second organization, blocked-call harness (no owner in S11 test design).
13. Treatment of E2 (contract update) given it is excluded from the write catalogue.
14. Periodic R-c interval; the baseline-capture mechanism for CREATE_DRAFT.
15. Whether GPT-PM reviewed the exact final S14 head.
16. Owners of the licensed clone/channel and target operations (not recorded).
