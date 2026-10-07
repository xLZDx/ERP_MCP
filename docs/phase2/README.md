# ERP_MCP Phase 2 — проектный пакет v0.1

08.10.2026 · DRAFT FOR REVIEW. R1 остаётся frozen. Это проектные документы, не реализация Phase2 и не изменение release verdict, runtime, migrations, grants или native validation policy R1.

## Основные локальные документы

- TDD_PHASE2_RU.md — 28 требований, архитектура, connectors, PDM/LDM, taxonomy, Time DB, native capture, reconciliation и безопасность.
- PLAN_PHASE2_RU.md — 11 спринтов S0–S10, gates G0–G7, dependencies, spikes, rollout/rollback.
- STORIES_PHASE2_RU.md — 48 историй, связанных со 144 acceptance scenarios.
- TEST_PLAN_PHASE2_RU.md — уровни, actual assertions, capacity/fault matrix и separate user/admin UAT.
- NATIVE_REPORT_PROTOCOL_RU.md — manual UI, qualified UI automation, optional qualified standard engine, dev/prod permissions и 12 qualification cases.
- DECISIONS_AND_SOURCES_RU.md — ADR proposals, риски, источники и открытые решения.
- CONTRACTS_AND_API_RU.md — уточнение data dictionary, API, scope/time/transaction boundaries и четырёх JSON contracts.
- PACKAGE_COMPLETION_RU.md — точный итог подготовки, размещение и ограничения проверки.
- SPEC_VALIDATION_SUMMARY.json — фактический результат SPEC/L0 и SHA-256 архива.

## Переносимый пакет

В чате предоставлен ERP_MCP_PHASE2_SPEC_v0.1_2026-10-08.zip: 38 файлов, расширенная редакция документов, offline HTML, requirements/stories/test_cases YAML, traceability.csv, 144 Gherkin scenarios, 4 JSON Schemas, synthetic examples и executable SPEC/L0 tests.

Архив не скопирован и не распакован на Windows. До распаковки нельзя считать companion YAML/schemas/tests уже присутствующими в этом каталоге. Для обычного сохранения и распаковки подходит новый подкаталог docs\phase2\spec-v0.1\, без перезаписи existing files.

## Проверка

В контейнере подготовки реально выполнены 35 SPEC/L0 checks: все PASS, без skipped. Product tests144, реальные 1С/Drive/PostgreSQL/UI/COM/native/prod проверки — NOT_RUN. Gherkin step implementations ещё нужно разработать. JSON Schema не доказывает genuine artifact, actual permissions или independent attestation.

HTML прошёл статическую проверку структуры/ссылок/отсутствия внешних render resources. Визуальный browser run не выполнен: managed Chromium заблокировал file navigation; ограничения не обходились. Подробнее — PACKAGE_COMPLETION_RU.md.

## Основное решение

Настоящий штатный отчёт1С может быть independent native oracle и при ручном, и при квалифицированном автоматическом запуске. Файл, созданный из MCP-чисел, не проверяет тот же MCP независимо. Требуются origin/recipe qualification, source consistency, все шесть колонок и строки, затем independent accounting approval. Prod capability сохраняется как default OFF до target-specific permit.

Точные денежные значения пользователя не добавлены в новые Git/package fixtures. Частная арифметическая записка находится отдельно в чате и не является native validation.

## Статус

Документационный пакет завершён для review. Реализация Phase2 не запускалась. R1 code/config/migrations/permissions не менялись этим этапом. Нет commit/push/merge, рестартов, нагрузки или удаления; сторонние изменения не тронуты.
