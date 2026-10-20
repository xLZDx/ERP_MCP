# ERP_MCP Phase 2 — 48 User Stories and Acceptance Mapping

**Version 0.1 · October 8, 2026 · PROPOSED.** Release 1 remains unchanged.

**Format:** An actor needs a specific outcome. Definition of Ready requires a scoped contract, test fixtures and permissions. Definition of Done requires actual test-case evidence bound to an exact Git HEAD. Every story covers positive, negative and boundary/recovery cases.

Full Given/When/Then steps are provided in the companion `03_STORIES_RU.md`, `test_cases.yaml` and `acceptance/phase2.feature`. The table below is the complete local catalog using the same IDs and required outcomes.

## Story Catalog

| Story | Sprint / Priority | Actor and desired outcome | Requirements | Acceptance cases: positive / negative / boundary and recovery |
| --- | --- | --- | --- | --- |
| R2-US-001 | S0/P0 | Owner establishes the R1/R2 boundary and baseline | REQ01,28 | TC001 R1 unchanged; TC002 R1 defects cannot be hidden in the future backlog; TC003 moving HEAD is not reported as deployment evidence |
| R2-US-002 | S0/P0 | Architect verifies actual PDCC/ERP/Ferma reuse | REQ04 | TC004 pin file path/SHA/license; TC005 an empty placeholder is not ready; TC006 donor write APIs are not exposed |
| R2-US-003 | S1/P0 | Connector engineer uses a bounded read-only SDK | REQ03,26 | TC007 typed scope and provenance; TC008 arbitrary URL/SQL/command denied; TC009 unsupported change feed maps to SNAPSHOT_ONLY |
| R2-US-004 | S1/P0 | Administrator defines tenant/company membership | REQ02,27 | TC010 permitted company read; TC011 cross-tenant FK/API denied; TC012 company-only grant does not authorize global metadata |
| R2-US-005 | S1/P0 | Owner revokes access without stale disclosures | REQ02,27 | TC013 revoke blocks jobs/bumps epoch; TC014 revoke before disclosure denies result; TC015 reconnect never restores revoked grants |
| R2-US-006 | S1/P0 | Operator runs jobs through an approved secret provider | REQ03,15,27 | TC016 no secrets in logs/arguments; TC017 missing credential pair fails preflight without gateway shutdown; TC018 rotation uses the new version |
| R2-US-007 | S3/P0 | Integrator obtains an authorized 1C baseline | REQ05 | TC019 complete coverage/digests; TC020 direct SQL forbidden; TC021 changing source yields partial/consistency warning |
| R2-US-008 | S3/P0 | Data architect distinguishes XML formatting changes from schema drift | REQ06 | TC022 whitespace-only structural hash unchanged; TC023 type/scale change causes diff; TC024 namespaces do not collide |
| R2-US-009 | S3/P0 | Operator preserves accepted truth after scan failure | REQ05,07 | TC025 timeout does not create a new schema; TC026 partial scan cannot delete objects; TC027 recovery without false version or automatic trust |
| R2-US-010 | S2/P0 | Database engineer maintains an immutable temporal ledger | REQ09 | TC028 append/projection order; TC029 SQL roles deny UPDATE/DELETE; TC030 identical replay |
| R2-US-011 | S2/P0 | Auditor distinguishes knowledge time and effective time | REQ09 | TC031 correct two-time views; TC032 unknown effective time is not replaced by poll timestamp; TC033 late supersession preserves earlier knowledge |
| R2-US-012 | S3/P0 | Auditor sees gaps and completeness | REQ05,09 | TC034 SNAPSHOT_ONLY interval; TC035 A–B–A changes are not invented; TC036 lost cursor causes controlled resnapshot and gap |
| R2-US-013 | S4/P0 | Domain engineer creates taxonomy/LDM | REQ08 | TC037 scoped candidate edges; TC038 LLM cannot validate; TC039 versioned semantics preserve old links |
| R2-US-014 | S4/P1 | Accountant distinguishes supplier aliases | REQ08,20,27 | TC040 exact scoped reference match; TC041 same name across companies never merges; TC042 ambiguity requires human resolution |
| R2-US-015 | S4/P0 | Architect computes dependency impact closure | REQ10 | TC043 affected tool blocked; TC044 unknown graph denied conservatively; TC045 remove/recreate is not a rename |
| R2-US-016 | S4/P0 | Model approver updates accepted head with CAS | REQ07,10,21 | TC046 evidence plus expected-head commit; TC047 stale reviewer yields conflict (409); TC048 incompatible rollback denied |
| R2-US-017 | S2/P0 | SRE prevents simultaneous writers | REQ11 | TC049 exactly one lease/fence; TC050 stale worker cannot commit; TC051 crash reclaim without duplicates |
| R2-US-018 | S2/P0 | Connector engineer persists cursor/outbox | REQ11,12 | TC052 atomic page/cursor; TC053 crash replay without loss; TC054 same ID with different digest is conflict |
| R2-US-019 | S3/P0 | SRE enforces physical-backend budget | REQ11,23 | TC055 budget shared across source aliases; TC056 bounded overload; TC057 interactive/background fairness |
| R2-US-020 | S3/P1 | Operator pauses, reconnects or quarantines a source | REQ03,11,27 | TC058 pause prevents new jobs; TC059 poisoned source isolated; TC060 resume rechecks scope/cursor |
| R2-US-021 | S5/P0 | Accountant obtains a manual native UI baseline | REQ13,16,19 | TC061 original artifact/manifest is UNATTESTED; TC062 partial screenshot is incomplete; TC063 edited XLSX digest rejected |
| R2-US-022 | S5/P0 | Capture operator automates the standard UI | REQ13,15 | TC064 manual/UI evidence equivalence; TC065 wrong database denied; TC066 selector/modal drift fails without guessed clicks |
| R2-US-023 | S6/P1 | 1C engineer qualifies standard engine/batch reporting | REQ14,16 | TC067 qualified native-object provenance; TC068 empty COM output is not zero; TC069 untrusted EPF denied |
| R2-US-024 | S5/P0 | Data owner issues a bounded capture permit | REQ15,26 | TC070 exact scope/window/mode admission; TC071 production default OFF and expired permit denied; TC072 identical idempotency key with changed parameters returns conflict (409) |
| R2-US-025 | S5/P0 | Security reviewer proves side-effect boundary | REQ15 | TC073 no business writes and complete coverage; TC074 administrator/posting rights disqualify; TC075 reset/write probes denied in production |
| R2-US-026 | S5/P0 | Custodian stores private immutable originals | REQ16,17 | TC076 opaque artifact version and digest; TC077 nonexistent blob/hash is not evidence; TC078 historical artifact remains subject to current ACL |
| R2-US-027 | S5/P0 | Security engineer isolates parsers | REQ17 | TC079 values-only parsing; TC080 macros/entities/zip bombs denied; TC081 timeout/memory bounded with no partial-data PASS |
| R2-US-028 | S6/P0 | Independent accountant signs evidence | REQ16,21 | TC082 attestation binds exact revision and policy; TC083 self-signing/fabricated PASS denied; TC084 revocation ends current validity but preserves history |
| R2-US-029 | S6/P0 | Tester compares a candidate without a public bypass | REQ16,18,21 | TC085 scoped EVALUATION_ONLY; TC086 unauthorized evaluation runner denied; TC087 canonical replay after acceptance |
| R2-US-030 | S6/P0 | Accountant reconciles all six account 521.1 balances and rows | REQ18,19 | TC088 all required measures MATCH; TC089 wrong opening/turnover causes MISMATCH despite equal closing balance; TC090 compare contract debit/credit sides separately from netting |
| R2-US-031 | S6/P0 | Domain engineer supports accounting-based AP | REQ18,19,21 | TC091 qualified ledger strategy; TC092 missing settlement register never invented; TC093 a balance alone does not establish aging |
| R2-US-032 | S6/P0 | Company user sees posted MOLDRETAIL receipts | REQ18,20,21 | TC094 correct identity/company/Posted status; TC095 exclude unposted/deleted; TC096 complete pagination and alias proof |
| R2-US-033 | S6/P0 | Auditor compares one consistent data snapshot | REQ18,19 | TC097 immutable snapshot proven; TC098 concurrent correction is INCONCLUSIVE; TC099 backdated rerun supersedes without overwrite |
| R2-US-034 | S6/P0 | Product owner defines operation validation | REQ21,28 | TC100 claim/evidence coverage; TC101 ten duplicate cases denied; TC102 purchases validation does not enable AP or alter R1 |
| R2-US-035 | S7/P0 | Drive owner authorizes the actual narrow corpus | REQ12,27 | TC103 scoped access proven; TC104 folder/new-child permission proof; TC105 broad OAuth is not claimed to be folder isolation |
| R2-US-036 | S7/P0 | Connector engineer updates Drive catalog | REQ12,11 | TC106 start token before baseline + catchup; TC107 shared-drive namespaces; TC108 lost cursor causes gap/resnapshot |
| R2-US-037 | S7/P0 | Auditor tracks revisions, moves and revocation | REQ12,16,27 | TC109 new revision UNATTESTED while previous PASS remains historical; TC110 shortcut/move cannot escape scope; TC111 deletion does not invent a replacement |
| R2-US-038 | S7/P1 | SRE handles auth expiration and watch notifications | REQ12,24 | TC112 invalid grant becomes AUTH_REQUIRED; TC113 notifications are hints only; TC114 polling works without watch |
| R2-US-039 | S8/P1 | Accountant investigates discrepancies | REQ22 | TC115 row/fragment/owner/delta; TC116 original numbers immutable; TC117 new evidence creates a new run |
| R2-US-040 | S8/P1 | Auditor reads timeline and coverage UI | REQ07,09,22 | TC118 explicit knowledge/effective-time labels; TC119 historical is not live-green; TC120 diff and evidence remain scoped |
| R2-US-041 | S8/P0 | API engineer exposes jobs and results safely | REQ26,02 | TC121 safe reason/annotation; TC122 CSRF/idempotency enforcement (403/409); TC123 raw COM/DC cannot bypass denial |
| R2-US-042 | S10/P0 | Production owner approves qualified canary | REQ15,28 | TC124 exact-scope capture/comparison; TC125 dev PASS does not grant production approval; TC126 kill switch owns running jobs |
| R2-US-043 | S9/P0 | Performance tester measures capacity | REQ23 | TC127 sessions-vs-active grid; TC128 denied profiles excluded from throughput; TC129 background interference and budget |
| R2-US-044 | S9/P0 | SRE verifies faults, alerts and recovery | REQ24 | TC130 audit failure is fail-closed; TC131 replica/network 429 without duplicates; TC132 alarm fires and resolves |
| R2-US-045 | S9/P0 | Release engineer deploys R2 without damaging R1 | REQ25 | TC133 additive shadow regression; TC134 destructive rollback denied; TC135 switchover rollback never resurrects revoked grants |
| R2-US-046 | S9/P0 | Privacy/operations owner handles retention and restore | REQ17,24,27 | TC136 restored foreign keys/digests/heads; TC137 export masking/tenant/formula safety; TC138 legal hold and no unauthorized deletion |
| R2-US-047 | FOLLOW_ON/P2 | Owner enables additional PDCC providers | REQ04,03,27 | TC139 adapter contract qualification; TC140 personal corpus expansion denied; TC141 pinned upgrade triggers retesting |
| R2-US-048 | S10/P0 | Release owner accepts exact candidate | REQ01,28 | TC142 complete manifest, IDs and actual results; TC143 NOT_RUN cannot become release PASS; TC144 separate user/admin/production UAT |

