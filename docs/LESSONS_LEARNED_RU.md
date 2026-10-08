# ERP_MCP Release 1 — lessons learned и практические ограничения

Дата актуализации: **2026-10-09**. Этот документ фиксирует инженерные уроки из текущих runbooks, тестовых отчётов и ревью репозитория. Он не заменяет [SECURITY.md](../SECURITY.md), [действующий release scope](SCOPE_FREEZE_BASELINE_2026-10-06.md) и [Definition of Done](DEFINITION_OF_DONE.md). «Тест пройден» всегда указывать с уровнем L1/L2/L3 и exact Git SHA.

## 1. Разделяйте демонстрацию и разрешённое production использование

**Урок.** В проекте есть работающие тестовые инструменты и некоторые реальные Windows/1C эксперименты, но они не равны утверждённому production релизу. В исторических отчётах встречаются green CI и локальные PASS при незакрытой бухгалтерской сверке или внешнем gate.

**Правило установки.** Для первого запуска используйте только Fake1C, отдельные порты и test IdP. Не отправляйте настоящие бухгалтерские данные в local no-OAuth ChatGPT gateway. Нужен отдельный production review и [release evidence](RELEASE_OPERATIONS.md).

## 2. Модель источника и компания — не одно и то же

**Урок.** Source-wide metadata/health и company-scoped business data имеют разные разрешения. Grant на компанию не делает универсальный `onec_read` безопасным для company-only доступа: до подтверждённого predicate этот инструмент может требовать более широкого источникового разрешения.

**Правило.** Никогда не расширять грант до `all sources` / source-wide только ради устранения 403. Использовать семантическую функцию с доказанной source/company scope либо возвращать access denied. Проверяйте отказ для другой компании до разрешённого happy-path.

## 3. Настоящие отчёты 1С нельзя заменить синтетическими числами

**Урок.** Fake1C, заполняемый JSON, digest и даже «10 PASS» без доказанного происхождения файлов не подтверждают суммы и проводки 1С. Ранняя валидация могла проверять только форму evidence, а не действительное происхождение. Поздние review выделили это как release-blocking trust boundary.

**Правило.** Независимый бухгалтерский oracle = оригинальный штатный отчёт 1С, квалифицированная процедура получения, source/company/config/time/period, полный объём данных (для ОСВ — все шесть агрегатов и строки, когда это требуется), неизменяемый artifact digest и независимое подтверждение. При отсутствии — `EVIDENCE_REQUIRED`, а не выдуманное подтверждение.

## 4. Не доверяйте именам регистров и универсальным SQL/OData предположениям

**Урок.** Конфигурации 1С существенно различаются: регистры, измерения, документы, знаки, валюта, time zone, счета и аналитики. Универсальные названия и presets не гарантируют правильного баланса (например, кредиторку 521.1 нельзя обещать без профиля конкретной базы).

**Правило.** Сначала live metadata/probe → capability profile → явное согласование mapping → native verification. Поддержка OData `Balance` или другого метода подтверждается для **конкретного** EntitySet; если нет, вернуть `CAPABILITY_UNSUPPORTED`. При неизвестном opening balance, неполноте или смешанных валютах — не возвращать уверенный ноль.

## 5. Ошибка транспорта не является metadata drift

**Урок.** Разбор capability observations выявил опасность записать транспортную ошибку или пустой `$metadata` как новое состояние схемы. Это могло бы необоснованно инвалидировать проверенные mappings.

**Правило.** `timeout` / `connection failed` → статус недоступности/необходимости проверки, но не новый правдивый fingerprint. Сохраняйте предыдущий known-good fingerprint; проверяйте recovery, повтор и negative PostgreSQL роль. См. [Master Plan](MASTER_PLAN.md) и [Phase 2 scope](PHASE_2_REQUIREMENTS_BACKLOG_DRAFT_2026-10-08.md).

## 6. Регистрация 1С: SSRF защищается на нескольких уровнях

**Урок.** Запрет произвольного URL от AI — только начало. Hostname allowlist сама по себе не исключает DNS rebinding или маршрут через proxy; redirect может увести запрос на другой origin.

**Правило.** Зарегистрированный `source_id` + issuer/audience/scope + exact hostname + CIDR/connect-time validation + TLS + network egress firewall + запрещённые redirects + private sidecar + ограничение verbs/read. Не выносить 1C OData или sidecar в открытый интернет. См. [Production](../deploy/PRODUCTION.md).

## 7. Приватные ключи, OAuth и Secure MCP Tunnel — три разные границы

**Урок.** Туннель даёт сетевой путь, **не** создаёт production-полномочия пользователя. Тестовая связка `development-local` + no-OAuth преднамеренно ограничена loopback Fake1C. Production IdP может быть недоступен браузеру, даже когда private tunnel работает.

**Правило.** Для реальной интеграции нужна проверяемая сквозная цепочка: публично доступный browser authorization flow IdP, MCP resource audience, scopes, user grants, отдельная Admin audience/scope, секреты вне Git. Не заменять ошибки auth тестовым bypass. См. [ChatGPT integration](CHATGPT_MCP_INTEGRATION.md).

## 8. Локальная Windows/COM-установка возможна, но не означает безопасный COM query

