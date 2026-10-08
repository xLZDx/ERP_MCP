# ERP_MCP — secure, read-only AI gateway for 1C

[**Русский**](#о-проекте) · [**English**](#english-overview) · [**Install / Установка**](docs/INSTALLATION_GUIDE_RU.md) · [**Lessons learned**](docs/LESSONS_LEARNED_RU.md)

> **Release 1 (ERP_MCP v1):** active read-only 1C gateway; implementation and acceptance are ongoing. **Not generally approved for production.**
> **Phase 2 (ERP_MCP v2 / Living Model):** **🚧 Work in progress.** Architecture and requirements are documented, and development is carried out separately. Phase 2 is **not a completed or generally available feature of `main`**.

ERP_MCP exposes governed, auditable access to 1C through the [Model Context Protocol](https://modelcontextprotocol.io/). The goal is **reliable accounting answers within explicit access boundaries**, not uncontrolled AI access to a database. It separates a public read-only MCP data plane from administrator operations and supports an eventual shared connector/control architecture for other systems.

## О проекте

**ERP_MCP 1 / Release 1** — MCP-шлюз для безопасного чтения данных из нескольких баз **1С:Предприятие**. Пользователь или AI-клиент работает с разрешёнными источниками и организациями; шлюз проверяет identity, ACL, capabilities, ограничения запросов и аудита. Конкретные бухгалтерские ответы доступны только при подтверждённом семантическом профиле и независимой сверке со штатными отчётами 1С.

**ERP_MCP 2 / Phase 2** — следующий этап: постоянно актуализируемая модель подключённых источников, история их изменений, дополнительные коннекторы, управляемая автоматическая сверка и рабочее место для исследования расхождений. **Эти возможности сейчас в разработке**, а не в списке готовых функций релиза.

### Статус версий

| Функциональность | Release 1 / ERP_MCP v1 | Phase 2 / ERP_MCP v2 |
| --- | --- | --- |
| Разрешённые источники 1С, organizations/grants | Реализованы базовые control-plane механизмы; приёмка зависит от окружения | Наследует границы R1, не обходит их |
| Read-only OData v3 / metadata / capability routing | Реализованы маршруты и защитные контракты; реальный профиль требует проверки | Наблюдения и детальные изменения возможностей по объектам **WIP** |
| MCP tools / semantic accounting | Инструменты и exact-profile gates; поддержка зависит от конфигурации и native evidence | Перспектива расширенных validated операций **WIP** |
| Admin Control Center, аудит, ограничения | Реализуемые и проверяемые части R1; полный release gate ещё открыт | Job/connector/workbench administration **WIP** |
| Real 1C / COM / RSV fallback | Ограниченный, проверяемый metadata-first путь; dangerous business queries заблокированы | Квалифицированный native report capture **WIP** |
| Независимая сверка со штатными отчётами 1С | Обязательное условие доверенных цифр и release GO; не заменяется L1 | Автоматизация сбора и сравнения + attestation **WIP** |
| Living Model Registry, PDM/LDM, taxonomy | Не входит в поставляемый R1 runtime | **Проектируется и разрабатывается, не production-ready** |
| Bitemporal history, diff/impact graph, adaptive jobs | Не заявлены как функции R1 | **WIP**, с отдельными validation gates |
| Дополнительные источники (например, Drive) | Только зарезервированные adapter boundaries, не «подключено из коробки» | Connector framework и provider-specific qualification **WIP** |
| Общий production GO | **NO-GO до закрытия обязательных gates** | **NO-GO / WIP** |

Здесь **P0–P10** в [Master Plan R1](docs/MASTER_PLAN.md) — *инженерные этапы Release 1*, а **Phase 2 S0–S10** — *отдельная дорожная карта следующей версии*. Это разные шкалы, их не следует путать.

## Быстрый старт: установка из GitHub

**Рекомендуемый первый опыт — полностью синтетический Fake1C стенд, без реальной бухгалтерской базы.**

Потребуются Windows, Git, Python **3.12+**, [uv](https://docs.astral.sh/uv/getting-started/installation/), Docker Desktop (Linux containers) и PowerShell 5.1/7.

```powershell
git clone https://github.com/xLZDx/ERP_MCP.git
Set-Location .\ERP_MCP
uv sync --locked --all-groups --extra dev
.\scripts\e2e\up.ps1 -Seed baseline
.\scripts\e2e\status.ps1
.\scripts\e2e\test.ps1 -Suite smoke
```

После успешного старта тестового окружения:
- Проверка gateway: [http://127.0.0.1:18000/healthz](http://127.0.0.1:18000/healthz)
- Admin UI: [http://127.0.0.1:18000/admin/](http://127.0.0.1:18000/admin/) (test IdP)
- MCP endpoint: `http://127.0.0.1:18000/mcp` (это не HTML-сайт)

Остановка **только своего** disposable-стенда: `.\scripts\e2e\down.ps1`. Не используйте `-Purge` без понимания удаления disposable data/volumes.

**Полная инструкция с prerequisites, установкой Python/infra, настоящей тестовой 1С, ACL, OData, ChatGPT, troubleshooting и production checklists: [УСТАНОВКА ПО ШАГАМ →](docs/INSTALLATION_GUIDE_RU.md).**

**История ошибок и принятых ограничений: [LESSONS LEARNED →](docs/LESSONS_LEARNED_RU.md).**

### Development-only gateway (без полного E2E)

```powershell
Copy-Item .env.development.example .env
uv sync --locked --all-groups --extra dev
docker compose -f compose.development.yml up -d postgres redis
uv run --locked python scripts/migrate.py
uv run --locked python scripts/doctor.py
uv run --locked uvicorn business_ai_gateway.app:app --host 127.0.0.1 --port 8000
```

Этот dev-профиль может содержать демонстрационные секреты и публикует локальные dev-порты. Он **не** является production deployment. Реальные источники подключайте только по [инструкции](docs/INSTALLATION_GUIDE_RU.md#5-подключение-своей-тестовой-базы-1с-l2-только-с-разрешения-владельца) и [production security contract](deploy/PRODUCTION.md).

## Что входит в ERP_MCP 1

### Read-only MCP data plane

- Управляемый список источников и компаний, source/company ACL, строгая проверка OAuth/OIDC в защищённом окружении.
- Метаданные и capability negotiation по реально поддерживаемому поведению 1С; OData v3 + приватный pinned adapter/sidecar.
- Ограничения строк, ответов, фильтров, времени, запросов и сетевых адресов; запросы только к заранее зарегистрированным источникам.
- Read-only инструменты: `system_status`, `sources_list`, `companies_list`, `source_health`, `onec_capabilities`, `onec_metadata_summary`, `onec_find_entities`, `onec_read`.
- Семантические функции учёта (включая обороты, продажи/покупки, денежные/складские и дебиторские/кредиторские представления) **только там, где подтверждены exact mapping, capability и native evidence**. Наличие исходного кода инструмента не означает, что он включён для произвольной базы.

### Security, administration and operations

- Separate Admin Control Center + role/grant management; Admin mutation APIs **не** публикуются как общедоступные MCP tools.
- PostgreSQL registry, grants и обязательный audit; Redis rate limits; secret providers и DB role split.
- Тестовая стратегия **Fake1C (L1) → реальная одноразовая тестовая база 1С (L2) → production-parity environment (L3)**.
- Приватный, ограниченный Windows/COM fallback для поддерживаемых сценариев; нельзя использовать его для произвольных AI SQL/COM команд.
- Observability, fault/restore и release-evidence процедуры; production допуск зависит от закрытия security, accuracy и operations gates.

См. [Security](SECURITY.md), [Architecture](docs/ARCHITECTURE.md), [Master Plan](docs/MASTER_PLAN.md), [Test Strategy](docs/TEST_STRATEGY.md), [Release Operations](docs/RELEASE_OPERATIONS.md).

## Что запланировано в ERP_MCP 2 (Phase 2) — 🚧 WIP

- Connector SDK и безопасные источники с отдельными permissions/secret refs.
- **Living Model Registry:** observed/accepted schema, PDM/LDM, taxonomy, canonical fingerprints.
- PostgreSQL temporal/event history, CAS, leases, cursors и консервативная оценка влияния изменений.
- Адаптивный мониторинг метаданных, разделение *source unavailable* и *schema drift*.
- Настоящий native report capture 1C с проверкой provenance; независимая аттестация и автоматическое сравнение по подтверждённым scopes.
- UI для истории, объяснений отклонений, разрешённого rerun и работы с исключениями.
- Поэтапное расширение на внешних providers только после специальных permission/revocation/load gates.

**Это план и экспериментальная работа; не обещание, что функции доступны после `git clone main`.** Для production native capture требуется отдельное разрешение на конкретную базу, компанию, рецепт и окно выполнения.

Документы: [Phase 2 README](docs/phase2/README.md) · [TDD](docs/phase2/TDD_PHASE2_RU.md) · [Roadmap S0–S10](docs/phase2/PLAN_PHASE2_RU.md) · [Acceptance](docs/phase2/TEST_PLAN_PHASE2_RU.md).

## ChatGPT / Secure MCP Tunnel

Для демонстрации изолированного **Fake1C** через ChatGPT предусмотрены Windows launchers:

```powershell
.\scripts\chatgpt\up.ps1
.\scripts\chatgpt\doctor.ps1
.\scripts\chatgpt\install-tunnel-client.ps1
```

Этот endpoint намеренно **test-only**, OAuth на нём отключён **только** для synthetic data. Для реальной базы нужен production OAuth, private network, реальные grants и approved native evidence. См. [ChatGPT ↔ ERP_MCP integration](docs/CHATGPT_MCP_INTEGRATION.md) и [русский runbook](docs/ERP_MCP_CHATGPT_RUNBOOK_RU.md).

## English overview

**ERP_MCP Release 1** is a 1C-first read-only MCP gateway with registered sources, scoped permissions, OAuth/OIDC, audit, controlled OData capability routing, security limits, and configuration-specific semantic accounting tools. It supports synthetic local tests and authorized real-1C validation. **It is not yet generally production-approved.**

**ERP_MCP Phase 2** is the **in-progress** Living Model / connector / history / reconciliation program. Its design includes scoped event history, drift-aware metadata discovery, independently verifiable 1C report evidence, and an operator workbench. **Do not assume these features ship in the main branch.**

**New users:** start with the [step-by-step installation guide](docs/INSTALLATION_GUIDE_RU.md) and the [lessons learned](docs/LESSONS_LEARNED_RU.md). They explain the safe synthetic first run, the real-1C onboarding boundary, production prerequisites and known limitations.

## Дополнительная документация

| Раздел | Ссылка |
| --- | --- |
| Нормативный индекс и приоритет требований | [docs/DOCUMENT_INDEX.md](docs/DOCUMENT_INDEX.md) |
| Подробная установка | [docs/INSTALLATION_GUIDE_RU.md](docs/INSTALLATION_GUIDE_RU.md) |
| Ошибки и lessons learned | [docs/LESSONS_LEARNED_RU.md](docs/LESSONS_LEARNED_RU.md) |
| Реальный тестовый стенд и L1/L2 | [docs/E2E_ENVIRONMENT.md](docs/E2E_ENVIRONMENT.md) |
| Подключение ChatGPT | [docs/CHATGPT_MCP_INTEGRATION.md](docs/CHATGPT_MCP_INTEGRATION.md) |
| Реальный Windows 1C/COM bridge | [docs/runbooks/RSV_DATA_BRIDGE.md](docs/runbooks/RSV_DATA_BRIDGE.md) |
| Production deployment и rollback | [deploy/PRODUCTION.md](deploy/PRODUCTION.md) / [deploy/ROLLBACK.md](deploy/ROLLBACK.md) |
| Phase 2 (WIP) | [docs/phase2/README.md](docs/phase2/README.md) |
| Engineering Command Center | [docs/ERP_MCP_ENGINEERING_COMMAND_CENTER.html](docs/ERP_MCP_ENGINEERING_COMMAND_CENTER.html) |
| Upstream reuse and third-party licensing | [vendor/UPSTREAMS.md](vendor/UPSTREAMS.md) / [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) |

Contributions: [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

**Release rule:** working code ≠ tested deployment ≠ accounting evidence ≠ formally approved production release.
