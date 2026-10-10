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

## 8. Drive: offline port, consent и cursor (S7)

Не tools, не миграции, не wiring в Release 1 и не открытие Drive capability: чистые in-memory модули в `src/business_ai_gateway/phase2/`, без httpx/requests/socket/DB, без `os.environ` и file I/O, без импорта `drive_http.py`, Release 1 и PDCC (AST-проверка `test_s7_boundaries.py`). Проверено только против scripted fake (IMPLEMENTED_UNVERIFIED); реальное поведение Google и G4 не доказаны.

**Порт `drive_port.py` (read-only).** `Protocol DrivePort` ровно с четырьмя async-методами; методов записи, permission и keepForever нет по построению. Все методы первыми принимают `DrivePortIdentity(namespace, tenant, connection_id)` и `scope_epoch`:

- `get_start_page_token(identity, scope_epoch) -> StartToken`
- `list_changes(identity, scope_epoch, page_token) -> ChangesPage(changes, next_page_token | None, new_start_page_token | None)`: ровно один из двух токенов (иначе `PAGE_CONTINUATION_XOR_NEW_START_REQUIRED`); `to_drive_page(...)` адаптирует страницу к существующему `DriveChangeProjector`.
- `get_file_meta(identity, scope_epoch, file_id) -> FileMeta(file_id, name, mime_type, parents, trashed, drive_id, shortcut_target, head_revision_id)`
- `list_revisions(identity, scope_epoch, file_id) -> tuple[RevisionMeta, ...]`

Ошибки порта - только `DrivePortError` с фиксированным `DriveErrorCode`: AUTH_REQUIRED, INVALID_GRANT, FORBIDDEN_HISTORY, NOT_FOUND, RATE_LIMITED, TRANSIENT, SCOPE_EPOCH_STALE; текст провайдера не передаётся. Namespace - `account:<id>` или `drive:<id>`; один raw file id в двух namespaces - два разных объекта. Id, токены, revision ids байт-точные (без trim/case-fold); значения только exact-type (`str`/`int`/`datetime`-подклассы отказываются); timestamp только timezone-aware, приводится к UTC. Полноту решает вызывающий модуль, не порт. `drive_fake.py` (`FakeDrivePort`) - scripted fake: страницы, токены, метаданные с parents, revisions, forced errors (`invalid_grant`, 403 history forbidden, 404, 429), call log, hook после N вызовов.

**Consent `drive_oauth.py`.** `ConsentManager` с `ConsentState`: NEW, CONSENT_PENDING, GRANTED, REVOKED, AUTH_REQUIRED; методы `begin_consent`, `complete_consent`, `revoke`, `mark_auth_required`, `snapshot`, `state_of`, `scope_epoch`, `is_authorized`, `consent_digest`. `state` одноразовый (replay отказан), PKCE-style verifier, ограниченный срок pending на injected clock, callback другого (tenant, connection) отказан. Токены живут только в `FakeTokenStore` (ключ - ERP_MCP connection id; строки с префиксом `FAKE-`; ничего из PDCC/Release 1 не принимается), не логируются, не попадают в digest, `repr`/`str`/ошибки. Revoke удаляет токены, увеличивает scope epoch и инвалидирует cursors старой epoch (старые grants не воскресают). Коды `ConsentCode`: OK, INPUT_INVALID, IDENTITY_INVALID, SCOPE_REFUSED, GRANT_NOT_SUBSET, VERIFIER_INVALID, VERIFIER_MISMATCH, CODE_INVALID, STATE_INVALID, STATE_UNKNOWN, STATE_REPLAYED, STATE_EXPIRED, STATE_SOURCE_INVALID, TOKEN_INVALID, ALREADY_GRANTED, NOT_GRANTED, CLOCK_INVALID, EPOCH_EXHAUSTED, CAPACITY.

