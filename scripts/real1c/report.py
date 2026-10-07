"""Standalone HTML/CSV report builder for the real 1C 818HA lane (pure, no I/O)."""

from __future__ import annotations

import csv
import html
import io
from collections import Counter
from collections.abc import Mapping
from typing import Any

from .catalog import Catalog
from .disposition import DISPOSITIONS
from .sanitize import redact_text

SUPPLEMENTARY_KINDS = ("NR", "INV", "RULE", "RL2", "ACL", "SYS")


class ReportIncomplete(Exception):
    """A catalogue story has no result, or more than one, or a result has no story."""


STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "lang": "en",
        "title": "ERP_MCP real 1C 818HA L2 report",
        "subtitle": "Read-only reference lane against the 818HA clone",
        "headline": "Headline counts (catalogue stories)",
        "total": "Total stories",
        "stories": "All catalogue stories",
        "supplementary": "Supplementary results (NR / INV / RULE / RL2 / ACL / SYS)",
        "no_supplementary": "No supplementary results recorded.",
        "gaps": "Requirement gaps (REQ-GAP)",
        "gap_explain": (
            "REQ-GAP means a gap in requirements: a missing definition, feature or rule "
            "that needs an operator scope decision. It is not a test failure."
        ),
        "owner": "Owner actions",
        "owner_1": (
            "Produce at least 10 genuine native 1C UI reports (distinct cases, each with a "
            "report hash) so a semantic profile can be validated."
        ),
        "owner_2": "Accountant sign-off (OACC oracle) on the accountant-judged stories.",
        "manifest": "Reference manifest (sanitised)",
        "git_sha": "Git SHA",
        "data_as_of": "Data as of",
        "generated_at": "Generated at",
        "com_statement": (
            "NATIVE_COM_QUERY comparison never validates a semantic profile. "
            "Only native 1C UI reports count towards validation."
        ),
        "col_id": "ID",
        "col_title": "Title",
        "col_persona": "Persona",
        "col_priority": "Priority",
        "col_class": "Class",
        "col_disposition": "Disposition",
        "col_reason": "Reason",
        "col_evidence": "Evidence",
        "col_tools": "Tools called",
        "col_obs": "Observation",
        "col_kind": "Kind",
        "col_text": "Text",
        "col_key": "Key",
        "col_value": "Value",
    },
    "ru": {
        "lang": "ru",
        "title": "Отчёт ERP_MCP real 1C 818HA L2",
        "subtitle": "Эталонная линия только для чтения на клоне 818HA",
        "headline": "Сводные счётчики (истории каталога)",
        "total": "Всего историй",
        "stories": "Все истории каталога",
        "supplementary": "Дополнительные результаты (NR / INV / RULE / RL2 / ACL / SYS)",
        "no_supplementary": "Дополнительных результатов нет.",
        "gaps": "Пробелы требований (REQ-GAP)",
        "gap_explain": (
            "REQ-GAP означает пробел в требованиях: отсутствующее определение, функция "
            "или правило, по которому нужно решение оператора об объёме. Это не сбой теста."
        ),
        "owner": "Действия владельца",
        "owner_1": (
            "Подготовить не менее 10 настоящих нативных отчётов интерфейса 1C (разные кейсы, "
            "у каждого хеш отчёта), чтобы можно было валидировать семантический профиль."
        ),
        "owner_2": "Подпись бухгалтера (оракул OACC) по историям, требующим его оценки.",
        "manifest": "Эталонный манифест (очищенный)",
        "git_sha": "Git SHA",
        "data_as_of": "Данные на дату",
        "generated_at": "Сформировано",
        "com_statement": (
            "Сравнение NATIVE_COM_QUERY никогда не валидирует семантический профиль. "
            "К валидации относятся только нативные отчёты интерфейса 1C."
        ),
        "col_id": "ID",
        "col_title": "Название",
        "col_persona": "Роль",
        "col_priority": "Приоритет",
        "col_class": "Класс",
        "col_disposition": "Решение",
        "col_reason": "Причина",
        "col_evidence": "Доказательства",
        "col_tools": "Вызванные инструменты",
        "col_obs": "Наблюдение",
        "col_kind": "Тип",
        "col_text": "Текст",
        "col_key": "Ключ",
        "col_value": "Значение",
    },
}

