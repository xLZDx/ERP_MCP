# Phase 2 — Native 1C Report Capture & Reconciliation: Dev / Prod

Версия0.1 · 08.10.2026 · DRAFT. Требования R2-REQ-13…21. Не изменяет действующий R1 runbook и не разрешает сейчас доступ/выполнение в production.

## 1. Что считается источником проверки

Пользователь может открыть штатную 1С, сформировать стандартный отчёт, сохранить оригинал и сравнить с MCP. Автоматизация может сделать то же через квалифицированный UI recipe или вызвать тот же стандартный report object. Это не становится синтетикой лишь из-за участия программы.

| Способ | R2 eligibility |
|---|---|
| Standard UI report, человек | Native evidence candidate после проверки оригинала/параметров/полноты |
| Standard UI report, qualified automation | Тот же возможный уровень authority плюс recipe/runner/session provenance |
| Standard report object через qualified engine/COM/batch | Candidate после сравнения с UI на той же конфигурации и approved recipe |
| Собственный COM/OData query | Диагностика, не автоматически native standard report |
| Synthetic/Ferma generator | Test oracle synthetic lane, не real/prod native proof |
| XLSX из ответа MCP или того же собственного калькулятора | Не независимый oracle проверки MCP |

R1 сейчас допускает для валидации NATIVE_UI_REPORT; NATIVE_ENGINE_REPORT не засчитывается. Новая R2 policy требует governance amendment/recipe qualification и не меняет старые artifacts задним числом. Numeric MATCH, origin verification, accounting attestation и model acceptance — отдельные состояния.

## 2. Среды

Synthetic CI: только fixtures/mocks, no real/native claim.
DEV_REFERENCE: разрешённая disposable copy, отдельные credentials/output namespace и dev authority.
STAGING: утверждённая reference copy, pinned identity/config и consistency.
PROD: capability предусмотрена, default OFF. Только source/company/recipe-specific permission с window/expiry/budget и qualification на копии. Prod identity не admin по умолчанию.

В production запрещены write-probes, reset.ps1, произвольный EPF/BSL, отключение safe mode или admin fallback. В dev write-probes/Ferma seeding допустимы лишь в отдельном явно разрешённом test harness, не в capture recipe. MFA выполняет уполномоченный человек; отсутствие сессии даёт OPERATOR_ACTION_REQUIRED.

## 3. Report recipe

Recipe содержит: source/config/platform fingerprints; report object и variant hash; environment/mode; executor/selector/processing digest; schema разрешённых параметров; output format/private destination; required permission set; timeout/resources; allowed technical effects; qualification_ref и version.

Вход job: source_id/company_id, recipe_id/version/hash, authorization_id, scope_epoch, idempotency_key, typed parameters. Запрещены command/executable/sql/bsl/arbitrary_url/connection_string/password/token/epf_bytes/force_validate. Секреты только через серверный provider.

Parameters: account, start_local/end_local_exclusive, verified timezone, grouping, expanded_balance, currency_basis, posted/deletion filter, source snapshot/cutoff. Эквивалентность wire Period/native UI проверяется конкретным adapter; нельзя заменять любую границу на 23:59:59Z.

## 4. Ручной baseline ОСВ521.1

1. Открыть утверждённую базу/копию через штатный клиент. Проверить infobase identity, организацию и актуальность данных.
2. Выбрать стандартную ОСВ по счёту; альтернативный отчёт допустим только как согласованный equivalent recipe.
3. Организация 818 HA SRL; счёт521.1; 01.08.2026–31.08.2026 включительно по локальному времени базы. Canonical interval [01.08 00:00,01.09 00:00). Timezone подтверждается отдельно, не по местоположению пользователя.
4. Контрагент→договор, развернутое сальдо. Колонки: opening debit/credit; turnover debit/credit; closing debit/credit. Зафиксировать валюту/units и все фильтры.
5. Дождаться формирования; проверить отсутствие скрытого лимита строк. Сохранить оригинальный XLSX/MXL и, при необходимости, PDF/скрин шапки/настроек. Не править суммы в Excel. Скрин части таблицы не полное доказательство.
6. Ingest в private evidence store: original bytes/hash/manifest, status UNATTESTED. Drive location не доказывает native origin.
7. Сравнить MCP на том же snapshot/cutoff/параметрах, все шесть показателей и каждую строку. Scope/currency/completeness mismatch не получает PASS.
8. Отдельный бухгалтер принимает/отклоняет attestation; model approver связывает usable mappings с evidence coverage. Один совпавший кейс — не валидация всей системы.

Денежные значения переписки остаются USER_SUPPLIED_NOT_ATTESTED. Два набора opening/turnover могут давать одинаковый closing net; сравнение только последней суммы недопустимо. Частная записка с арифметикой прилагается к пользовательским файлам, но не включена в Git fixtures.

## 5. Автоматизация UI

Порядок: verify process/app identity → verify infobase/company → open standard report → set/read back parameters → generate/wait → verify header/columns/completeness → export original → hash/ingest → безопасно закрыть только owned report/session.

Unknown dialog/selector/wrongbase/config mismatch — отказ. Никакого угадывания кликов по похожей форме в prod. Наличие файловых операций DC_MCP не доказывает наличие UI executor. Implementation spike должен обнаружить и зарегистрировать реальный способ управления и его полномочия; при отсутствии использовать manual baseline.

Qualification: manual UI и automated UI report на одной стабильной copy/config, одинаковый object/variant/parameters/columns/totals/rows; no-business-write rights и effects proof. После изменения configuration/UI/recipe повторить affected qualification.

## 6. COM/engine/batch

