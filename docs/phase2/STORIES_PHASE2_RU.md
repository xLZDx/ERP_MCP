# ERP_MCP Phase 2 — 48 историй и acceptance mapping

Версия0.1 · 08.10.2026 · PROPOSED. R1 не изменяется.
Формат: actor хочет результат; Ready требует scoped contract/fixtures/permission; Done требует реальный testcase evidence на exact head. Каждый набор состоит из positive, negative, boundary/recovery cases. Подробные Given/When/Then находятся в переносимом companion `03_STORIES_RU.md`, `test_cases.yaml`, `acceptance/phase2.feature`; ниже полный локальный каталог с теми же IDs и результатами.

## Каталог

| Story | Sprint/Priority | Actor / результат | Требования | Acceptance tests: positive / negative / boundary-recovery |
|---|---|---|---|---|
| R2-US-001 | S0/P0 | Владелец фиксирует R1/R2 boundary и baseline | REQ01,28 | TC001 R1 неизменён; TC002 defect R1 нельзя скрыть backlog; TC003 moving head не выдан за deployed proof |
| R2-US-002 | S0/P0 | Архитектор проверяет actual PDCC/ERP/Ferma reuse | REQ04 | TC004 pin path/SHA/license; TC005 .gitkeep не ready; TC006 donor writes не exposed |
| R2-US-003 | S1/P0 | Connector engineer использует bounded read-only SDK | REQ03,26 | TC007 typed scope/provenance result; TC008 arbitrary URL/sql/command denied; TC009 unsupported changes=SNAPSHOT_ONLY |
| R2-US-004 | S1/P0 | Admin задаёт tenant/company membership | REQ02,27 | TC010 read своей компании; TC011 cross-tenant FK/API denied; TC012 company-only не получает global metadata |
| R2-US-005 | S1/P0 | Owner отзывает доступ без stale disclosure | REQ02,27 | TC013 revoke blocks jobs/epoch; TC014 revoke до выдачи denies result; TC015 reconnect не resurrect старые grants |
| R2-US-006 | S1/P0 | Operator запускает jobs с safe secret provider | REQ03,15,27 | TC016 no log/argv leakage; TC017 missing pair preflight denies без gateway stop; TC018 rotation использует новую version |
| R2-US-007 | S3/P0 | Integrator получает разрешённый 1C baseline | REQ05 | TC019 full coverage/digests; TC020 direct SQL forbidden; TC021 racing source yields partial/consistency warning |
| R2-US-008 | S3/P0 | Data architect отличает XML formatting от schema drift | REQ06 | TC022 whitespace structural hash equal; TC023 type/scale change diff; TC024 namespaces не colliding |
| R2-US-009 | S3/P0 | Operator сохраняет принятую истину при сбое scan | REQ05,07 | TC025 timeout≠new schema; TC026 partial не удаляет objects; TC027 recovery без fake version/auto trust |
| R2-US-010 | S2/P0 | DB engineer хранит immutable temporal ledger | REQ09 | TC028 append+projection sequence; TC029 UPDATE/DELETE denied SQL roles; TC030 replay identical |
| R2-US-011 | S2/P0 | Auditor различает known/effective time | REQ09 | TC031 корректные two-time views; TC032 unknown не polling timestamp; TC033 late supersession сохраняет прежнее знание |
| R2-US-012 | S3/P0 | Auditor видит gaps/completeness | REQ05,09 | TC034 SNAPSHOT_ONLY interval; TC035 A-B-A не выдумывается; TC036 cursor loss -> controlled resnapshot+gap |
| R2-US-013 | S4/P0 | Domain engineer строит taxonomy/LDM | REQ08 | TC037 scoped candidate edges; TC038 LLM cannot validate; TC039 versioned semantics/old links retained |
| R2-US-014 | S4/P1 | Accountant различает supplier aliases | REQ08,20,27 | TC040 exact scoped ref match; TC041 same-name cross-company no merge; TC042 ambiguity human resolution |
| R2-US-015 | S4/P0 | Architect вычисляет impact closure | REQ10 | TC043 affected tool blocked; TC044 unknown graph conservative deny; TC045 remove/recreate не rename |
| R2-US-016 | S4/P0 | Model approver принимает head с CAS | REQ07,10,21 | TC046 evidence+expected head commit; TC047 stale reviewer409; TC048 incompatible rollback denied |
| R2-US-017 | S2/P0 | SRE исключает двойного writer | REQ11 | TC049 один lease/fence; TC050 stale worker commit denied; TC051 crash reclaim no duplicates |
| R2-US-018 | S2/P0 | Connector engineer сохраняет cursor/outbox | REQ11,12 | TC052 atomic page+cursor; TC053 crash replay no loss; TC054 same ID/different digest conflict |
| R2-US-019 | S3/P0 | SRE ограничивает physical backend | REQ11,23 | TC055 shared budget across source aliases; TC056 bounded overload; TC057 interactive/background fairness |
| R2-US-020 | S3/P1 | Operator pause/reconnect/quarantine | REQ03,11,27 | TC058 no new jobs on pause; TC059 poison source изолирован; TC060 resume revalidates scope/cursor |
| R2-US-021 | S5/P0 | Accountant получает manual native UI baseline | REQ13,16,19 | TC061 original+manifest UNATTESTED; TC062 partial screenshot incomplete; TC063 edited XLSX digest rejected |
| R2-US-022 | S5/P0 | Capture operator автоматизирует штатный UI | REQ13,15 | TC064 manual/UI equivalence; TC065 wrong base denied; TC066 selector/modal drift fail, no guessed clicks |
| R2-US-023 | S6/P1 | 1C engineer квалифицирует standard engine/batch | REQ14,16 | TC067 qualified object provenance; TC068 empty COM не zero; TC069 untrusted EPF denied |
| R2-US-024 | S5/P0 | Data owner выдаёт bounded capture permit | REQ15,26 | TC070 scope/window/mode admission; TC071 prod defaultOFF/expired denied; TC072 same idem/different params409 |
| R2-US-025 | S5/P0 | Security reviewer доказывает side-effect boundary | REQ15 | TC073 no business writes/coverage; TC074 admin/posting requirement disqualifies; TC075 reset/write-probe prod denied |
| R2-US-026 | S5/P0 | Custodian хранит immutable private originals | REQ16,17 | TC076 opaque version+digest; TC077 nonexistent blob/hash not evidence; TC078 current ACL on historical artifact |
| R2-US-027 | S5/P0 | Security engineer изолирует parsers | REQ17 | TC079 values-only parse; TC080 macro/entity/zipbomb denied; TC081 bounded timeout/memory, no truncated PASS |
| R2-US-028 | S6/P0 | Independent accountant подписывает evidence | REQ16,21 | TC082 exact revision+policy attestation; TC083 self-sign/fake PASS denied; TC084 revoke current validity, preserve history |
| R2-US-029 | S6/P0 | Tester сравнивает candidate без public bypass | REQ16,18,21 | TC085 scoped EVALUATION_ONLY; TC086 unauthorized runner denied; TC087 canonical replay после acceptance |
| R2-US-030 | S6/P0 | Accountant сверяет 521.1 all-six и строки | REQ18,19 | TC088 all-required MATCH; TC089 equal closing с ошибками opening/turnover MISMATCH; TC090 contract sides/netting отдельно |
| R2-US-031 | S6/P0 | Domain engineer поддерживает account-based AP | REQ18,19,21 | TC091 ledger strategy qualified; TC092 absent register not fabricated; TC093 balance alone no aging. S6b (offline fixtures only, IMPLEMENTED_UNVERIFIED): `ap_account_strategy.py` (`qualify_strategy`, `make_balance_view`, `compute_aging`), `test_ap_account_strategy.py` (217); `ap.account_based` stays refused |
| R2-US-032 | S6/P0 | Company user получает posted MOLDRETAIL receipts | REQ18,20,21 | TC094 identity/company/Posted correct; TC095 unposted/deleted exclusions; TC096 complete pagination/alias proof. S6b (offline fixtures only, IMPLEMENTED_UNVERIFIED): `posted_receipts.py` (`PostedReceiptsRetriever`, `assess_receipts`), `test_posted_receipts.py` (117), `test_posted_receipts_pagination.py` (73), `test_posted_receipts_assessment.py` (71); real 1C source, real MOLDRETAIL data and native journal NOT_RUN |
| R2-US-033 | S6/P0 | Auditor сравнивает один data state | REQ18,19 | TC097 immutable snapshot proven; TC098 concurrent correction INCONCLUSIVE; TC099 backdated rerun supersedes не overwrite |
| R2-US-034 | S6/P0 | Product owner задаёт operation validation | REQ21,28 | TC100 claims/evidence coverage; TC101 ten duplicate cases rejected; TC102 purchases validated не открывает AP и не меняет R1 |
| R2-US-035 | S7/P0 | Drive owner разрешает actual narrow corpus | REQ12,27 | TC103 scoped access proven; TC104 folder/newchild PoC; TC105 broad OAuth не называется folder isolation. S7 (offline fixtures only, IMPLEMENTED_UNVERIFIED): `drive_port.py` (read-only Protocol `DrivePort`, 4 methods), `drive_fake.py` (`FakeDrivePort`), `drive_oauth.py` (`ConsentManager`, `FakeTokenStore`), `drive_scope.py` (`evaluate_scopes`, `resolve_membership`, `prove_scoped_read`, `observe_new_child_access`), `test_drive_port_fake.py` (108), `test_drive_oauth.py` (110), `test_drive_scope.py` (116); real Google OAuth client, tokens, consent and the G4 new-child PoC NOT_RUN |
| R2-US-036 | S7/P0 | Connector engineer обновляет Drive catalog | REQ12,11 | TC106 starttoken-before-baseline catchup; TC107 shared-drive namespaces; TC108 lost cursor gap/resnapshot. S7 (offline fixtures only, IMPLEMENTED_UNVERIFIED): `drive_baseline.py` (`DriveBaseline.run`, `check_baseline_order`), `drive_cursor.py` (`DriveCursorStore`, `CursorState`, `CursorReason`), `test_drive_baseline.py` (53), `test_drive_cursor.py` (56), counts as of drafting; real changes.list token behavior and PostgreSQL cursor persistence for S7 NOT_RUN |
| R2-US-037 | S7/P0 | Auditor отслеживает revisions/moves/revoke | REQ12,16,27 | TC109 newrevision UNATTESTED oldPASS historical; TC110 shortcut/move scope escape denied; TC111 removal no guessed replacement. S7 (offline fixtures only, IMPLEMENTED_UNVERIFIED): `drive_revisions.py` (`RevisionTracker`, `list_history`), `drive_membership.py` (`MembershipChecker`), `test_drive_revisions.py` (48), `test_drive_membership.py` (42); real revision history for Viewer/readonly, real shortcuts/moves NOT_RUN |
| R2-US-038 | S7/P1 | SRE обрабатывает auth expiry/watch | REQ12,24 | TC112 invalid_grant AUTH_REQUIRED; TC113 notifications только hint; TC114 polling корректен без watch. S7 (offline fixtures only, IMPLEMENTED_UNVERIFIED): `drive_auth_state.py` (`DriveAuthHealth`, `AuthGuardedDrivePort`, `HintIntake`, `run_poll`), `test_drive_auth_state.py` (41), `test_drive_hints.py` (16); real invalid_grant, real watch channels and alert delivery NOT_RUN |
| R2-US-039 | S8/P1 | Accountant разбирает discrepancies | REQ22 | TC115 row/fragment/owner/delta; TC116 original numbers immutable; TC117 new evidence -> new run |
| R2-US-040 | S8/P1 | Auditor читает timeline/coverage UI | REQ07,09,22 | TC118 known/effective labels; TC119 historical !=live green; TC120 diff/evidence scoped |
| R2-US-041 | S8/P0 | API engineer безопасно выдаёт jobs/results | REQ26,02 | TC121 safe reason+annotation; TC122 CSRF/idem403/409; TC123 отказ не обходится rawCOM/DC |
| R2-US-042 | S10/P0 | Prod owner разрешает qualified canary | REQ15,28 | TC124 exact scope capture/compare; TC125 devPASS не prod approval; TC126 kill-switch owned job |
| R2-US-043 | S9/P0 | Performance tester измеряет capacity | REQ23 | TC127 sessions vs active grid; TC128 profile refusals not throughput; TC129 background interference/budget |
| R2-US-044 | S9/P0 | SRE проверяет faults/alerts/recovery | REQ24 | TC130 audit down fail-closed; TC131 replica/network429 no duplicates; TC132 alert fired+recovered |
| R2-US-045 | S9/P0 | Release engineer вводит R2 без порчи R1 | REQ25 | TC133 additive shadow regressions; TC134 destructive rollback denied; TC135 switch rollback no revoked grant resurrection |
| R2-US-046 | S9/P0 | Privacy/ops owner управляет retention/restore | REQ17,24,27 | TC136 restored FKs/digests/heads; TC137 export masking/tenant/formula safety; TC138 hold/no unapproved deletion |
| R2-US-047 | FOLLOW_ON/P2 | Owner включает дополнительные PDCC providers | REQ04,03,27 | TC139 adapter contract qualification; TC140 personal corpus creep denied; TC141 pin upgrade retests |
| R2-US-048 | S10/P0 | Release owner принимает exact candidate | REQ01,28 | TC142 manifest/IDs/actual results; TC143 NOT_RUN cannot release PASS; TC144 separate user/admin/prod UAT |

Все shorthand REQxx соответствуют R2-REQ-xx, TCxxx — R2-TC-xxx. Все144 scenarios имеют статус NOT_RUN в product acceptance; SPEC self-tests не меняют это.

## Зависимости (story IDs без префикса)

001: нет
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

S4 implementation истории016 создаёт механизмы/CAS/shadow tests; реальное принятие по native evidence завершается после028/G3. Дорожки могут работать параллельно, но не считать зависимую live acceptance выполненной раньше prerequisites.

## Общие критерии

Ready: actor/scope/source identity/authority, policy contract, fixture origin, positive/negative expected и rollback.
Done: relevant actual tests с exact build/environment/assertions/artifacts; safe ACL/permissions; traceability; no blanket proof из unit tests; mandatory gate approval. История FOLLOW_ON не попадает в первый release обещанием.