_CSS = """
:root{--bg:#fff;--fg:#1b1f24;--muted:#57606a;--line:#d0d7de;--card:#f6f8fa;
--pass:#1a7f37;--find:#cf222e;--inc:#9a6700;--ev:#0969da;--cap:#6e7781;
--sem:#8250df;--ref:#bc4c00;--err:#82071e}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8b949e;
--line:#30363d;--card:#161b22;--pass:#3fb950;--find:#ff7b72;--inc:#d29922;--ev:#58a6ff;
--cap:#8b949e;--sem:#d2a8ff;--ref:#ffa657;--err:#ffa198}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--line);background:var(--card)}
header h1{margin:0 0 4px;font-size:22px}
main{padding:16px 24px}
h2{margin:28px 0 8px;font-size:17px}
h3{margin:18px 0 6px;font-size:15px}
table{border-collapse:collapse;width:100%;margin:6px 0}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
th{background:var(--card)}
.counts{display:flex;flex-wrap:wrap;gap:8px}
.count{border:1px solid var(--line);border-radius:6px;padding:6px 12px;background:var(--card)}
.badge{font-weight:600;white-space:nowrap}
.d-PASS{color:var(--pass)}.d-FINDING{color:var(--find)}.d-INCONCLUSIVE{color:var(--inc)}
.d-EVIDENCE_REQUIRED{color:var(--ev)}.d-CAPABILITY_UNSUPPORTED{color:var(--cap)}
.d-SEMANTIC_PROFILE_UNVALIDATED{color:var(--sem)}.d-REFUSED-WRITE{color:var(--ref)}
.d-ERROR{color:var(--err)}
.muted{color:var(--muted)}
"""


def _e(value: Any) -> str:
    """Redact secrets, then HTML-escape."""
    return html.escape(redact_text(str(value)), quote=True)


def _short_obs(result: Mapping[str, Any], limit: int = 160) -> str:
    obs = result.get("observations") or []
    if not obs or not isinstance(obs[0], Mapping):
        return ""
    o = obs[0]
    text = f"{o.get('probe', '')}: {o.get('outcome', '')} - {o.get('detail', '')}"
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _index_results(results: list[dict[str, Any]], catalogue: Catalog) -> dict[str, dict[str, Any]]:
    ids = set(catalogue.story_ids())
    seen = Counter(r.get("case_id") for r in results if r.get("kind") in ("ST", "AX"))
    missing = sorted(i for i in ids if seen[i] == 0)
    dupes = sorted(i for i in ids if seen[i] > 1)
    unknown = sorted(str(i) for i in seen if i not in ids)
    if missing or dupes or unknown:
        raise ReportIncomplete(f"missing={missing} duplicated={dupes} not_in_catalogue={unknown}")
    return {r["case_id"]: r for r in results if r.get("kind") in ("ST", "AX")}


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _badge(disposition: Any) -> str:
    cls = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(disposition))
    return f'<span class="badge d-{cls}">{_e(disposition)}</span>'