Engine recipe запускает штатный report object, не собственный запрос, переписанный из его логики. Existing runbook указывает UI-dependent ОСВ/карточки: empty external connection output означает CAPTURE_UNSUPPORTED/INCOMPLETE. Возможен только явно разрешённый переход к UI recipe с новой provenance, а не маскировка query под native report.

/Execute — optional способ запуска заранее reviewed и pinned processing artifact. Требует source-specific authorization, fixed hash/signature, allowlisted path/parameters и side-effect assessment. Нет произвольного EPF из запроса модели, нет отключения защиты или elevated identity.

Wrapper управляет параметрами/экспортом, но не вычисляет expected totals тем же собственным кодом, который проверяется. Один source допустим; один и тот же собственный result/calculator по обе стороны — не независимость.

## 7. Preflight и полномочия

Permit: actor/source/company/environment/recipe/hash/modes/window/expiry/max_runs/budget/output_class/approver. Проверить до dispatch: текущий grant/epoch/revoke; matching config/recipe; owner runtime; secrets available без echo; source readiness; maintenance window; backend lease/budget; audit START.

Нельзя останавливать работающий gateway, если job/replacement невозможен. Report job не перезапускает gateway/IdP/1С. Cancel относится только к owned job; PID/start-time/foreign-process guards обязательны. Child process не наследует посторонние Gmail/API/SSH secrets. Нельзя читать секрет через обходной pytest probe.

## 8. Side effects и source consistency

Штатный отчёт выполняет код конфигурации: слово reader не гарантирует, что не пишутся настройки/логи. Business write rights на документы/проводки запрещены. Технические записи классифицируются, qualification фиксирует coverage. Не заявлять byte-identical production DB после запуска, поскольку сервисные данные могут меняться.

Dev предпочтительно проверяется на стабильной disposable copy. Prod требует доказанный snapshot/cutoff/version либо согласованное окно и before/after source markers. Одинаковая отчётная дата не доказывает отсутствие backdated posting между native и MCP read. При недоказанной consistency — INCONCLUSIVE SOURCE_CHANGED_OR_UNPROVEN.

No-business-write proof: rights/contract/qualified recipe + наблюдение relevant objects с explicit coverage. Production write-probe недопустим. При непроверенных effects automated prod denied; возможен manual export уполномоченным пользователем или согласованная copy.

## 9. Trust и результаты

Artifact trust: UNATTESTED / ORIGIN_VERIFIED / ATTESTED / REVOKED.
Comparison: MATCH / MISMATCH / INCONCLUSIVE / ERROR / NOT_RUN.
Applicability: CURRENT / SUPERSEDED / EXPIRED / SCOPE_MISMATCH / POLICY_STALE.
Authority: SYNTHETIC / DEV_REFERENCE / STAGING / PROD_QUALIFIED.

Hash только проверяет bytes; signature без надёжного key/actor management не доказывает правду. Actual artifact и attestation связываются по FK к immutable revision, exact scope/model/policy. Uploader/connector не может ставить VALIDATED. Новая revision снимает latest applicability, но historical PASS старых bytes не удаляется. Поддельное доказательство/отзыв подписи порождает отдельное revocation event.

## 10. Bootstrap candidate mapping

Public business tools остаются закрыты, пока mapping не validated. Для разрыва круговой зависимости отдельный закрытый validation runner может на разрешённой копии выполнить pinned candidate mapping через существующий read-only adapter. Результат EVALUATION_ONLY, не native oracle и не public bypass. Native export получен независимым standard report route. После comparison+approval -> accepted binding -> canonical MCP replay.

## 11. Двенадцать qualification cases

Это дополнительные R2 cases, не замена existing R1 NR-01…NR-10 и не доказательство, что любые10файлов достаточны.

R2-NR-01: ОСВ521.1 август, все шесть totals.
R2-NR-02: ОСВ по контрагентам, completeness и aggregates.
R2-NR-03: ОСВ контрагент/договор, expanded sides/no hidden netting.
R2-NR-04: карточка521.1, каждая проводка/документ/дата/корреспонденция.
R2-NR-05: июль и граница31.07–01.08, opening continuity.
R2-NR-06: native журнал posted MOLDRETAIL purchases.
R2-NR-07: unposted/deleted negative corpus на dev copy, не создание prod документов.
R2-NR-08: debit и credit по разным договорам одного поставщика.
R2-NR-09: несовпадающая currency/units -> scope refusal.
R2-NR-10: backdated correction в отдельном test corpus -> новый current run/history.
R2-NR-11: manual UI против qualified UI automation.
R2-NR-12: manual UI против qualified engine где поддержано; иначе UNSUPPORTED.

## 12. Финансовое сравнение

Net liability=credit-debit. Контроль closing_net=opening_net+credit_turnover-debit_turnover дополнительный. Развернутые Дт/Кт сравниваются напрямую с native, не заменяются общей формулой.

Match key: tenant/company/account/counterparty_ref/contract/currency_basis/report_grain. Implied name aliases требуют доказательства. Scope/precision/cutoff/completeness проверяются до сумм. Decimal, approved tolerance policy/rounding и signed deltas обязательны; float/подгонка к итоговой сумме запрещены.

Account-based balance не доказывает aging/due dates. В818HA отсутствие settlement register решается отдельной явно qualified ledger strategy, не ручным заполнением имён. Posted purchases требуют своего native journal contract.

## 13. Что входит в prod-поставку

API/queue/executor contracts и manual intake сохраняются в продукте. Automatic prod capture выключен до source-specific qualification/permit. Нет debug bypass, headless password grant или временного отключения semantic checks. Истёкшее право/recipe даёт безопасную причину отказа, history сохраняется по policy.
