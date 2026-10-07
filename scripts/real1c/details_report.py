"""Per-test HTML report: for every case, what was asked, what was sent, what came back and why that outcome is right.

Pure builder (no I/O).  Everything shown has been through redact_text; no business values are included (calls carry
key names, row counts and typed codes only).
"""

from __future__ import annotations

import html
import json
from collections import Counter
from typing import Any

from .catalog import Catalog
from .disposition import DISPOSITIONS
from .report import _CSS, _badge
from .sanitize import redact_text

KIND_ORDER = ("ST", "AX", "RL2", "ACL", "SYS", "NR", "INV", "RULE")
KIND_TITLE = {
    "en": {"ST": "Catalogue stories (ST)", "AX": "Additional accounting scenarios (AX)", "RL2": "Raw-data fidelity checks (RL2)",
           "ACL": "Access-control checks (ACL)", "SYS": "System and product checks (SYS)",
           "NR": "Native reconciliation cases (NR)", "INV": "Supplier invoices (INV)", "RULE": "Month-close rules (RULE)"},
    "ru": {"ST": "Истории каталога (ST)", "AX": "Дополнительные бухгалтерские сценарии (AX)", "RL2": "Проверки точности сырых данных (RL2)",
           "ACL": "Проверки прав доступа (ACL)", "SYS": "Системные и продуктовые проверки (SYS)",
           "NR": "Нативная сверка (NR)", "INV": "Счета поставщиков (INV)", "RULE": "Правила закрытия месяца (RULE)"},
}

