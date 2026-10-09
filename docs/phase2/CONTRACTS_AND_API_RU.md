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

## 7. Reconciliation и purchases: offline reference modules S6b

Не tools, не миграции, не wiring в Release 1: чистые in-memory модули в `src/business_ai_gateway/phase2/`. Результаты имеют authority `EVALUATION_ONLY` и ничего не продвигают. Capability `ap.account_based` остаётся reserved и отказывается в `validation_coverage` (CAPABILITY_NOT_OPENED).

**`ap_account_strategy.py` (R2-US-031, TC091-093).**

- `qualify_strategy(name, declared: LedgerInputs, source: SourceDescription) -> StrategyResult(state, reason, strategy, missing, digest)`. Именованные стратегии: `ledger_accounting_register`, `settlements_register`; без default и fallback. State: QUALIFIED / UNQUALIFIED / ABSENT. Missing inputs (`InputName`): REGISTER, ACCOUNT_CODES, ANALYTICS_KEYS, COMPANY, CURRENCY, PERIOD (period внутри покрытого `[from, until)`).
- `make_balance_view(strategy, closing_balance) -> BalanceView`: state BALANCE_ONLY / UNQUALIFIED / ABSENT / INPUT_INVALID; aging всегда NOT_AVAILABLE.
- `compute_aging(strategy, items: tuple[OpenItem], as_of, declared_total=None) -> AgingResult`: buckets CURRENT, D1_30, D31_60, D61_90, D91_PLUS по дням после due date; точная сумма = open total; Decimal only; не `datetime`, только `date`.
- Reason codes (`Reason`): ALL_INPUTS_PRESENT, UNKNOWN_STRATEGY, INPUT_INVALID, INPUT_NOT_DECLARED, INPUT_NOT_IN_SOURCE, REGISTER_NOT_IN_SOURCE, STRATEGY_NOT_QUALIFIED, BALANCE_ONLY_NO_ITEMS, BALANCE_INVALID, ITEMS_INVALID, ITEMS_EMPTY, TOO_MANY_ITEMS, ITEM_REF_INVALID, DUPLICATE_ITEM, DATE_MISSING, DATE_INVALID, DATE_ORDER_INVALID, AMOUNT_INVALID, NEGATIVE_AMOUNT, TOTAL_MISMATCH, DECIMAL_PRECISION_EXCEEDED, AGING_COMPUTED. Любой дефект даже одной строки отклоняет весь aging; hostile input даёт код, не исключение.

**`posted_receipts.py` (R2-US-032, TC094-096).**

- Порт (read-only, `Protocol PageSource`): `fetch_page(scope: PurchaseScope, continuation_token: str | None) -> Page(documents, next_token | None, snapshot_ref, page_index=None)`. Порт может бросить что угодно (retriever отображает в SOURCE_ERROR); полноту решает retriever, не порт.
- `PostedReceiptsRetriever(source, resolver: AliasResolver).retrieve(ReceiptsRequest(scope, direction, supplier_reference, supplier_name), max_pages=MAX_PAGES(100), max_rows=MAX_ROWS(10000)) -> RetrievalResult(complete, reason, listing: PurchaseListing | None, proof: ReceiptsProof | None)`. Listing совместим с `compare_posted_purchases`.
- Исключения считаются ровно по одной причине (`ExclusionReason`, порядок первого совпадения): WRONG_COMPANY, WRONG_COUNTERPARTY, WRONG_CURRENCY, OUT_OF_PERIOD, DELETED, UNPOSTED. Direction принимается только RECEIPT.
- Reason codes (`RetrievalReason`): OK; до fetch - REQUEST_INVALID, SCOPE_INVALID, DIRECTION_NOT_RECEIPT, CURRENCY_INVALID, PERIOD_INVALID, BOUNDS_INVALID, SOURCE_INVALID, RESOLVER_INVALID, ALIAS_NOT_FOUND, ALIAS_AMBIGUOUS, ALIAS_SCOPE_VIOLATION, ALIAS_REJECTED, ALIAS_COUNTERPARTY_MISMATCH; в цепочке - SOURCE_ERROR, PAGE_INVALID, PAGE_IDENTITY_INVALID, PAGE_POSTED_FLAG_UNQUALIFIED, PAGE_ROW_INVALID, SNAPSHOT_REF_INVALID, SNAPSHOT_CHANGED, TOKEN_MISSING, TOKEN_REPEATED, TOKEN_REGRESSED, PAGE_GAP, DUPLICATE_DOCUMENT, PAGE_LIMIT_HIT, ROW_LIMIT_HIT; PROOF_UNAVAILABLE, INTERNAL_ERROR. Строка с пустой/неоднозначной identity или не-bool posted флагом отклоняет всю страницу, строка не пропускается.
- `ReceiptsProof` связывает alias (entity, namespace, value), tenant, company, counterparty, currency, период, direction, source id, snapshot ref, page tokens, счётчики страниц/строк/исключений, terminal_page_reached, complete, reason и canonical digest listing; общий digest детерминирован и меняется при любом изменении входа.
- `assess_receipts(native: PurchaseListing, result: RetrievalResult) -> ReceiptsAssessment`: три независимых вердикта. Completeness COMPLETE / INCOMPLETE (с reason, повторно проверяет digest proof); correctness MATCH / MISMATCH / INCONCLUSIVE из `compare_posted_purchases` (неквалифицированный native: `NATIVE_LISTING_UNQUALIFIED`); discrepancy NONE / LISTED / NOT_ASSESSABLE со списком расхождений по doc_ref/field. Остаточный риск: источник, молча пропустивший страницу при валидном токене, не обнаруживается без `page_index`.

**NOT_RUN после S6b.** Реальный 1C read grant для 818HA; реальный постраничный источник (OData или аналог) и его page-size/token поведение; реальные MOLDRETAIL posted receipts и native журнал (UAT-U02); аттестация бухгалтера (G3); реальные байты native отчётов (521.1, журнал, AP aging); валидация маппинга accounting register 818HA (открытый operator finding: settlements register отсутствует); открытие `ap.account_based`; продвижение выше EVALUATION_ONLY; wiring в runtime/server/Release 1; persistence runs/proofs; Release 1 regression; GitHub CI; mutation runs. Тесты на фикстурах доказывают логику только на этих фикстурах, не поведение реальной 818HA.
