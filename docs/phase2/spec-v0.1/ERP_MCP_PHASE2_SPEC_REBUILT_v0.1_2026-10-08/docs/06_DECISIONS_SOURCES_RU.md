# Phase 2 — ADR proposals, решения, риски и источники

Версия0.1 · 08.10.2026 · DRAFT. Предложения не меняют нормативные ADR R1 автоматически.

## ADR-кандидаты

R2-ADR-01: observed отдельно от accepted; scanner не auto-approver.
R2-ADR-02: PostgreSQL bitemporal events/current projections; TimescaleDB лишь после benchmark.
R2-ADR-03: manual/qualified automated standard UI и qualified standard-engine отчёты могут быть eligible native evidence; synthetic/custom-query не повышаются автоматически.
R2-ADR-04: report capture отдельная control-plane capability; prod default OFF.
R2-ADR-05: actual evidence/attestation FK, независимые роли и operation-specific validation policy.
R2-ADR-06: reusable connector event/provenance contract; donor pin/license/dependency audit.
R2-ADR-07: Drive polling first, access PoC, own immutable captured bytes; no assumed complete revisions.
R2-ADR-08: backend-wide budgets/lease fencing/outbox.
R2-ADR-09: account-based AP отдельно от settlement/open-item strategy.
R2-ADR-10: financial acceptance требует одинаковый scope/cutoff/source consistency, не лишь отчётную дату.

Утверждение: risk review -> impact -> independent tests -> operator governance decision -> implementation. Смена eligibility native evidence требует normative amendment при внедрении; не relabel старых engine artifacts.

## Ключевые риски и критерии

RK01 Critical: fabricated ten PASS -> actual artifact/digest/FK/independent approver, TC083/101.
RK02 Critical: отчёт пишет business data -> qualification/rights/recipe/no arbitrary execution, TC073–075.
RK03 Critical: tenant leakage из metadata/evidence -> scoped keys/RLS/epoch, TC011/014/120.
RK04 High: один own calculator у expected/actual -> standard report origin и независимость.
RK05 High: компенсирующие opening/turnover errors при equal final net -> six-column comparison, TC089.
RK06 High: metadata/capture перегружает1С -> shared backend budgets/load test.
RK07 High: не наблюдаем промежуточные изменения -> gaps/unknown effective time; no fabricated history.
RK08 High: Drive scopes шире папки/нет новыхfiles -> actual grant PoC.
RK09 High: token/revoke ломает background -> AUTH_REQUIRED, alerts/reconsent.
RK10 High: UI-dependent ОСВ через COM пустая -> explicit UNSUPPORTED, qualified UI fallback только по permit.
RK11 High: backdated changes между чтениями -> snapshot/cutoff INCONCLUSIVE.
RK12 High: SPEC PASS выдан за prod -> NOT_RUN honesty/release guard.
RK13 High: timezone/currency/rounding неизвестны -> scope verification before arithmetic.
RK14 Medium: storage growth -> dedup/partition/retention/approved archive.
RK15 High: restore воскресил revoked grant -> current policy/epoch checks.
RK16 High: recipe после обновления конфигурации неверен -> requalification.
RK17 Medium: новая revision стёрла historical PASS -> immutable history/latest applicability отдельно.
RK18 High: test runtime назван production -> authority field/target-specific gate.

## Открытые решения

Подтвердить реальный UI executor и 1С topology/config edition. Подтвердить timezone/currency базы. Выбрать consistency mechanism prod. Назначить независимого accounting approver. Утвердить native evidence policy и claims coverage отдельно от числа файлов. Проверить полный donor inventory. Выбрать Drive account/file/folder/shared-drive model. Утвердить retention/legal hold/data residency. Установить hardware/load budgets/stop criteria. Для prod выбрать долговечный HTTPS IdP отдельно от временного tunnel.

## Прочитанные локальные источники

L01 docs/PHASE_2_REQUIREMENTS_BACKLOG_DRAFT_2026-10-08.md — существующий R2 backlog, перечитан.
L02 AGENTS.md и docs/DOCUMENT_INDEX.md — перечитаны; указывают precedence SECURITY/GOVERNANCE/SCOPE_FREEZE и запрет произвольных write/query/secret действий.
L03 docs/NATIVE_REPORT_CAPTURE_RUNBOOK.md — перечитан. R1 UI-only eligible class; engine diagnostic; UI-dependent reports; report effects; disposable clone; ten existing cases; проблема отсутствующего settlement register.
L04 reports/LOAD_TEST_REPORT.md — перечитан: реальная PostgreSQL/synthetic callbacks, production capacity NOT APPROVED. Лимиты app.py/db.py/fanout.py/sidecar ранее прочитаны и не равны реальной capacity.
L05 PDCC services/gmail-connector/src/history-runtime.ts; services/slack-connector/src/index.ts; host/telegram-connector — ранее inspected donor paths, повторный pin/audit S0 обязателен.
L06 ERP_MCP testbed/ferma_onec/reconcile.py и docs/FERMA_1C_SYNTHETIC_TESTBED_IMPLEMENTATION.md — ранее inspected independent comparator/test oracle patterns.
L07 ERP docs/architecture/R12_TEST_DATA_PLATFORM_TDD.md и workers/reconciliation-jobs — design ideas; worker был placeholder.
L08 reports/CHATGPT_READER_BOOTSTRAP_REPAIR_2026-10-07.md и обсуждение — historical access/profile/evidence findings, не новая live attestation.
L09 Git status/log: рабочее дерево dirty, последняя прочитанная short SHA4a21a01; ранее1294b42. Не certifies moving deployed head.

## Первичные внешние источники, проверены08.10.2026

W01 Google Drive changes: https://developers.google.com/workspace/drive/api/guides/manage-changes
W02 Drive scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
W03 OAuth token expiration: https://developers.google.com/identity/protocols/oauth2
W04 Drive notifications: https://developers.google.com/workspace/drive/api/guides/push
W05 PostgreSQL RLS: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
W06 1C official REST: https://1c-dn.com/1c_enterprise/rest_interface/
W07 Drive changes.list: https://developers.google.com/workspace/drive/api/reference/rest/v3/changes/list
W07b Drive revisions: https://developers.google.com/workspace/drive/api/guides/manage-revisions
W08 Keyless workload identity option: https://docs.cloud.google.com/iam/docs/workload-identity-federation
W09 PostgreSQL16 ranges: https://www.postgresql.org/docs/16/rangetypes.html

Provider facts не превращаются в implementation guarantees. Drive change feed не даёт безусловную историю всех revisions; Viewer/readonly не гарантирует history API; connector не выдаёт writer и не вызывает keepForever mutation ради исторического скачивания. WIF не выдаёт Drive permissions автоматически. OData поддерживает и записи, поэтому read-only обеспечивается контрактом ERP_MCP и правами1С.

## Доказательства подготовки

Созданы только новые project docs и companion specification files. Native/UI/1С/Drive/prod execution, новые grants, migration, code deployment и load tests не запускались. SPEC self-tests проверяют структуру/fixtures/контрпримеры, не реализацию продукта. Product cases144 остаются NOT_RUN.