**Scope и membership `drive_scope.py`.** `evaluate_scopes(scope_names, risk_labels) -> ScopeEvaluation` даёт claim `ScopeClaim` (NARROW_FILE_SCOPE / READONLY_BROAD / BROAD) и `Isolation` (FILE_GRANT_ONLY / APPLICATION_FILTER_ONLY / FOLDER_ISOLATED); broad grant никогда не называется folder isolation (`check_isolation_label` отказывает `ISOLATION_LABEL_REFUSED`), для продолжения нужна риск-метка `BROAD_ACCEPTED` (`BROAD_REQUIRES_RISK_LABEL`). `ScopeCode`: OK, SCOPE_NAMES_INVALID, SCOPE_NAME_INVALID, SCOPE_UNKNOWN, SCOPE_SET_EMPTY, SCOPE_SET_TOO_LARGE, RISK_LABELS_INVALID, RISK_LABEL_UNKNOWN, BROAD_REQUIRES_RISK_LABEL, ISOLATION_LABEL_REFUSED, INPUT_INVALID. `resolve_membership(port, identity, scope_epoch, corpus, file_id, ...)` идёт по parent chain до объявленных roots (ограничены глубина и бюджет вызовов, cycle-safe); `MembershipStatus` IN_SCOPE / NOT_IN_SCOPE, `MembershipCode`: IN_CORPUS, INPUT_INVALID, EMPTY_CORPUS, NAMESPACE_MISMATCH, FILE_UNRESOLVED, PARENT_UNRESOLVED, OUTSIDE_CORPUS, DEPTH_EXCEEDED, BUDGET_EXCEEDED, CYCLE, SHORTCUT_NOT_PROOF, TRASHED, PORT_REFUSED. `prove_scoped_read` и `observe_new_child_access` возвращают `AccessProof` PROVEN / NOT_PROVEN / DENIED только из scripted observation (с `ProofBasis`); доступ к новым children не предполагается (G4 NOT_RUN).

**Baseline и cursor `drive_baseline.py`, `drive_cursor.py`.** Порядок фиксирован и проверяется `check_baseline_order(call_log)`: getStartPageToken -> persist token (CAS с fence) -> baseline listing -> catch-up от записанного token -> terminal `newStartPageToken` -> LIVE. `CursorState`: UNINITIALIZED, BASELINING, CATCHING_UP, LIVE, GAP, AUTH_REQUIRED, RESNAPSHOT_REQUIRED. `DriveBaseline.run` возвращает `BaselineOutcome`: LIVE, LIMIT_REACHED, BLOCKED, GAP, RESNAPSHOT_REQUIRED, AUTH_REQUIRED, LEASE_LOST, CONFLICT, RETRYABLE, REFUSED; режимы `DriveRunMode`: INCREMENTAL, RESNAPSHOT_START, RESNAPSHOT_CONTINUE. Paging ограничен (`BaselineLimits`); достижение лимита - не LIVE. Page и cursor коммитятся вместе через существующий cursor CAS port (`DriveCursorStore.commit`) с lease fence; stale fence ничего не коммитит; повтор закоммиченной страницы идемпотентен, тот же id с другим digest - конфликт. Fail-closed `CursorReason` (через `ResnapshotTracker`): CURSOR_MISSING, CURSOR_EMPTY, CURSOR_CORRUPT, IDENTITY_CHANGED, CORPUS_CHANGED, SCOPE_EPOCH_CHANGED, TOKEN_NOT_FOUND, TOKEN_REPEATED, TOKEN_REGRESSED, TOKEN_MISSING, UNKNOWN_CHANGE_KIND, MEMBERSHIP_UNVERIFIED, PAGE_INVALID, AUTH_INVALID_GRANT, AUTH_REQUIRED, INCREMENTAL_BLOCKED, PAGE_LIMIT, ROW_LIMIT, START_TOKEN_INVALID, START_TOKEN_ORDER, INVALID_REQUEST, INTERNAL, LEASE_LOST, SCOPE_REVOKED, STALE_CURSOR, COMMIT_CONFLICT, INVALID_BATCH, INVALID_TRANSITION, RATE_LIMITED, TRANSIENT, PORT_UNEXPECTED, PORT_FAILURE. Cursor ключи, кандидаты и dedup keys несут namespace. Как в разделе 6, регулярный expiry Drive cursor не выдумывается.