# Why each outcome is the right one: reason_code -> text per language.
WHY: dict[str, dict[str, str]] = {
    "profile_gate_refusal": {
        "en": "The semantic profile of this real source has not been validated by genuine native 1C reports. The gateway must "
              "therefore refuse to serve accounting numbers and answer with the typed code SEMANTIC_PROFILE_UNVALIDATED. It did, "
              "and no figure was returned, so a refusal is the correct result; a PASS here would mean unvalidated numbers were served.",
        "ru": "Семантический профиль этого реального источника не валидирован настоящими нативными отчётами 1C. Шлюз обязан не "
              "выдавать бухгалтерские цифры и ответить типизированным кодом SEMANTIC_PROFILE_UNVALIDATED. Так и произошло, цифры не "
              "возвращены, поэтому отказ — правильный результат; PASS означал бы, что невалидированные цифры были выданы."},
    "oracle_match": {
        "en": "The observed facts equal the independent oracle named for this test (audit rows, control-plane rows or a read-only "
              "COM query of the clone), and every condition of the acceptance rule held, so the test passes.",
        "ru": "Наблюдаемые факты совпали с независимым оракулом этого теста (строки аудита, строки control plane или read-only "
              "COM-запрос к клону), и все условия правила приёмки выполнены, поэтому тест пройден."},
    "oracle_mismatch": {
        "en": "At least one condition of the acceptance rule did not hold when compared with the oracle. This is a real difference "
              "found in the product or the catalogue, so the honest result is FINDING with the failed condition listed below.",
        "ru": "Хотя бы одно условие правила приёмки не выполнилось при сравнении с оракулом. Это реальное расхождение продукта или "
              "каталога, поэтому честный результат — FINDING; невыполненное условие указано ниже."},
    "capability_absent_confirmed": {
        "en": "The capability was searched for in the whole product surface (public MCP tools and descriptions, admin API routes, CLI "
              "commands) and is not there. Reporting CAPABILITY_UNSUPPORTED is the truthful statement; inventing a pass would hide the gap.",
        "ru": "Возможность искали во всей поверхности продукта (публичные MCP-инструменты и описания, маршруты admin API, команды CLI) "
              "— её нет. Правдивый результат — CAPABILITY_UNSUPPORTED; выдумать PASS значило бы скрыть пробел."},
    "capability_present_but_catalogued_unsupported": {
        "en": "The catalogue marks this capability as unsupported, but the lane exercised it on the real source and it works. The "
              "catalogue expectation is wrong, which is a FINDING (a catalogue correction), not a product defect.",
        "ru": "Каталог помечает возможность как неподдерживаемую, но линия проверила её на реальном источнике и она работает. "
              "Ошибочно ожидание каталога — это FINDING (поправка каталога), а не дефект продукта."},
    "capability_not_confirmed": {
        "en": "The probe did not produce enough evidence to say whether the capability exists, so the result stays INCONCLUSIVE.",
        "ru": "Проверка не дала достаточных данных, есть ли возможность, поэтому результат остаётся INCONCLUSIVE."},
    "evidence_required_observed": {
        "en": "The answer depends on external evidence (a hashed document, bank statement or declaration). The evidence plane "
              "refused with a typed status instead of inventing a value, so EVIDENCE_REQUIRED is the correct result.",
        "ru": "Ответ зависит от внешнего доказательства (документ с хешем, банковская выписка, декларация). Контур доказательств "
              "ответил типизированным отказом вместо выдуманного значения, поэтому EVIDENCE_REQUIRED — правильный результат."},
    "data_without_evidence": {
        "en": "Data came back although the evidence is missing. That would be a bypass of the evidence gate, so it is a FINDING.",
        "ru": "Данные пришли, хотя доказательств нет. Это обход контура доказательств, поэтому FINDING."},
    "profile_bypass": {
        "en": "Numbers were served although the semantic profile is not validated. That is a bypass of the profile gate: FINDING.",
        "ru": "Цифры выданы, хотя семантический профиль не валидирован. Это обход ворот профиля: FINDING."},
    "write_refused": {
        "en": "The request would change data. The product has no mutating tool, the write-shaped inputs were rejected with typed "
              "errors, the loopback proxies saw only GET/HEAD, and the database fingerprint did not change. REFUSED-WRITE is correct.",
        "ru": "Запрос изменил бы данные. В продукте нет изменяющих инструментов, запросы в форме записи отклонены типизированными "
              "ошибками, прокси видели только GET/HEAD, отпечаток базы не изменился. REFUSED-WRITE — правильный результат."},
    "write_effect_detected": {
        "en": "A change to the database or a write verb towards 1C was observed. That is the most serious outcome: FINDING.",
        "ru": "Зафиксировано изменение базы или команда записи в сторону 1C. Это самый серьёзный исход: FINDING."},
    "profile_gate_not_observed": {
        "en": "The lane could not exercise a semantic tool for this story, so the profile gate was not observed: INCONCLUSIVE.",
        "ru": "Для этой истории линия не смогла вызвать семантический инструмент, ворота профиля не наблюдались: INCONCLUSIVE."},
    "evidence_gate_not_observed": {
        "en": "The evidence gate was not observed: INCONCLUSIVE.", "ru": "Ворота доказательств не наблюдались: INCONCLUSIVE."},
    "write_outcome_not_observed": {
        "en": "The write refusal was not observed: INCONCLUSIVE.", "ru": "Отказ записи не наблюдался: INCONCLUSIVE."},
    "oracle_not_compared": {
        "en": "No comparison with the oracle was possible: INCONCLUSIVE.", "ru": "Сравнение с оракулом невозможно: INCONCLUSIVE."},
    "truncated": {
        "en": "The answer was truncated, so it cannot be compared completely: INCONCLUSIVE.",
        "ru": "Ответ усечён и не может быть сравнён полностью: INCONCLUSIVE."},
    "error": {
        "en": "The test could not produce a typed answer (transport failure or evaluation defect). ERROR is reported instead of "
              "guessing a verdict.", "ru": "Тест не получил типизированного ответа (сбой транспорта или дефект оценки). Вместо "
              "угадывания вердикта фиксируется ERROR."},
    "com_agrees_native_ui_report_required": {
        "en": "The read-only COM recomputation on the clone agrees with the candidate assertion. COM is comparison evidence only: "
              "the genuine native 1C UI report is still owed by the owner, so the case cannot be PASS and stays EVIDENCE_REQUIRED.",
        "ru": "Read-only пересчёт через COM на клоне совпал с кандидатным утверждением. COM — только сравнительное доказательство: "
              "настоящий нативный отчёт интерфейса 1C ещё предстоит предоставить владельцу, поэтому PASS невозможен — EVIDENCE_REQUIRED."},
    "com_disagrees_with_candidate_assertion": {
        "en": "The COM recomputation differs from the candidate assertion, so the assertion (or the data) is wrong: FINDING.",
        "ru": "Пересчёт через COM расходится с кандидатным утверждением — неверно либо утверждение, либо данные: FINDING."},
    "not_computable_by_com": {
        "en": "This assertion has no COM-computable form (it needs a native month-close view), so it is INCONCLUSIVE until the owner supplies the native report.",
        "ru": "У этого утверждения нет формы, вычислимой через COM (нужен нативный вид закрытия месяца), поэтому INCONCLUSIVE до отчёта владельца."},
    "com_consistent_native_ui_report_required": {
        "en": "The invoice is in the clone as recorded (presence, total and date as expected by the prior observation). That is consistent, "
              "but only the native UI report plus the PDF can confirm it, so EVIDENCE_REQUIRED.",
        "ru": "Счёт в клоне соответствует записи (наличие, сумма и дата как в предыдущем наблюдении). Это согласуется, но подтвердить "
              "может только нативный отчёт и PDF, поэтому EVIDENCE_REQUIRED."},
    "com_differs_from_recorded_invoice_state": {
        "en": "The clone differs from the recorded state of this invoice (presence, total or date): FINDING.",
        "ru": "Клон расходится с записанным состоянием счёта (наличие, сумма или дата): FINDING."},
    "head_supported": {"en": "HEAD $metadata is accepted by the real publication.", "ru": "Реальная публикация принимает HEAD $metadata."},
    "head_metadata_rejected_by_1c": {
        "en": "The real 1C publication answers HEAD $metadata with 405 while the gateway health check relies on HEAD. This is a "
              "real compatibility gap of the product against the real platform: FINDING. The lane keeps a HEAD-to-GET shim only so the "
              "other tests can run.",
        "ru": "Реальная публикация 1C отвечает на HEAD $metadata кодом 405, а проверка здоровья шлюза опирается на HEAD. Это реальный "
              "разрыв совместимости продукта с настоящей платформой: FINDING. Подмена HEAD→GET в линии нужна лишь чтобы шли остальные тесты."},
    "all_calls_audited": {"en": "Every rejected call left exactly one audit row.", "ru": "Каждый отклонённый вызов оставил ровно одну запись аудита."},
    "malformed_calls_not_audited": {
        "en": "Some malformed calls were rejected before the audit write and left no audit row, although the story requires one row "
              "per call: FINDING.", "ru": "Часть некорректных вызовов отклонена до записи аудита и не оставила строки, хотя история "
              "требует одну строку на вызов: FINDING."},
    "identity_privilege_reported": {"en": "The product reports the privilege of its upstream identity.",
                                    "ru": "Продукт сообщает уровень привилегий своей учётной записи в 1C."},
    "identity_privilege_not_reported": {
        "en": "Neither the capabilities, the health nor the status payload tells an operator whether the upstream 1C identity can "
              "write. The product therefore cannot flag a read/write-capable identity: FINDING.",
        "ru": "Ни capabilities, ни health, ни status не говорят оператору, может ли учётная запись 1C писать. Продукт не способен "
              "пометить учётную запись с правом записи: FINDING."},
    "paging_supported": {"en": "companies_list supports paging.", "ru": "companies_list поддерживает постраничность."},
    "no_paging_arguments": {
        "en": "companies_list returns the whole visible list in one response and has no paging arguments, which does not scale "
              "to large portfolios: FINDING.", "ru": "companies_list возвращает весь видимый список одним ответом и не имеет "
              "параметров постраничности — это не масштабируется на большие портфели: FINDING."},
    "literal_secret_refused_typed": {"en": "A literal credential was refused with a typed validation error and nothing was stored or echoed.",
                                     "ru": "Литеральный пароль отклонён типизированной ошибкой валидации, ничего не сохранено и не показано."},
    "literal_secret_refused_untyped": {
        "en": "The literal credential was refused safely (no row, no echo) but as an HTTP 500 dependency failure instead of a typed "
              "validation error, so the operator gets no reason: FINDING.",
        "ru": "Литеральный пароль отклонён безопасно (нет строки, нет эха), но как сбой зависимости HTTP 500, а не типизированная "
              "ошибка валидации — оператор не получает причину: FINDING."},
    "literal_secret_accepted": {"en": "A literal credential was accepted or echoed: FINDING.",
                                "ru": "Литеральный пароль принят или показан: FINDING."},
    "admin_endpoints_ok": {"en": "All Admin Control Center read endpoints answered 200 for the real source.",
                           "ru": "Все read-эндпоинты Admin Control Center ответили 200 для реального источника."},
    "admin_endpoint_failed": {"en": "An Admin endpoint did not answer 200: FINDING.", "ru": "Эндпоинт Admin не ответил 200: FINDING."},
    "validation_refused": {
        "en": "Profile validation without genuine native evidence was refused and the profile stayed DRAFT, as required. The API "
              "answers a generic INVALID_REQUEST without naming the reason.",
        "ru": "Валидация профиля без настоящих нативных доказательств отклонена, профиль остался DRAFT, как требуется. API отвечает "
              "общим INVALID_REQUEST, не называя причину."},
    "validated_without_native_evidence": {"en": "The profile was validated or the refusal was not the expected one: FINDING.",
                                          "ru": "Профиль провалидирован или отказ не тот, что ожидался: FINDING."},
}
WHY_DEFAULT = {"en": "The outcome follows mechanically from the observations below and the disposition rules.",
               "ru": "Исход механически следует из наблюдений ниже и правил определения решения."}

