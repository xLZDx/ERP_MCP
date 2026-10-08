# ERP_MCP — пошаговая установка (Release 1)

**Для кого:** разработчик, администратор или владелец 1С, который впервые скачал [ERP_MCP](https://github.com/xLZDx/ERP_MCP).  
**Актуальность документа:** 9 октября 2026 года.  
**Важно:** Release 1 пока **не имеет подтверждённого общего production GO**; Phase 2 находится в разработке. Успешная установка тестового стенда не означает разрешения подключать клиентов к production.

Этот документ проводит по трём разным сценариям:

1. **L1 — учебный стенд Fake1C:** лучший первый запуск, без настоящей 1С и клиентских данных.
2. **L2 — собственная тестовая база 1С:** реальное OData/COM-подключение, отдельная разрешённая тестовая база и сверка с 1С.
3. **L3 / production:** защищённый шлюз, настоящая IAM/ACL, сеть, секреты и формальная приёмка. Это **не** one-click вариант.

> Не устанавливайте демонстрационный профиль без OAuth для реальных данных. Не направляйте скрипты reset, fault, purge или тестовые seed-команды на существующую рабочую базу.

## 0. Что устанавливается

```text
AI / MCP-клиент
    │ /mcp, OAuth/OIDC и ACL в реальном окружении
    ▼
ERP_MCP gateway ── PostgreSQL (источники, grants, аудит)
    │             └─ Redis (rate limits)
    ▼
Read-only OData adapter / защищённый sidecar
    ▼
Разрешённая публикация 1С (HTTPS) ── read-only пользователь
```

В тестовом стенде вместо реальной 1С работает **Fake1C**. Не смешивайте L1 с доказательством бухгалтерской точности L2/L3.

## 1. Предварительные требования

### Windows 10/11 — рекомендуемый путь для первого запуска

- **Git** — доступен в PowerShell: `git --version`.
- **Python 3.12+** — `py -3.12 --version` (версию можно обновить, соблюдая `pyproject.toml`).
- **uv** — менеджер Python с lock-файлом: `uv --version`. Установка: [официальное руководство uv](https://docs.astral.sh/uv/getting-started/installation/).
- **Docker Desktop** — запущен с **Linux containers**, команда `docker compose version` работает.
- **PowerShell 5.1 или 7** — тестовые `.ps1`-скрипты предназначены прежде всего для Windows.
- Доступные локальные порты. Для стандартного стенда: `15432`, `16379`, `18766`, `18767`, `18080`, `18000`. Для отдельного ChatGPT-демо используется свой порт `18100` и смещение тестовых портов `5000`.
- Для браузерных E2E по необходимости Chromium/Playwright.

**Проверьте перед скачиванием:**

```powershell
git --version
py -3.12 --version
uv --version
docker version
docker compose version
$PSVersionTable.PSVersion
```

Если `docker version` показывает ошибку daemon, сначала запустите Docker Desktop. **Не** продолжайте установку, пока он недоступен.

### Linux / macOS

Python 3.12+, uv, Git и Docker пригодны для **базового developer-пути**, но Windows PowerShell E2E, 1С COM и Windows RSV bridge не являются автоматически кроссплатформенными. Для них используйте отдельный поддерживаемый Windows-хост. Не считайте Linux/macOS полной заменой L2/COM-стенда.

## 2. Скачать ERP_MCP из GitHub

Откройте PowerShell **в новой пустой папке** и выполните:

```powershell
git clone https://github.com/xLZDx/ERP_MCP.git
Set-Location .\ERP_MCP
git branch --show-current
git status --short
git log -1 --oneline
```

Ожидается ветка `main` и пустой `git status --short`. Не переключайтесь на ветки `phase2/*` или `integration/*` для стандартного знакомства. Ветки разработки и PR не гарантируют совместимого, законченного установочного комплекта.

Для обновления **чистого** клона:

```powershell
git pull --ff-only origin main
```

Если Git сообщает о локальных изменениях — сначала сохраните их отдельно; **не** используйте `reset --hard` или `clean -fd` как универсальное «исправление».

## 3. Самый простой запуск: полностью синтетический L1 (Windows)

Этот путь автоматически настраивает локальный Docker/PostgreSQL/Redis, тестовый IdP, Fake1C, sidecar, gateway и изолированные учетные записи. Никакие реальные данные 1С не нужны.

```powershell
# Из корня ERP_MCP
uv sync --locked --all-groups --extra dev
.\scripts\e2e\up.ps1 -Seed baseline
.\scripts\e2e\status.ps1
.\scripts\e2e\test.ps1 -Suite smoke
```

Сначала дождитесь завершения `up.ps1`. При готовом стенде локальные адреса:

| Сервис | Адрес |
| --- | --- |
| Gateway health | `http://127.0.0.1:18000/healthz` |
| Gateway readiness | `http://127.0.0.1:18000/readyz` |
| MCP endpoint | `http://127.0.0.1:18000/mcp` |
| Admin UI (тестовая) | `http://127.0.0.1:18000/admin/` |

`/mcp` — протокольный endpoint, не обычная HTML-страница; не ожидайте, что он красиво откроется в браузере. `healthz=200` сам по себе не доказывает, что есть доступ к 1С или что отчёты сверены.

Параметры и случайно созданные локальные секреты находятся в **git-ignored** `.e2e/`. Никому не отправляйте содержимое `.e2e/credentials.json`, `.e2e/env.ps1` или токены из терминала.

### Если нужны браузерные тесты

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
.\scripts\e2e\test.ps1 -Suite user
.\scripts\e2e\test.ps1 -Suite admin
```

Полная матрица и ожидаемые внешние skip-ограничения: [E2E_ENVIRONMENT.md](E2E_ENVIRONMENT.md), [MANUAL_ACCEPTANCE_USER.md](MANUAL_ACCEPTANCE_USER.md), [MANUAL_ACCEPTANCE_ADMIN.md](MANUAL_ACCEPTANCE_ADMIN.md). `skipped` ≠ `passed`.

### Корректная остановка

```powershell
.\scripts\e2e\down.ps1
```

Не используйте `-Purge`, пока осознанно не решили удалить **именно disposable** данные тестового стенда; этот флаг удаляет его данные/volume. `reset.ps1` также пересоздаёт тестовую схему — не запускать без понимания назначения.

## 4. Альтернативный запуск только gateway для разработки

Если нужны Python-сервер и инфраструктура без полного E2E:

```powershell
Copy-Item .env.development.example .env
uv sync --locked --all-groups --extra dev
docker compose -f compose.development.yml up -d postgres redis
docker compose -f compose.development.yml ps
uv run --locked python scripts/migrate.py
uv run --locked python scripts/doctor.py
uv run --locked uvicorn business_ai_gateway.app:app --host 127.0.0.1 --port 8000
```

Это **локальная разработка**, а не готовая production-конфигурация. `compose.development.yml` публикует стандартные порты PostgreSQL `5432` и Redis `6379`; применять только на доверенном одиночном компьютере с подходящими правилами брандмауэра. Файл `.env.development.example` содержит небезопасные для production demo-значения. Проверьте отсутствие конфликтов по портам и учётным данным. Запускайте эти команды в новом рабочем каталоге, не поверх чужого стенда.

После запуска:

```powershell
Invoke-WebRequest http://127.0.0.1:8000/healthz -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8000/readyz -UseBasicParsing
```

Для полноценной проверки разделения БД-ролей и тестовой Admin UI используйте [ручное QA-руководство](QA_MANUAL_TEST_AND_ENVIRONMENT_GUIDE.md), а не общие development-секреты.

**Linux/macOS:** аналогичный Python/docker-путь возможен с `cp`, `uv sync` и `uv run`; не переносите Windows `.ps1`-команды вслепую.

## 5. Подключение своей тестовой базы 1С (L2, только с разрешения владельца)

Это **отдельная процедура**, а не продолжение синтетической базы. Убедитесь, что вы действительно владелец или администратор разрешённой disposable-копии 1С.

1. Подготовьте отдельную базу 1С 8.3 для тестов. **Не** проводите испытания на боевой базе и не выдавайте шлюзу права записи.
2. Настройте штатную публикацию OData (`/odata/standard.odata`) с **HTTPS** и минимальными правами учетной записи; откройте её только для утверждённых хостов шлюза. Проверьте доступность `$metadata` **вручную из разрешённой сети** без публикации учётных данных.
3. Укажите разрешённый hostname и адресные CIDR-диапазоны. В production обязателен контроль egress на уровне сети и connect-time DNS; точная hostname allowlist не заменяет firewall.
4. Настройте секреты через разрешённый secret provider: **ключи-ссылки**, а не пароли в Git, prompt, URL, отчётах или аргументах команд.
5. Поднимите gateway, миграции и приватный read-only OData-sidecar по [production-контракту](../deploy/PRODUCTION.md) и [договору sidecar](ADAPTER_CONTRACT_ODATA_SIDECAR.md). Для локального real-1C E2E используйте [специальный режим](E2E_ENVIRONMENT.md#real-local-1c-profile-e2e_real1c1); он требует отдельные `E2E_SOURCE_ALLOWED_HOSTS`, `E2E_SIDECAR_URL` и `-Seed bootstrap-only`, а не Fake1C `baseline`.
6. Зарегистрируйте источник **операторским** CLI. Пример для заранее настроенных secret refs:

   ```powershell
   uv run --locked python scripts/admin.py source-upsert `
     --source-id sample-1c-l2 `
     --display-name "Test 1C" `
     --base-url https://onec-test.example.org/demo/odata/standard.odata `
     --username-secret sample-1c-l2-user `
     --password-secret sample-1c-l2-password
   ```

   Адрес и secret refs выше — **плейсхолдеры**: это не реальный сервис. Команда не создаёт secret entries и не выдаёт ACL. В production администратор использует отдельную `BAG_ADMIN_DATABASE_URL`/роль.

7. Сначала зарегистрируйте проверенную компанию, затем выдайте **минимальный** grant валидированному OAuth-субъекту:

   ```powershell
   uv run --locked python scripts/admin.py company-upsert `
     --company-id <approved-uuid> `
     --source-id sample-1c-l2 `
     --external-ref <exact-1c-organization-id> `
     --display-name "Test company"

   uv run --locked python scripts/admin.py grant-add `
     --principal <oidc-subject> `
     --source-id sample-1c-l2 `
     --company-id <approved-uuid>
   ```

   **Ограничение Release 1:** company-scoped grant поддерживает discovery, но generic `onec_read` требует source-wide grant, пока конкретный семантический адаптер не гарантирует company scope. **Не расширяйте права только ради того, чтобы запрос заработал**; выбирайте предусмотренный company-scoped семантический путь либо остановите проверку.

8. Сверьте метаданные, capability profile и десять независимых штатных отчётов 1С по соответствующему source/company/configuration. Если профиль `UNVALIDATED`, нет native evidence или доступ истёк — это **блокировка**, а не разрешение угадать числа. См. [Semantic Profiles](SEMANTIC_PROFILES.md), [Native report capture](NATIVE_REPORT_CAPTURE_RUNBOOK.md) и [MVP acceptance](MVP_SCOPE.md).

### Дополнительно: COM / RSV bridge на Windows

COM является отдельным, более чувствительным вариантом для некоторых поддерживаемых конфигураций. Требует установленной лицензированной 1С и `V83.COMConnector`; на Windows возможна per-user регистрация через официальные компоненты. Смотрите [RSV Data Bridge](runbooks/RSV_DATA_BRIDGE.md) и [опыт локальной настройки](../reports/LOCAL_1C_SETUP_HANDOFF.md).

**Запрещено считать безопасными по умолчанию** `execute_query`, `reveal`, generic business query или прямое выставление RSV MCP наружу. Пока нет доказанной неизменяемой company-boundary и zero-write, бизнес-операции COM должны оставаться `CAPABILITY_UNSUPPORTED`.

## 6. Подключение ChatGPT (только отдельный синтетический пример)

Чтобы проверить MCP-интеграцию **без настоящих данных**, в новом чистом клоне Windows:

```powershell
.\scripts\chatgpt\up.ps1
.\scripts\chatgpt\doctor.ps1
.\scripts\chatgpt\install-tunnel-client.ps1
```

Это дополнительный локальный gateway `http://127.0.0.1:18100/mcp`, где OAuth выключен **только для фиксированного Fake1C и loopback**. Tunnel не добавляет полноценной пользовательской авторизации к реальным данным. Сохраните приватность control-plane API key, выберите OpenAI tunnel и пройдите [полный сценарий настройки](CHATGPT_MCP_INTEGRATION.md).

После проверки:

```powershell
.\scripts\chatgpt\stop-tunnel.ps1
.\scripts\chatgpt\down.ps1
```

**Никогда не переключайте no-OAuth demo на реальную 1С.**

## 7. Что нужно для промышленного развёртывания

Этап **требует отдельного инженерного проекта и приёмки**, а не простого `docker compose up`:

- отдельные production PostgreSQL роли (`BAG_DATABASE_URL` runtime, `BAG_ADMIN_DATABASE_URL` administrator, `BAG_MIGRATION_DATABASE_URL` owner) и проверенные migration/rollback;
- реальные IdP issuer/audience/JWKS/scope, ACL уровня source/company, отзыв grants и раздельный Admin OAuth;
- секреты только из file/GCP secret manager, никогда не из environment provider для production;
- HTTPS, private sidecar, pinned upstream и токен, точные host/CIDR allowlists, firewall, запрет redirect и SSRF;
- append-only audit, Redis cross-replica limits, мониторинг, backup/PITR и восстановление;
- настоящий native accounting reconciliation L2/L3 + пользовательская приёмка; security/load/ops evidence; утверждённый production GO.

Контрольные документы: [Production](../deploy/PRODUCTION.md), [Security](../SECURITY.md), [Rollback](../deploy/ROLLBACK.md), [Release Operations](RELEASE_OPERATIONS.md), [Definition of Done](DEFINITION_OF_DONE.md).

## 8. Troubleshooting — сначала это

| Симптом | Что проверить / безопасное действие |
| --- | --- |
| `docker version`: daemon unreachable | Docker Desktop запущен и выбран Linux containers |
| `uv sync --locked` не проходит | Python >=3.12, uv обновлён, доступ к package index; **не** обходить lock самовольным upgrade |
| `port already in use` / `foreign listener` | `Get-NetTCPConnection -State Listen -LocalPort 18000`; не убивать чужой процесс; отдельный клон/порт offset |
| `/healthz` доступен, `/readyz` нет | DB/Redis, миграции, ACL/секреты и логи тестового стенда; проверить `scripts\e2e\status.ps1` |
| `401 / 403` | Реальный OAuth issuer/audience/scope, source/company grant, Admin отдельно; не отключать OAuth |
| `SEMANTIC_PROFILE_UNVALIDATED` | Нужны подтверждённый mapping + genuine native reports; **не** выдавать ноль или уверенный ответ |
| `CAPABILITY_UNSUPPORTED` | Не доказана возможность конкретного адаптера/регистра/COM; не включать опасный универсальный query |
| `NEEDS_VALIDATION`, metadata drift | Различать ошибку транспорта и действительное изменение схемы, сверить fingerprints/evidence |
| Tunnel показывает недоступность | `chatgpt\doctor.ps1`, локальный gateway и tunnel credentials; demo только Fake1C |
| Изменения `git status` после установки | `.env`, `.e2e`, `.chatgpt` не должны попадать в Git; не коммитить приватные файлы |

Перед вопросами к разработчикам приложите **без секретов**: ОС, `git rev-parse --short HEAD`, версии Python/uv/Docker, команду, только безопасный код ошибки и результат `status.ps1`. Не присылайте DSN, токены, OData-пароли, customer URLs или реальные суммы.

## 9. Принципы и lessons learned

Прочитайте [LESSONS_LEARNED_RU.md](LESSONS_LEARNED_RU.md): там объяснены реальные ошибки и архитектурные решения проекта — security boundary, источники/компании, capability drift, native reconciliation, локальная Windows/COM интеграция, миграции и тестовая изоляция.

## 10. Готовность установки — что можно утверждать

- **L1 READY:** локальный `up.ps1` и `status.ps1` успешны, `smoke` прошёл — это только synthetic-contract demo.
- **L2 VERIFIED:** реальная тестовая база, права, OData/COM и независимая native-сверка пройдены на том же source/company/конфигурации.
- **Production GO:** обязательные gates закрыты на точном релизном HEAD и утверждены ответственными лицами. Текущее наличие кода или зелёные L1 тесты этому не равны.

**Phase 2** не входит в описанный здесь инсталлятор: [дизайн / статус Phase 2](phase2/README.md) и [план S0–S10](phase2/PLAN_PHASE2_RU.md). Функции Living Model ещё не следует рекламировать как общедоступные в `main`.
