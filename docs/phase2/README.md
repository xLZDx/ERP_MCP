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

На Windows **создана отдельная рабочая копия** `D:\Repo\ERP_MCP-phase2`. В ней уже сохранён `docs\phase2\spec-v0.1\ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08\` с YAML/JSON Schema/Gherkin/traceability и отдельный `docs\phase2\artifacts\ERP_MCP_PHASE2_SPEC_REBUILT_v0.1_2026-10-08.zip`. Это **пересобранный из текущих документов** пакет, а не исходный ZIP из ChatGPT; его точный SHA проверяется генератором `scripts\phase2\build_spec_bundle.py`.

## Проверка

В контейнере подготовки первоначально выполнены 35 SPEC/L0 checks: все PASS. В **изолированной Windows-копии Phase 2** дополнительно выполнены 23 новых офлайн-теста: PASS, и Ruff lint: PASS. Product tests144, реальные 1С/Drive/PostgreSQL/UI/COM/native/prod проверки — NOT_RUN. Gherkin step implementations ещё нужно разработать. JSON Schema не доказывает genuine artifact, actual permissions или independent attestation.

HTML прошёл статическую проверку структуры/ссылок/отсутствия внешних render resources. Визуальный browser run не выполнен: managed Chromium заблокировал file navigation; ограничения не обходились. Подробнее — PACKAGE_COMPLETION_RU.md.

## Основное решение

Настоящий штатный отчёт1С может быть independent native oracle и при ручном, и при квалифицированном автоматическом запуске. Файл, созданный из MCP-чисел, не проверяет тот же MCP независимо. Требуются origin/recipe qualification, source consistency, все шесть колонок и строки, затем independent accounting approval. Prod capability сохраняется как default OFF до target-specific permit.

Точные денежные значения пользователя не добавлены в новые Git/package fixtures. Частная арифметическая записка находится отдельно в чате и не является native validation.

## Статус

Документационный пакет и первый изолированный кодовый срез Phase 2 созданы и запушены **только** в `phase2/living-model-connectors-reconciliation`. R1 code/config/migrations/permissions не менялись этим этапом, merge в `main` не производился, services/1C не перезапускались, посторонние рабочие изменения не тронуты. Статус и план дальнейшего переключения — `BRANCH_ISOLATION_AND_HANDOFF.md`, `CUTOVER_PLAN_RU.md`.