DISPOSITION_MEANING = {
    "en": {"PASS": "passed", "FINDING": "a real difference or defect found", "INCONCLUSIVE": "not enough evidence to decide",
           "EVIDENCE_REQUIRED": "external or native evidence is owed", "CAPABILITY_UNSUPPORTED": "the product does not have this capability",
           "SEMANTIC_PROFILE_UNVALIDATED": "numbers are correctly withheld until the profile is validated",
           "REFUSED-WRITE": "a write was correctly refused", "ERROR": "the test could not run to a typed answer"},
    "ru": {"PASS": "пройден", "FINDING": "найдено реальное расхождение или дефект", "INCONCLUSIVE": "данных для решения недостаточно",
           "EVIDENCE_REQUIRED": "нужны внешние или нативные доказательства", "CAPABILITY_UNSUPPORTED": "в продукте нет такой возможности",
           "SEMANTIC_PROFILE_UNVALIDATED": "цифры верно не выдаются, пока профиль не валидирован",
           "REFUSED-WRITE": "запись верно отклонена", "ERROR": "тест не получил типизированного ответа"},
}

L: dict[str, dict[str, str]] = {
    "en": {"title": "ERP_MCP real 1C 818HA L2: every test in detail", "lead": "For each test: the question, the request that was sent, "
           "what came back, and why that result is the right one.", "back": "Summary report", "filter": "Show", "all": "all outcomes",
           "question": "Question (business scenario)", "expected": "Expected by the catalogue", "negative": "Negative semantics",
           "sent": "Request that was sent", "received": "What was received", "why": "Why this result is correct",
           "obs": "Observations", "owner": "Owner action", "oracle": "Oracle", "evidence": "Evidence classes", "gaps": "Requirement gaps",
           "principal": "Principal", "tool": "Tool", "args": "Arguments", "answer": "Answer", "audit": "Audit row", "shown": "shown",
           "of": "of", "calls": "calls", "no_request": "No request", "query": "COM query on the clone", "more": "more",
           "inv_note": "Supplier names and numbers are not shown, only the short hash of the number.", "git": "Git SHA",
           "generated": "Generated", "kind": "Kind", "meaning": "Meaning", "reading": "How to read the cards",
           "reading_text": "An MCP client only ever sees a generic tool error for a refused call, so an answer shown as ERROR is expected "
           "for refusals: the typed reason (for example SEMANTIC_PROFILE_UNVALIDATED or AccessDenied) is read from the audit row printed "
           "under it. Company identifiers appear as short hashes. Exact monetary figures are masked as <amount> in this public report; "
           "equality with the oracle is stated by the outcome, and the exact figures are kept in a private evidence file outside Git."},
    "ru": {"title": "ERP_MCP real 1C 818HA L2: каждый тест подробно", "lead": "По каждому тесту: вопрос, отправленный запрос, "
           "что получено и почему этот результат правильный.", "back": "Сводный отчёт", "filter": "Показать", "all": "все исходы",
           "question": "Вопрос (бизнес-сценарий)", "expected": "Ожидание каталога", "negative": "Негативная семантика",
           "sent": "Отправленный запрос", "received": "Что получено", "why": "Почему результат правильный",
           "obs": "Наблюдения", "owner": "Действие владельца", "oracle": "Оракул", "evidence": "Классы доказательств", "gaps": "Пробелы требований",
           "principal": "Субъект", "tool": "Инструмент", "args": "Аргументы", "answer": "Ответ", "audit": "Строка аудита", "shown": "показано",
           "of": "из", "calls": "вызовов", "no_request": "Запроса нет", "query": "COM-запрос к клону", "more": "ещё",
           "inv_note": "Названия и номера поставщиков не показываются, только короткий хеш номера.", "git": "Git SHA",
           "generated": "Сформировано", "kind": "Тип", "meaning": "Значение", "reading": "Как читать карточки",
           "reading_text": "MCP-клиент на отказ всегда видит общую ошибку инструмента, поэтому ответ «ERROR» для отказов ожидаем: типизированная "
           "причина (например SEMANTIC_PROFILE_UNVALIDATED или AccessDenied) берётся из строки аудита под ним. Идентификаторы компаний "
           "показаны короткими хешами. Точные денежные суммы в этом публичном отчёте скрыты как <amount>; совпадение с оракулом отражено "
           "исходом, а точные значения хранятся в приватном файле вне Git."},
}

