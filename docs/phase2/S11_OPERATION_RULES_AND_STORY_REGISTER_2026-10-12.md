# S11 operation rule table and v2 story register (2026-10-12)

Status: DRAFT for GPT-PM review. Scope: the first S12 freeze slice, purchase receipt create, post and unpost through COM on a file base (see `CT14_FEASIBILITY_SPIKE_2026-10-12.md`). No code, no push, no new check run.

## 1. Per-operation rule table (expected effects and permitted registers)

Measured basis: one posted purchase receipt copied on the disposable clone (`818HA_p2diff`): accounting register `Хозрасчетный` 2 rows and accumulation register `НДСПредъявленный` 1 row, no row in any other register that has a recorder (all accumulation, accounting and information registers with a recorder were queried by registrar), no payment, bank or cash register. One receipt shape was measured; every other shape is UNMEASURED and its expectations must be hand-computed from a real posting before it is admitted (CT6).

| Operation | Document fields after the write | Registrar movements after the write | Version evidence | Forbidden outcomes (fail closed) |
| --- | --- | --- | --- | --- |
| Create draft | the typed fields of the approved proposal; marker attributes set; `Проведен` = false; number assigned by 1C auto-numbering | EMPTY set in every register (expected-empty is asserted, not skipped) | version token read after the write differs from the approved target version (new object: absent before) | any movement row; a posted flag; a second document with the same canonical business key |
| Update draft (correction) | only the approved fields changed; marker unchanged | EMPTY set | token differs from the approved target version, equals the token read after the write | any movement row; a changed field outside the approved list |
| Post | unchanged fields; `Проведен` = true | multiset in the permitted registers only: for the measured shape accounting `Хозрасчетный` 2 rows and accumulation `НДСПредъявленный` 1 row, amounts and accounts equal to the independent oracle; every other register with a recorder EMPTY | token differs from the pre-post token | a row in any register outside the permitted set (especially payment, bank, cash, settlement registers); a missing permitted row; an amount or account differing from the oracle; a created payment document |
| Unpost | unchanged fields; `Проведен` = false; marker unchanged | EMPTY set in every register | token differs from the pre-unpost token | any remaining movement row; dependent documents changed |

Rules: the permitted register set is a per-shape allowlist maintained with the oracle fixtures; the verifier reads movements by registrar over every register that has a recorder (the movement collection of a loaded object is lazy and is not a valid read path); VERIFIED needs field, movement and version evidence together (S11-D); a six-column match or an audit acknowledgement is never evidence; an unexpected register row gives `FAILED_VERIFY` with the effect known, an alert and a halt of the base queue (CT8). Shapes beyond the measured one (several lines, VAT mixes, foreign currency, service-only or goods-only documents, fixed assets) stay outside the freeze until their own measured fixtures exist.

## 2. Contract update

Out of the first S12 freeze (D12): the allowed attributes (validity end, comment) and the write with stale-version rejection were measured on the clone, but no marker mechanism exists for the catalogue (no additional-property definitions) and the narrow role was measured for the receipt only. It enters a later freeze only after its own measured provenance mechanism and rights matrix.

## 3. v2 story register

The v1 catalogue of 48 stories (spec archive `ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08`) contains no story that changes data and is not edited. The v2 stories are new and carry the prefix `V2-` so they never collide with the v1 ids; the ids below replace the assumed ids of the test-design package (`S12-01` becomes `V2-S12-01`, and so on). This register is the authoritative id list for the sprint scopes; any later change goes through a reviewed update of this file.

| Sprint | Story ids | Subject (see the test-design package section C for DoD and tests) |
| --- | --- | --- |
| S12 | V2-S12-01 .. V2-S12-07 | change model and digest, state taxonomy, principal and approval records, policy and grants, kill switch and WRITE/POST evaluator, error-code registry and crash matrix, CT14 record as data |
| S13 | V2-S13-01 .. V2-S13-05 | PostgreSQL ledger, transactional claim, signed checkpoints, fingerprint and target registry, recovery sweep |
| S14 | V2-S14-01 .. V2-S14-07 | write port, apply protocol, call ownership and compare-and-write, unknown-outcome resolution, draft/post/unpost, least-privilege role, token separation |
| S15 | V2-S15-01 .. V2-S15-05 | verifier, independent oracle, A-to-B comparison, bidirectional ledger-to-1C check, negative-control set |
| S16 | V2-S16-01 .. V2-S16-05 | approval page, registries and secrets, MCP surface, private-network exposure, recorded tool-call replay |
| S17 | V2-S17-01 .. V2-S17-06 | untrusted-file boundary, extraction, entity resolution, hostile corpus, workbench, H3 measurement |
| S18 | V2-S18-01 .. V2-S18-06 | queue and parking, chaos, alerting, SLOs, security review, rights-matrix drift read |
| S19 | V2-S19-01 .. V2-S19-05 | exact-head manifest, closure validator run, matrix completeness, residual-risk record, canary recipe |

The sprint-scope freeze of each sprint repeats this list with the final subjects and acceptance scenarios.