**Урок.** На disposable стенде удалось установить 1C 8.3, Community/Developer License, `V83.COMConnector` (per-user регистрация), RSV Data v1.3.0, проверить native metadata и reconnect. Но аудит RSV выявил shared token map, привилегированный `reveal`, записи токенов расширением и отсутствие неизменяемого company predicate для произвольного query.

**Правило.** Не открывать `execute_query`, `reveal`, arbitrary `query` или upstream bridge напрямую AI. Метаданные разрешать только через фиксированный allowlist и ERP_MCP ACL/audit. Любой бизнес-route только после zero-write + scope + native доказательств. См. [RSV runbook](runbooks/RSV_DATA_BRIDGE.md) и [local handoff](../reports/LOCAL_1C_SETUP_HANDOFF.md).

## 9. Административная роль, миграции и аудит — отдельная trust boundary

**Урок.** Административная мутация через runtime DB-логин, несовместимые линии миграций или способность application-role подправлять trusted capability rows разрушает модель доверия. В ревью выявлялись необходимость реальных permission-тестов и аккуратного объединения миграционных веток.

**Правило.** Отдельные `BAG_MIGRATION_DATABASE_URL`, `BAG_ADMIN_DATABASE_URL`, `BAG_DATABASE_URL`; миграции вперёд только с проверенной историей и возвратным планом; обычная runtime-роль не может менять trusted grants или audit. Проводить privilege-negative tests на настоящем disposable PostgreSQL, не только на mocks. Никогда не запускайте `reset` против рабочей БД.

## 10. Тесты и среда могут испортить друг другу результаты

**Урок.** Одновременные worktrees и E2E процессы конфликтуют по портам, БД и pid. Ранние отчёты также обнаруживали missing Docker daemon, неправильные ожидания test fixture, неинтерпретированные skip и зелёные тесты на другом SHA.

**Правило.** Каждый стенд получает собственный `E2E_PORT_OFFSET` и `E2E_PROJECT_SUFFIX`; `up.ps1` должен отвергать чужой listener. Тесты проводить на exact head, записывать skipped/xfail и реально исполнять negative cases. Не используйте `down -Purge` на чужом стенде. См. [E2E Environment](E2E_ENVIRONMENT.md).

## 11. Наблюдаемость и fail-closed — не только метрики

**Урок.** Реализация HTTP/Redis/PostgreSQL/OData/RSV трассировки не доказывает восстановление от аварии; синтетические fault tests не равны замерам в production-like окружении. Нарушение записи обязательного audit должно блокировать dispatch, а не бесшумно возвращать данные.

**Правило.** Требуйте реального негативного доказательства DB/Redis/JWKS/secrets/OData/RSV failure/recovery, transport timeouts и data-redaction. Любое критическое `audit unavailable` — deny. Не публикуйте query/raw credentials в evidence.

## 12. Phase 2 — развитие без подмены фактов

**Урок.** Автообновление LDM/PDM, история наблюдений и коннекторы полезны, но polling не может гарантировать все промежуточные изменения. Нельзя превращать `OBSERVED` в `ACCEPTED` силами модели AI и использовать фальшивую «нативную» сверку на основе собственных же MCP данных.

**Правило.** Phase 2 вводится через собственные review gates: immutable events, scoped PostgreSQL RLS, optimistic CAS/leases/cursors, drift-vs-failure, настоящие 1C reports, independent attestation, controlled source budget и explicit production permit. Пока отдельные gate не пройдены, это **WIP**, даже если код в feature-ветке выполняется.

См. [Phase 2 overview](phase2/README.md), [Phase 2 plan](phase2/PLAN_PHASE2_RU.md).

## 13. Чистый Windows install: отдельно проверить ComSpec и source grants

**Урок из выполненной 09.10.2026 установки:** `Start-Process -FilePath $env:ComSpec` может получить пустой аргумент в удалённой noninteractive PowerShell. Теперь E2E helper проверяет штатный `cmd.exe` и восстанавливает `ComSpec` в процессе. Это не повод снижать ExecutionPolicy или отключать ACL.

**Второй подтверждённый случай:** test `AUDITOR` platform role успешно создавалась, но новый отдельный тестовый DB не имел data-plane source grant. `source_health`/ `onec_capabilities` выдали `AccessDenied` — корректную защиту, а не сломанную capability-схему. Ограниченный тестовый bootstrap для конкретного real1c source и idempotent repair позволяют проверить позитивный кейс. На реальном тестовом источнике **7/7** позитивных и негативных checks прошли. [Отчёт](../reports/FRESH_INSTALL_REAL1C_VERIFICATION_2026-10-09.md).

## Чек-лист перед любым публичным заявлением «готово»

- Назван exact Git SHA, версия конфигурации и тип окружения.
- Есть защищённые настоящие роли/ACL, read-only границы, egress и audit.
- Есть реальная L2 native-сверка на разрешённой базе; synthetic L1 помечена явно.
- Отличаются «код реализован», «тест пройден», «gate закрыт» и «production разрешён».
- Не скрыты skipped/NOT_RUN, внешние approvals и остаточные риски.
- В документации не раскрыты URL клиентов, пароли, bearer-токены, DSN и приватные цифры.

Эта запись — **операционное руководство**, не утверждение, что все перечисленные инварианты уже достигли production GO.