_EXTRA_CSS = """
.card{border:1px solid var(--line);border-radius:6px;margin:8px 0;background:var(--bg)}
.card>summary{cursor:pointer;padding:8px 12px;display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;background:var(--card)}
.card>summary .id{font-weight:700;font-family:ui-monospace,monospace}
.card .body{padding:4px 14px 12px}
.card h4{margin:12px 0 4px;font-size:13px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
pre{background:var(--card);border:1px solid var(--line);padding:6px 8px;overflow-x:auto;white-space:pre-wrap;word-break:break-word;margin:4px 0}
.why{border-left:4px solid var(--ev);padding:4px 10px;background:var(--card)}
.tbl-wrap{overflow-x:auto}
select{padding:3px 6px}
"""
_JS = """
(function(){var s=document.getElementById('flt');if(!s)return;s.addEventListener('change',function(){
var v=s.value;document.querySelectorAll('details.card').forEach(function(d){d.style.display=(v===''||d.dataset.d===v)?'':'none';});});})();
"""


def _e(value: Any) -> str:
    return html.escape(redact_text(str(value)), quote=True)


def _json(value: Any) -> str:
    return _e(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=None))


def _why(result: dict[str, Any], lang: str) -> str:
    text = WHY.get(result.get("reason_code", ""), WHY_DEFAULT)[lang]
    meaning = DISPOSITION_MEANING[lang].get(result["disposition"], "")
    return f"<p><strong>{_e(result['disposition'])}</strong> ({_e(meaning)}). {_e(text)}</p>"