def build_report(
    results: list[dict[str, Any]],
    catalogue: Catalog,
    manifest_summary: dict[str, Any],
    git_sha: str,
    data_as_of: str,
    generated_at: str,
    *,
    lang: str,
) -> str:
    if lang not in STRINGS:
        raise ValueError(f"unsupported lang: {lang!r}")
    t = STRINGS[lang]
    by_id = _index_results(results, catalogue)
    counts = Counter(r.get("disposition") for r in by_id.values())

    count_html = "".join(
        f'<div class="count">{_badge(d)}: <strong>{counts.get(d, 0)}</strong></div>'
        for d in DISPOSITIONS
    )
    story_tables: list[str] = []
    stories = {s.id: s for s in catalogue.stories}
    for section in catalogue.sections:
        rows = []
        for sid in section.story_ids:
            s, r = stories[sid], by_id[sid]
            rows.append(
                [
                    _e(sid),
                    _e(s.title),
                    _e(s.persona),
                    _e(s.priority),
                    _e(s.catalogue_class),
                    _badge(r.get("disposition")),
                    _e(r.get("reason_code", "")),
                    _e(", ".join(r.get("evidence_classes") or [])),
                    _e(", ".join(r.get("tools_called") or [])),
                    _e(_short_obs(r)),
                ]
            )
        headers = [
            t["col_id"], t["col_title"], t["col_persona"], t["col_priority"], t["col_class"],
            t["col_disposition"], t["col_reason"], t["col_evidence"], t["col_tools"],
            t["col_obs"],
        ]  # fmt: skip
        story_tables.append(
            f'<h3 id="sec-{_e(section.code)}">{_e(section.code)}. {_e(section.title)}</h3>'
            + _table(headers, rows)
        )

    supp = [r for r in results if r.get("kind") in SUPPLEMENTARY_KINDS]
    if supp:
        supp_html = _table(
            [t["col_kind"], t["col_id"], t["col_title"], t["col_disposition"], t["col_reason"],
             t["col_evidence"], t["col_obs"]],
            [
                [
                    _e(r.get("kind")),
                    _e(r.get("case_id")),
                    _e(r.get("title", "")),
                    _badge(r.get("disposition")),
                    _e(r.get("reason_code", "")),
                    _e(", ".join(r.get("evidence_classes") or [])),
                    _e(_short_obs(r)),
                ]
                for r in supp
            ],
        )  # fmt: skip
    else:
        supp_html = f'<p class="muted">{_e(t["no_supplementary"])}</p>'

    gap_html = _table(
        [t["col_id"], t["col_text"]], [[_e(i), _e(text)] for i, text in catalogue.req_gaps]
    )
    owner_extra = sorted({str(r["owner_action"]) for r in results if r.get("owner_action")})
    owner_items = [t["owner_1"], t["owner_2"], *owner_extra]
    owner_html = "<ul>" + "".join(f"<li>{_e(x)}</li>" for x in owner_items) + "</ul>"
    manifest_html = _table(
        [t["col_key"], t["col_value"]],
        [[_e(k), _e(v)] for k, v in sorted(manifest_summary.items())],
    )

    return (
        f'<!DOCTYPE html>\n<html lang="{t["lang"]}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(t['title'])}</title><style>{_CSS}</style></head><body>"
        f'<header><h1>{_e(t["title"])}</h1><div class="muted">{_e(t["subtitle"])}</div>'
        f'<div class="muted">{_e(t["git_sha"])}: <code>{_e(git_sha)}</code> | '
        f"{_e(t['data_as_of'])}: {_e(data_as_of)} | "
        f"{_e(t['generated_at'])}: {_e(generated_at)}</div></header><main>"
        f"<section><h2>{_e(t['headline'])}</h2>"
        f'<div class="count">{_e(t["total"])}: <strong>{len(by_id)}</strong></div>'
        f'<div class="counts">{count_html}</div>'
        f"<p>{_e(t['com_statement'])}</p></section>"
        f"<section><h2>{_e(t['stories'])}</h2>{''.join(story_tables)}</section>"
        f"<section><h2>{_e(t['supplementary'])}</h2>{supp_html}</section>"
        f"<section><h2>{_e(t['gaps'])}</h2><p>{_e(t['gap_explain'])}</p>{gap_html}</section>"
        f"<section><h2>{_e(t['owner'])}</h2>{owner_html}</section>"
        f"<section><h2>{_e(t['manifest'])}</h2>{manifest_html}"
        f"<p>{_e(t['git_sha'])}: <code>{_e(git_sha)}</code></p></section>"
        "</main></body></html>\n"
    )


def _csv_cell(value: Any) -> str:
    text = redact_text(str(value))
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def build_csv(results: list[dict[str, Any]], catalogue: Catalog) -> str:
    by_id = _index_results(results, catalogue)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        ["id", "title", "persona", "priority", "class", "disposition", "reason",
         "evidence_classes", "tools_called", "observation"]
    )  # fmt: skip
    for s in catalogue.stories:
        r = by_id[s.id]
        w.writerow(
            [
                _csv_cell(v)
                for v in (
                    s.id, s.title, s.persona, s.priority, s.catalogue_class,
                    r.get("disposition"), r.get("reason_code", ""),
                    ";".join(r.get("evidence_classes") or []),
                    ";".join(r.get("tools_called") or []), _short_obs(r),
                )
            ]
        )  # fmt: skip
    return buf.getvalue()