**Revisions и membership `drive_revisions.py`, `drive_membership.py`.** `RevisionTracker.observe` / `record_attested` / `verdict` / `latest_verdict`: `ObservationOutcome` FIRST_SEEN, NEW_REVISION, DUPLICATE, OUT_OF_ORDER, REFUSED; `RevisionState` UNATTESTED, PASS_CURRENT, PASS_HISTORICAL, UNKNOWN; новая revision - новый UNATTESTED, прежний PASS становится PASS_HISTORICAL и не считается latest (сама attestation остаётся в `evidence_attestation.py`). `list_history(port, ...)` возвращает `HistoryStatus` AVAILABLE / HISTORY_UNAVAILABLE / NOT_FOUND / CHECK_FAILED и `HistoryCoverage` LISTED / CURRENT_ONLY / NONE; forbidden history даёт HISTORY_UNAVAILABLE + CURRENT_ONLY, права не повышаются, keepForever не вызывается. `MembershipChecker.check` / `authorize_disclosure` / `recheck_all` / `prepare_page` / `advance_epoch`: `MembershipVerdict` IN_SCOPE, SCOPE_ESCAPE_DENIED, NOT_IN_SCOPE, REMOVED, CHECK_FAILED; `PageStatus` PREPARED / REFUSED. Rename сохраняет identity, move внутри corpus принимается после повторного разрешения parent chain, move наружу, shortcut на внешнюю цель и неразрешённый parent - SCOPE_ESCAPE_DENIED без раскрытия и кандидата; удаление - tombstone без замены по имени/размеру/hash; revoke перепроверяет cached membership до disclosure.

**Auth и hints `drive_auth_state.py`.** `DriveAuthHealth` с `AuthState` HEALTHY / AUTH_REQUIRED и `AuthCause` INVALID_GRANT / CONSENT_REVOKED / ACCESS_REJECTED. `TokenStatus` VALID / EXPIRED_REFRESHABLE / MISSING: истёкший, но обновляемый token обновляется и работа продолжается; `invalid_grant` и revoke - AUTH_REQUIRED, пауза через `SourceStateMachine`, ровно один alert на переход (`AuthAlert`, без токена и текста провайдера) в `AlertSink`, `AuthGuardedDrivePort` блокирует все вызовы fail-closed, cursor не двигается (`run_poll` читает `committed_token`). `reconsent` -> `ReconsentResult` RECOVERED, NOT_REQUIRED, EPOCH_NOT_NEW, NO_CONSENT, EPOCH_MISMATCH, SCOPE_CHECK_FAILED, QUARANTINED, SEAM_FAULT (нужна новая scope epoch и свежая проверка scope). `HintIntake.accept_hint` -> `HintResult` ACCEPTED_NEW_JOB, ACCEPTED_COLLAPSED, REJECTED_INVALID, REJECTED_FOREIGN, REJECTED_STALE, REJECTED_PAUSED: hint принимается только с совпадающими channel/resource/token владельца, только планирует `PollJob`, идемпотентен, не несёт данных и не двигает cursor. `run_poll` -> `PollStatus` COMPLETE, AUTH_REQUIRED, NO_CURSOR, PAGE_LIMIT, COMMIT_FAILED, PORT_ERROR; polling полон без hints и без watch.

NOT_RUN: реальная регистрация OAuth client и consent screen, реальные tokens и обмен/refresh, реальная папка/shared drive и поведение narrow scope на новых children (G4), реальные quotas/429/403, реальные changes.list токены, watch channels/webhook, revision history для Viewer, доставка alert, PostgreSQL для S7, wiring в runtime, CI, mutation runs. Release 2 остаётся NO-GO, G1 и G4 NOT PASSED.