def _calls_html(result: dict[str, Any], t: dict[str, str]) -> str:
    calls = result.get("calls") or []
    parts = []
    note = result.get("channel_note")
    if note:
        parts.append(f"<p>{_e(note)}</p>")
    for call in calls:
        audit = f"{call.get('audit_outcome')}/{call.get('detail_code')}" if (call.get("audit_outcome") or call.get("detail_code")) else "-"
        status = "ERROR" if call.get("is_error") else "OK"
        parts.append(
            f"<table><tbody><tr><th>{t['principal']}</th><td>{_e(call['principal'])}</td><th>{t['tool']}</th><td><code>{_e(call['tool'])}</code></td></tr>"
            f"<tr><th>{t['args']}</th><td colspan=3><pre>{_json(call['arguments'])}</pre></td></tr>"
            f"<tr><th>{t['answer']}</th><td colspan=3>{status}{' (transport failure)' if call.get('transport_error') else ''}"
            f"<pre>{_json(call.get('response') or {})}</pre></td></tr>"
            f"<tr><th>{t['audit']}</th><td colspan=3>{_e(audit)}; items={_e(call.get('returned_items'))}</td></tr></tbody></table>")
    if result.get("calls_total", 0) > len(calls):
        parts.append(f"<p class='muted'>{t['shown']} {len(calls)} {t['of']} {result['calls_total']} {t['calls']}</p>")
    for q in result.get("queries") or []:
        parts.append(f"<p class='muted'>{t['query']}</p><pre>{_e(q['text'])}</pre>")
    if not parts:
        parts.append(f"<p class='muted'>{t['no_request']}</p>")
    return "".join(parts)


