# ERP_MCP Phase 2 — План S0–S10 и gates G0–G7

Версия0.1 · 08.10.2026 · DRAFT. Это проектная последовательность, не календарное обещание или запуск реализации. Длительности оцениваются после inventory/spikes. Источник требований — TDD_PHASE2_RU.md; истории — STORIES_PHASE2_RU.md; тесты — TEST_PLAN_PHASE2_RU.md и расширенный каталог144 cases.

## 1. Два трека

R1: закрыть уже действующие безопасность/достоверность/native evidence/release gates. Не задерживать R1 universal connectors/Time DB. Дефект R1 не списывается как будущая функция R2.
R2: новый согласованный scope, staged feature flags и отдельные gates. Prod capture capability поставляется default OFF; dev PASS не разрешает production.

## 2. Спринты

| Sprint | Результат | Зависимости / exit |
|---|---|---|
| S0 | R1 baseline, источники/identity ownership, PDCC/ERP/Ferma inventory, ADR proposals, native report feasibility | G0 scope/architecture/security; нельзя утверждать неподтверждённый donor ready |
| S1 | Connector contract, отдельный source OAuth, secret refs, scope/epoch, job/idempotency envelope | Contract unit/integration tests, no arbitrary target/write |
| S2 | PostgreSQL event/history/projections, scoped FKs/RLS/roles, leases/fencing/outbox/cursors | G1 real DB negative role/transaction/replay tests |
| S3 | 1C baseline, canonical hashes, partial/outage/coverage, adaptive scheduler/backend budget | G2a: whitespace invariant, failure≠drift, no source alias budget bypass |
| S4 | Taxonomy/LDM candidates, dependency graph, observed/accepted logic, CAS, timeline API | G2: impact-known/unknown; promotion mechanics тестируются на synthetic evidence, реальное принятие ждёт G3 |
| S5 | Manual native UI export, qualified UI automation dev, capture permit, original store/parser sandbox | G3a: настоящий UI baseline, report identity/parameters/no business writes |
| S6 | Optional engine qualification; attestation; candidate runner; 521.1 six totals; account-based AP; purchases contract | G3: native+MCP independent proof/coverage; missing register не выдумывается |
| S7 | Drive least-privilege PoC, baseline+changes/revisions/moves/revoke, auth expiry | G4: actual new-file scope behavior; polling работает без webhook |
| S8 | Workbench/UI explanations, history/coverage, job/read APIs, safe rerun | G5 user/admin UAT и evidence revocation/current applicability |
| S9 | Capacity/chaos/audit/restore/retention, R1 compatibility, migrations rehearsal | G6-pre: actual workload metrics, fault alarms, repeatable recovery |
| S10 | Source-specific prod canary при отдельном разрешении; exact-head R2 release bundle | G6/G7: approved recipe/identity/window/budget, native correctness и formal acceptance |

FOLLOW_ON: rollout других PDCC providers, push webhooks, TimescaleDB и advanced anomaly proposals. Inventory/SDK обязательны, но заявлять все providers поддержанными нельзя. Не переносить test seeder Ferma в production.

## 3. Gates

G0 — product owner+architecture+security утверждают scope/ADR/threat model, R1 boundary и source inventory. Документационный запрос сам по себе не implementation approval.
G1 — database/security review: real PostgreSQL roles/RLS/FKs/lease/fence/cursor/outbox/replay, не только mocks.
G2 — metadata/domain review: full canonical corpus, observed/accepted, unknown impact conservative denial, no AI promotion.
G3 — independent accountant+verifier: authentic report bytes/provenance, qualified recipe/config, source consistency, six totals+rows, operation coverage и attestation. Десять JSON PASS недостаточны.
G4 — source owner+security: narrow Drive access proven, shared drive/membership/revoke/token/revision tests.
G5 — actual user/admin UAT, безопасные объяснения блоков, operations separation и auditable workbench.
G6 — prod owner+ops+security: default-OFF enablement, pinned source/company/recipe/hash/user, time window/expiry/budget, kill-switch, copied-environment qualification. Нет test probes в prod.
G7 — release owner: exact commit/config/recipe/parser/policy/evidence manifest, все mandatory tests actual PASS, no P0/P1 correctness/security blockers; skipped не PASS.

## 4. Параллельные дорожки

A contracts/auth; B Postgres/temporal; C 1C capture/reconciliation; D UI; E security/functional/performance. Один владелец shared schema/files. Изолированные worktrees не должны перезапускать чужой live testbed. Внешних AI-reviewers не запускать без отдельного разрешения; независимость review можно обеспечить локальными ролями и proof review.

Критический путь: G0 -> contracts/storage -> observed/accepted и native capture -> attestation/comparison -> UAT/ops -> prod qualification. Drive не нужен для первого ручного native521.1 proof и не должен блокировать его.

## 5. Definition of Ready / Done

Ready: scoped story, requirement/test IDs, source/identity/data authority, recipe/contract, dependencies, риски и rollback. Для prod — valid permit.
Done: code+tests на exact candidate, реальные assertions, relevant integration/security/performance, migration/restore rehearsal, docs/traceability, independent evidence/approval. Нельзя считать наличие .feature пройденным тестом.

При blocker, который решает только оператор, записать точный код/причину/minimal action, продолжать независимые задачи. Не подменять MFA/secret/permission проблему обходом auth. Не снимать профиль и не выдавать временный admin ради демонстрации.

## 6. Delivery slices

R2-A: 1C-only living registry + temporal/taxonomy + dev manual/UI capture + первая comparison. Drive не обязателен.
R2-B: evidence/attestation, operation policies, qualified engine где поддержан, Drive polling, workbench. Canonical tools только для конкретных validated scopes.
R2-C: operations/load/DR, optional prod capture canary, first external provider qualified rollout. Остальные adapters по отдельным test contracts.

## 7. Ограниченные spikes

SP-01 UI-dependent ОСВ/карточка: реальный способ формирования/экспорта, no admin fallback.
SP-02 accounting-based AP для818HA вместо отсутствующего settlement register.
SP-03 Drive file/folder/shared-drive grant и новые файлы; readonly history ограничения.
SP-04 source-effective time и полнота change history; честный snapshot-only/gap.
SP-05 side effects штатного report и production reader права.
SP-06 shared backend capacity across replicas/source aliases.
SP-07 native formats/parser/currency/timezone/cutoff.

Каждый spike заканчивается SUPPORTED/UNSUPPORTED/INCONCLUSIVE с evidence, а не обещанием поддержки всех конфигураций.

## 8. Приёмка пользовательских сценариев

Обычный пользователь: статус своей компании; posted purchases MOLDRETAIL; ОСВ521.1 all six+rows; historical timeline; чужая компания/raw command denied; revoke во время job предотвращает выдачу.
Администратор/бухгалтер: источник/scope/secret/budget; observed diff/impact; native baseline/recipe; независимая аттестация; Drive update/revoke; prod permit/toggle/canary; алерты и restore/rollback.

## 9. Что этим планом не выполнено

Нет изменений R1 runtime/migrations/security/CI; нет branch/commit/push/merge; нет новых source auth/grants, входа в приложение1С, prod capture, рестартов, нагрузки или удаления. Только проектные документы и companion SPEC tests.