All shorthand `REQxx` identifiers refer to `R2-REQ-xx`; all `TCxxx` identifiers refer to `R2-TC-xxx`. At the time of the original specification, all 144 product-acceptance scenarios were `NOT_RUN`. Specification self-tests did not change those statuses. Later test evidence must always be checked against its exact implementation HEAD.

## Dependencies (Story Numbers Without the Prefix)

```text
001: none
002:001
003:002
004:003
005:004
006:003
007:003,009,017
008:010
009:010
010:004
011:010
012:010
013:007,008
014:013
015:013
016:015,028
017:010
018:017
019:017
020:005,018
021:006,024,026
022:021,025
023:021,025
024:004,006
025:024
026:010,004
027:026
028:026,027
029:015,024,027
030:021,029
031:030
032:014,021,029
033:030
034:028,030,031,032
035:003,004,026
036:018,035
037:005,036
038:006,036
039:030,032,034
040:011,016,037
041:003,024,034
042:023,034,043,044,045
043:019,041
044:018,020,041
045:016,041
046:026,037,045
047:002,041
048:042,043,044,045,046
```

S4 story 016 implements promotion mechanics, CAS, and shadow tests. Acceptance based on **genuine native accounting evidence** is completed only after story 028/G3. Workstreams can execute concurrently, but dependent live acceptance cannot be declared complete before its prerequisites.

## General Acceptance Criteria

**Ready:** Defined actor, scope, source identity and authority, policy contract, fixture provenance, positive/negative expectations and rollback.

**Done:** Actually executed relevant tests with the exact build, environment, assertions and artifacts; verified ACL and permissions; traceability; no blanket inference from unit tests; required gate approval. A FOLLOW_ON story must not be marketed as part of the first release by implication.

**Release rule:** Implementation, successful tests, independent evidence, and approved production availability are separate claims.