def _card(result: dict[str, Any], story: Any, lang: str) -> str:
    t = L[lang]
    obs = "".join(f"<tr><td>{_e(o['probe'])}</td><td>{_e(o['outcome'])}</td><td>{_e(o['detail'])}</td></tr>" for o in result["observations"])
    supp = "".join(f"<tr><td>{_e(o['probe'])}</td><td>{_e(o['outcome'])}</td><td>{_e(o['detail'])}</td></tr>"
                   for o in result.get("supplementary") or [])
    question = result.get("question") or result["title"]
    expected = result.get("expected") or ""
    negative = result.get("negative") or ""
    head = f"{t['evidence']}: {_e(', '.join(result['evidence_classes']))} | {t['oracle']}: {_e(result['oracle'])}"
    extras = ""
    if expected and expected != "-":
        extras += f"<h4>{t['expected']}</h4><p>{_e(expected)}</p>"
    if negative and negative != "-":
        extras += f"<h4>{t['negative']}</h4><p>{_e(negative)}</p>"
    owner = f"<h4>{t['owner']}</h4><p>{_e(result['owner_action'])}</p>" if result.get("owner_action") else ""
    gaps = f"<p class='muted'>{t['gaps']}: {_e(', '.join(result['req_gap_refs']))}</p>" if result.get("req_gap_refs") else ""
    meta = ""
    if story is not None:
        meta = f"<span class='muted'>{_e(story.persona)} · {_e(story.priority)} · {_e(story.catalogue_class)}</span>"
    return (f'<details class="card" id="c-{_e(result["case_id"])}" data-d="{_e(result["disposition"])}"><summary>'
            f'<span class="id">{_e(result["case_id"])}</span>{_badge(result["disposition"])}<span>{_e(result["title"])}</span>{meta}</summary>'
            f'<div class="body"><h4>{t["question"]}</h4><p>{_e(question)}</p>{extras}'
            f'<h4>{t["sent"]}</h4>{_calls_html(result, t)}'
            f'<h4>{t["received"]}</h4><div class="tbl-wrap"><table><tbody>{obs}</tbody></table></div>'
            f'{"<div class=tbl-wrap><table><tbody>" + supp + "</tbody></table></div>" if supp else ""}'
            f'<h4>{t["why"]}</h4><div class="why">{_why(result, lang)}</div>'
            f'<p class="muted">{head}</p>{owner}{gaps}</div></details>')


