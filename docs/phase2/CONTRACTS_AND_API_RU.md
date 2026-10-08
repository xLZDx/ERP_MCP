# Phase 2 — Контракты данных и API: уточнение к ТДД

08.10.2026 · v0.1 · DRAFT FOR REVIEW. Это проектирование, не новая миграция и не перечень уже доступных tools.

## 1. Группы данных

| Группа | Предлагаемые сущности | Граница |
|---|---|---|
| Connections | connector_instances, scope_memberships, provider_principals | Existing sources/companies переиспользуются; secret refs, не значения |
| Jobs | jobs, leases, cursors, outbox | Scope+idempotency+parameter digest; fencing; atomic page/cursor/outbox |
| PDM | snapshots, object/field/relation versions | Raw и canonical hash отдельно; canonicalizer version; coverage |
| Accepted | accepted_heads, acceptance_events | CAS, independent actor/policy/evidence; scanner не approver |
| LDM | concepts, aliases, typed/dependency edges | Stable IDs, source/company scope, provenance/confidence/owner |
| Time | immutable model_events, current projections | Known/effective time, corrections/supersedes/gaps, deterministic replay |
| Capture | recipes, qualifications, execution_permits, job_events | Source/config/report/variant/executor hash, mode/window/budget |
| Evidence | artifacts, revisions, origin checks, attestations | Private immutable bytes, actual digest, authenticated signer, scoped FKs |
| Reconciliation | runs, measures, row links, discrepancies | Scope/cutoff/model/parser/recipe/policy pin; numeric vs business verdict |
| Validation | policies, operation bindings, evidence claims | Actual evidence FKs и coverage; нет произвольного JSON set VALIDATED |

Source-wide PDM может храниться один раз; company projections показывают только разрешённую область. Global observation не выдаёт company reader source-wide grant. Capture/financial jobs имеют exact company. Composite keys/FKs/RLS и runtime reauthorization защищают API, queue, cache, blob и historical view.

## 2. Time DB

Registry-recorded time задаётся сервером при commit, а не доверяется клиенту. Source-effective time заполняется только по доказанному source marker/semantics; UNKNOWN остаётся NULL. Poll timestamp нельзя выдавать за дату вступления изменения в силу.

AS KNOWN AT восстанавливает знание на момент K. AS EFFECTIVE AT V с knowledge cutoff K учитывает effective state, который был известен тогда. Late correction — новый event с supersedes, не переписывание прежней истории. При polling A→B→A без source history промежуточный B неизвестен; нужно показывать gap/coverage, не выдумывать события.

## 3. Контракты API

Register connection и source OAuth — отдельно от ChatGPT OAuth. Enqueue rescan/report/reconciliation — control mutations с idempotency/CSRF/audit; source read-only не делает enqueue неизменяющим действием.

Read model/changes/job/result — текущий scoped доступ плюс selected observed/accepted/version/time query. Historical evidence не бессрочное право на disclosure.

Report request: recipe_id/version/hash, source/company, permit reference, scope_epoch, typed parameters и private output policy. Никаких command/sql/bsl/epf_bytes/arbitrary_url/password/connection_string/force_validate.

Attest и accept — privileged commands с independent authenticated identity, exact artifact revision/claims/policy, evidence FKs и expected_previous_head. Нет открытого endpoint, который просто записывает статус VALIDATED.

Pause/revoke — scoped mutation, reason/idempotency, epoch update, outbox cancellation. Revoke before disclosure блокирует выдачу уже вычисленного результата. Rollback не возвращает отозванные grants.

## 4. Четыре JSON Schemas сопровождающего архива

- schemas/model_event.schema.json: OBSERVED event, nullable effective time, source/company scope level, coverage/gaps.
- schemas/capture_request.schema.json: typed request/recipe/permit, режим dev/staging/prod, безопасные параметры.
- schemas/native_manifest.schema.json: original artifact, источник/recipe, evidence class/authority, parameters/hashes/completeness/attestation.
- schemas/reconciliation_result.schema.json: evidence/actual/model/policy refs, Decimal strings, numeric outcome отдельно от approval.

Эти файлы находятся в архиве в чате. Они не считаются уже распакованными на Windows. Примеры synthetic; соответствие JSON Schema не доказывает подлинность отчёта, действительность permit или наличие полномочий.

## 5. Где проверяется каждое утверждение

Формат IDs/digest/Decimal — Schema + DB. Scope — FK/RLS + registry lookup/current grants. Permit — actual policy/epoch/window/budget. Native origin — actual bytes и квалификация источника/recipe. Independent signer — verified identity и separation of duties, не signed_by в JSON. MATCH — deterministic all-six/row calculation при подтверждённом scope/cutoff/completeness. Prod — separate source-specific permission и no-business-write qualification.

Source fetch не держит длинную DB transaction. Ingest транзакционно сохраняет page/events/cursor/outbox. Promotion транзакционно проверяет current head/evidence/policy и CAS. Disclosure заново проверяет текущие права. Append-only не защищает от DB superuser автоматически: audit anchors и privileged roles рассматриваются отдельно.

## 6. Уточнение по Drive

В проверенной документации changes.list page tokens не истекают. Не путать их с OAuth refresh token. Recovery tests нужны для потери/corruption/смены identity/corpus, а не для выдуманного регулярного expiry Drive cursor. Source: https://developers.google.com/workspace/drive/api/reference/rest/v3/changes/list

Доступ к revision history не гарантирован readonly/Viewer. Не повышать права и не изменять keepForever ради исторического скачивания. Сохранять только действительно полученные разрешённые current bytes в собственном private immutable store с честной basis/coverage. Исторический PASS и применимость к latest — разные состояния.
