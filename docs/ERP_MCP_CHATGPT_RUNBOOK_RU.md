# ERP_MCP ↔ ChatGPT — краткий runbook

Обновлено: 2026-10-07

## 1. Текущий локальный статус

Репозиторий:
`D:\Repo\ERP_MCP-chatgpt`

Git branch:
`feature/chatgpt-mcp-integration`

Текущий OpenAI tunnel:
`tunnel_6ac64553de90819188eaf83bc540eb7a`

Tunnel profile:
`erp-mcp-local`

Текущий MCP target из `.chatgpt\tunnel.json`:
`http://127.0.0.1:21000/mcp`

ВАЖНО: файл `.chatgpt\tunnel-health.json` содержит старый health snapshot, снятый для предыдущего endpoint `18100/mcp`. Его нельзя считать подтверждением текущего `21000/mcp`. Перед использованием текущий endpoint нужно перепроверить отдельно.

DC_MCP:
использовать как отдельный административный канал к локальному ПК/репозиториям. Не использовать его как обязательную прокладку для рабочих ERP-запросов.

Целевой рабочий data path:
ChatGPT → OpenAI Secure MCP Tunnel → tunnel-client → ERP_MCP → 1С

## 2. Что действительно требуется

ERP_MCP НЕ обязан стоять на том же сервере, где физически находится база 1С.

Требования простые:

1. Хост с `tunnel-client` должен иметь доступ к ERP_MCP.
2. ERP_MCP должен иметь разрешённый доступ к 1С.
3. Между ChatGPT и локальной сетью используется Secure MCP Tunnel.
4. 1С и ERP_MCP не требуется публиковать напрямую в интернет.
5. Для реальной финансовой базы production-доступ должен сохранять OAuth / source ACL / company ACL.
6. MCP-инструменты ChatGPT должны оставаться read-only.

## 3. Варианты размещения

### Вариант A — всё на одном Windows-сервере

На одном хосте:
- 1С
- ERP_MCP
- tunnel-client

Схема:
ChatGPT → Secure MCP Tunnel → tunnel-client → localhost ERP_MCP → 1С

Плюсы:
- минимальная сложность;
- минимум firewall правил;
- простой troubleshooting.

Минусы:
- компоненты сильнее связаны;
- обновления/нагрузка делят один хост.

### Вариант B — рекомендуемый

Server A:
- 1С

Server B:
- ERP_MCP
- tunnel-client

Схема:
ChatGPT → Secure MCP Tunnel → Server B: tunnel-client → ERP_MCP → private LAN → Server A: 1С

Плюсы:
- хороший security boundary;
- ERP_MCP можно обновлять отдельно от 1С;
- 1С остаётся полностью приватной;
- tunnel-client находится рядом с MCP endpoint.

Это рекомендуемый вариант для твоей архитектуры.

### Вариант C — всё раздельно

Server A:
- 1С

Server B:
- ERP_MCP

Server C:
- tunnel-client

Схема:
ChatGPT → Secure MCP Tunnel → Server C → private MCP → Server B → private 1С → Server A

Использовать только если инфраструктура требует отдельный edge/connector host.

Минусы:
- больше сетевых зависимостей;
- больше firewall/DNS/TLS точек отказа;
- сложнее диагностика.

## 4. OpenAI — что нужно

Для Secure MCP Tunnel нужны:

- `tunnel_id`;
- Runtime API Key;
- права Tunnels Read + Use для runtime/оператора;
- tunnel должен быть связан с нужным ChatGPT workspace;
- `tunnel-client` должен иметь исходящий HTTPS-доступ к OpenAI;
- `tunnel-client` должен видеть приватный MCP endpoint.

Для создания/редактирования tunnel нужны Tunnels Read + Manage.

Официальные ссылки:

- Tunnels:
  https://platform.openai.com/settings/organization/tunnels
- API keys:
  https://platform.openai.com/settings/organization/api-keys
- Roles:
  https://platform.openai.com/settings/organization/people/roles
- Secure MCP Tunnel:
  https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- Custom MCP server:
  https://developers.openai.com/api/docs/guides/custom-mcp-server

## 5. OAuth для реальной 1С

Secure MCP Tunnel защищает приватный транспорт, но не заменяет ERP_MCP authorization.

Для реальной базы:

ChatGPT
→ Tunnel
→ ERP_MCP
→ OAuth identity
→ source ACL
→ company ACL
→ 1С

OpenAI может проводить OAuth discovery через tunnel, но сам authorization server не становится автоматически публично доступным через tunnel.

Поэтому если ERP_MCP использует OAuth:
- authorization server должен быть доступен участнику browser OAuth flow;
- либо нужно использовать подходящий публично-доступный OAuth provider;
- нельзя просто выключать OAuth на production financial endpoint ради удобства.

## 6. Read-only граница

Для ChatGPT ERP_MCP должен предоставлять только безопасные read-only tools.

Примеры:
- sources_list
- companies_list
- source_health
- onec_capabilities
- onec_metadata_summary
- onec_find_entities
- onec_read
- accounting_balance_and_turnovers
- accounting_posting_rows
- payable_balance
- receivable_balance
- payable_aging
- receivable_aging
- inventory_balance
- inventory_movements
- bank_balance
- cash_movements
- sales_documents
- purchase_documents

Admin Control Center должен оставаться отдельным.

## 7. Финальная проверка

Перед тем как считать интеграцию готовой:

1. `GET /healthz` ERP_MCP → 200.
2. `GET /readyz` ERP_MCP → 200.
3. MCP initialize → PASS.
4. tools/list → ожидаемый read-only catalog.
5. `sources_list` → именно real 1C source, не synthetic fixture.
6. `companies_list` → только разрешённые компании.
7. Пробный accounting read → реальные данные.
8. Tunnel `/healthz` → live.
9. Tunnel `/readyz` → ready.
10. ChatGPT custom MCP создан через Connection = Tunnel.
11. В ChatGPT доступен отдельный `@ERP_MCP`.
12. Запрос из ChatGPT появляется в ERP_MCP audit.
13. Write/delete tools отсутствуют.
14. Реальные 1С credentials не передаются в ChatGPT и не сохраняются в tunnel profile.

## 8. Рекомендованная архитектура для тебя

Рабочий канал ERP:

ChatGPT
→ OpenAI Secure MCP Tunnel
→ tunnel-client
→ ERP_MCP
→ private 1С

Административный канал:

ChatGPT
→ DC_MCP
→ Windows / Git / локальные файлы / обслуживание

Эти два канала лучше держать раздельно.

## 9. Что проверить следующим шагом именно сейчас

Текущий tunnel profile уже указывает на:
`http://127.0.0.1:21000/mcp`

Нужно проверить:
- что `21000/mcp` — именно real-1C ERP_MCP endpoint;
- что там включён правильный OAuth/ACL режим;
- что `sources_list` возвращает real source;
- что ChatGPT custom MCP использует именно tunnel `tunnel_6ac64553de90819188eaf83bc540eb7a`;
- после этого сделать контрольный запрос:
  «Сколько мы должны поставщикам по счёту 521.1 на 31.08.2026?»