def _compact_row(result: dict[str, Any], lang: str) -> str:
    queries = " | ".join(q["text"] for q in (result.get("queries") or [])[:2])
    obs = result["observations"][0] if result["observations"] else {"probe": "", "outcome": "", "detail": ""}
    why = WHY.get(result.get("reason_code", ""), WHY_DEFAULT)[lang]
    return (f"<tr><td>{_e(result['case_id'])}</td><td>{_badge(result['disposition'])}</td><td>{_e(result['title'])}</td>"
            f"<td><code>{_e(queries) or '-'}</code></td><td>{_e(obs['outcome'])}: {_e(obs['detail'])}</td><td>{_e(why)}</td></tr>")


def build_details(results: list[dict[str, Any]], catalogue: Catalog, git_sha: str, generated_at: str, *, lang: str,
                  summary_href: str) -> str:
    if lang not in L:
        raise ValueError(f"unsupported lang: {lang!r}")
    t = L[lang]
    stories = {s.id: s for s in catalogue.stories}
    by_kind: dict[str, list[dict[str, Any]]] = {k: [] for k in KIND_ORDER}
    for r in results:
        by_kind.setdefault(r["kind"], []).append(r)
    counts = Counter(r["disposition"] for r in results)
    options = f'<option value="">{t["all"]}</option>' + "".join(
        f'<option value="{d}">{d} ({counts.get(d, 0)})</option>' for d in DISPOSITIONS if counts.get(d, 0))
    legend = "".join(f"<tr><td>{_badge(d)}</td><td>{_e(DISPOSITION_MEANING[lang][d])}</td></tr>" for d in DISPOSITIONS)
    sections = []
    for kind in KIND_ORDER:
        items = by_kind.get(kind) or []
        if not items:
            continue
        if kind in ("INV", "RULE"):
            head = "".join(f"<th>{h}</th>" for h in ("ID", "", t["kind"], t["query"], t["received"], t["why"]))
            rows = "".join(_compact_row(r, lang) for r in items)
            note = f"<p class='muted'>{t['inv_note']}</p>" if kind == "INV" else ""
            sections.append(f"<section><h2>{_e(KIND_TITLE[lang][kind])} ({len(items)})</h2>{note}"
                            f"<div class='tbl-wrap'><table><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div></section>")
        else:
            cards = "".join(_card(r, stories.get(r["case_id"]), lang) for r in items)
            sections.append(f"<section><h2>{_e(KIND_TITLE[lang][kind])} ({len(items)})</h2>{cards}</section>")
    return (
        f'<!DOCTYPE html>\n<html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(t['title'])}</title><style>{_CSS}{_EXTRA_CSS}</style></head><body>"
        f'<header><h1>{_e(t["title"])}</h1><div class="muted">{_e(t["lead"])}</div>'
        f'<div class="muted">{_e(t["git"])}: <code>{_e(git_sha)}</code> | {_e(t["generated"])}: {_e(generated_at)} | '
        f'<a href="{_e(summary_href)}">{_e(t["back"])}</a></div></header><main>'
        f'<section><h2>{_e(t["reading"])}</h2><p>{_e(t["reading_text"])}</p><h2>{_e(t["meaning"])}</h2><table><tbody>{legend}</tbody></table>'
        f'<p><label>{_e(t["filter"])}: <select id="flt">{options}</select></label></p></section>'
        f'{"".join(sections)}</main><script>{_JS}</script></body></html>\n')
