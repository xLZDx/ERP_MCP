"""Render an evidence-conscious RU/EN status report from PROJECT_PLAN.md."""
from __future__ import annotations

import html
import re
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports"
REMOTE = "origin/codex/s0-r2-tc001-compat-20261104"

TEXT = {
    "ru": {
        "title": "ERP_MCP — полный статус программы",
        "h1": "ERP_MCP — состояние всех задач программы",
        "hero": "Закрытие программы",
        "not_calc": "Процент закрытия не рассчитан: план S11 содержит только sprint-level rollup, число дочерних задач не указано. Неизвестный знаменатель не заменяется догадкой.",
        "scope": "Охват",
        "scope_value": "Спринты S0–S19, активный FIN backlog и отдельный FOLLOW_ON; S11 показан как сводная запись без декомпозиции дочерних задач.",
        "inventory": "PROJECT_PLAN.md перечисляет 93 task ID в S0–S19 (91 в S1–S19 и 2 в S0), 10 задач FIN и одну FOLLOW_ON. Для S11 указан только статус спринта, без списка и числа дочерних задач; полный знаменатель программы неизвестен.",
        "asof": "Срез",
        "source": "Источник и Git",
        "closed": "Полная продуктовая приёмка",
        "bounded": "Ограниченные критерии подтверждены; продуктовая приёмка остаётся открытой / NOT_RUN",
        "unknown": "Текущий статус задачи не подтверждён на проверяемом HEAD; штриховка означает именно отсутствие подтверждения",
        "queued": "Очередь отмечает задачу как не начатую; это запись плана, не вывод из отсутствия коммита",
        "sprint": "Спринт",
        "bar": "Подтверждённое состояние перечисленных строк",
        "counts": "Записей",
        "active": "Активный спринт из плана",
        "all_tasks": "Задачи и доказательства по спринтам",
        "columns": ["ID / смысл", "Критерии приёмки", "Текущая проверка", "Последний статус в плане", "Доказательства", "Остаток / зависимость", "Владелец / следующий шаг", "Ссылка на коммит в плане", "Точные task-ID коммиты на remote ref: окно / diff-доли"],
        "legend": "Легенда",
        "legend_bounded": "Тёмно-зелёный: ограниченный scope подтверждён; это не полное закрытие задачи.",
        "legend_unknown": "Штрихованный серый: актуальный статус отдельной задачи не подтверждён.",
        "legend_queued": "Серый: задача стоит в явной очереди и записана как не начатая.",
        "gate": "Gate-реестр (отдельно от задач)",
        "gate_note": "Статус gate не используется как число закрытых задач.",
        "no_child": "В плане нет дочернего списка задач S11; текущая запись описывает только статус спринта.",
        "note": "Коммит в колонке плана — ссылка из реестра. Точные даты и доли diff показываются только для коммитов, в сообщении которых явно указан task ID; NR означает, что такой привязанный коммит не найден. Отсутствие task-ID коммита само по себе не доказывает отсутствие кода.",
        "current_head": "Проверенный HEAD",
        "remote": "Remote ref на момент сверки",
        "copy": "Копировать весь HTML",
        "copied": "HTML скопирован",
        "recorded": "Текущий статус не перепроверен; в плане последним записан",
        "bounded_label": "Ограниченный scope подтверждён; продукт открыт",
        "unverified_label": "НЕ ПОДТВЕРЖДЕНО",
        "queued_label": "В очереди / не начата по плану",
        "rollup_label": "Спринтовая сводка; дочерние задачи неизвестны",
        "nr": "NR — нет точных task-ID коммитов",
        "task_rows": "перечисленных строк",
        "sprint_status": "Статус спринта из дорожной карты",
        "fin_note": "FIN — отдельный активный backlog из 10 задач в PROJECT_PLAN.md; его статус показан отдельно и не подменяет статусы S0–S19.",
        "remaining_bounded": "Канонические продуктовые критерии остаются NOT_RUN; bounded scope не закрывает задачу целиком.",
        "remaining_queued": "Критерии ещё не выполнялись; следовать очереди и зависимостям.",
        "remaining_unknown": "Остаток приёмки не подтверждён на текущем HEAD; сначала сверить source records.",
        "depends": "Зависит от",
        "next_bounded": "Завершить оставшиеся канонические продуктовые критерии или сохранить их как NOT_RUN до валидной приёмки.",
        "next_queued": "Повторно подтвердить очередь на текущем HEAD и начинать только после зависимостей.",
        "next_unknown": "Сверить задачу, доказательства и Git на текущем HEAD; обновить статус только по подтверждённым критериям.",
        "active_table_label": "Таблица задач активного спринта; прокручивайте по горизонтали для просмотра всех колонок.",
        "table_scroll": "Таблица задач; прокручивайте по горизонтали для просмотра всех колонок.",
        "tz": "Europe/Chisinau",
        "chart_formula": "Сегменты спринта = число строк с таким подтверждённым состоянием / число перечисленных task-ID строк этого спринта. S11 не имеет task-ID знаменателя.",
        "evidence_legend": "Уровни доказательств в строках: source/implementation = код или документ есть; reviewed = проверено ревьюером; run = зафиксирован результат запуска; NOT_RUN = сценарий не запускался. Это уровни свидетельств, не статусы принятия.",
        "gate_formula": "Gate-процент = PASSED gates / зарегистрированные gates × 100%; знаменатель берётся только из governance/GATE_MANIFEST.json.",
    },
    "en": {
        "title": "ERP_MCP — full program status",
        "h1": "ERP_MCP — status of all program tasks",
        "hero": "Program closure",
        "not_calc": "Closure percentage is not calculated: the S11 plan contains only a sprint-level rollup and gives no child-task count. The unknown denominator is not guessed.",
        "scope": "Coverage",
        "scope_value": "Sprints S0–S19, the active FIN backlog, and separate FOLLOW_ON; S11 is shown as a rollup without child-task decomposition.",
        "inventory": "PROJECT_PLAN.md lists 93 task IDs in S0–S19 (91 in S1–S19 and 2 in S0), 10 FIN tasks, and one FOLLOW_ON item. S11 has only a sprint status, without a child-task list or count; the full program denominator is unknown.",
        "asof": "As of",
        "source": "Source and Git",
        "closed": "Full product acceptance",
        "bounded": "Bounded criteria confirmed; product acceptance remains open / NOT_RUN",
        "unknown": "Current task status is not verified at the inspected HEAD; hatching means precisely that missing confirmation",
        "queued": "The ordered queue records the task as not started; this is a plan record, not an inference from missing commits",
        "sprint": "Sprint",
        "bar": "Confirmed state of listed rows",
        "counts": "Rows",
        "active": "Active sprint in the plan",
        "all_tasks": "Tasks and evidence by sprint",
        "columns": ["ID / meaning", "Acceptance criteria", "Current verification", "Last status in plan", "Evidence", "Remaining / dependency", "Owner / next action", "Plan commit reference", "Exact task-ID commits on remote ref: window / diff shares"],
        "legend": "Legend",
        "legend_bounded": "Dark green: bounded scope confirmed; this is not full task closure.",
        "legend_unknown": "Hatched gray: the individual current task status is not confirmed.",
        "legend_queued": "Gray: the task is explicitly recorded as not started in the ordered queue.",
        "gate": "Gate registry (separate from tasks)",
        "gate_note": "Gate status is not used as a count of completed tasks.",
        "no_child": "The plan has no S11 child-task list; its current row describes sprint status only.",
        "note": "A commit in the plan column is a registry reference. Exact dates and diff shares are shown only for commits whose messages explicitly contain the task ID; NR means no such linked commit was found. Missing task-ID commits alone do not prove that no code exists.",
        "current_head": "Inspected HEAD",
        "remote": "Remote ref at snapshot",
        "copy": "Copy full HTML",
        "copied": "HTML copied",
        "recorded": "Current status not rechecked; last recorded in plan as",
        "bounded_label": "Bounded scope confirmed; product open",
        "unverified_label": "NOT VERIFIED",
        "queued_label": "Queued / not started per plan",
        "rollup_label": "Sprint rollup; child tasks unknown",
        "nr": "NR — no exact task-ID commits",
        "task_rows": "listed rows",
        "sprint_status": "Sprint status from roadmap",
        "fin_note": "FIN is a separate active backlog of 10 tasks in PROJECT_PLAN.md; it is shown separately and does not replace S0–S19 task statuses.",
        "remaining_bounded": "Canonical product criteria remain NOT_RUN; bounded scope does not close the full task.",
        "remaining_queued": "Acceptance work has not started; follow the ordered queue and dependencies.",
        "remaining_unknown": "Remaining acceptance is not confirmed at the current HEAD; reconcile source records first.",
        "depends": "Depends on",
        "next_bounded": "Complete the remaining canonical product criteria or keep them NOT_RUN until valid acceptance evidence exists.",
        "next_queued": "Reconfirm the queue at current HEAD and start only after dependencies are met.",
        "next_unknown": "Reconcile the task, evidence and Git at current HEAD; update status only from confirmed criteria.",
        "active_table_label": "Active-sprint task table; scroll horizontally to view all columns.",
        "table_scroll": "Task table; scroll horizontally to view all columns.",
        "tz": "Europe/Chisinau",
        "chart_formula": "Sprint segments = rows in that confirmed state / task-ID rows listed for that sprint. S11 has no task-ID denominator.",
        "evidence_legend": "Evidence levels in the rows: source/implementation = code or document exists; reviewed = checked by a reviewer; run = an execution result is recorded; NOT_RUN = the scenario was not executed. These are evidence levels, not acceptance statuses.",
        "gate_formula": "Gate percentage = PASSED gates / registered gates × 100%; the denominator comes only from governance/GATE_MANIFEST.json.",
    },
}


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True, encoding="utf-8").strip()


def cells(line: str) -> list[str]:
    return [part.strip().replace("\\|", "|") for part in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def parse_plan() -> tuple[dict[str, str], list[dict[str, str]], dict[str, dict[str, str]]]:
    lines = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8-sig").splitlines()
    meta: dict[str, str] = {}
    i = 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            if ":" in lines[i]:
                k, v = lines[i].split(":", 1)
                meta[k.strip()] = v.strip()
            i += 1
        i += 1
    tasks: list[dict[str, str]] = []
    roadmap: list[dict[str, str]] = []
    sprint_meta: dict[str, dict[str, str]] = {}
    active = ""
    title = ""
    while i < len(lines):
        m = re.match(r"^##\s+Sprint\s+(\S+)\s*[-—–:]*\s*(.*)$", lines[i], re.IGNORECASE)
        if m:
            active, title = m.group(1).rstrip(":"), m.group(2).strip()
            goal = ""
            j = i + 1
            while j < len(lines) and not lines[j].lstrip().startswith("|") and not lines[j].startswith("## "):
                gm = re.match(r"\s*Goal:\s*(.+)$", lines[j])
                if gm:
                    goal = gm.group(1).strip()
                j += 1
            sprint_meta[active] = {"title": title, "goal": goal}
            if j >= len(lines) or not lines[j].lstrip().startswith("|"):
                i = j
                continue
            i = j
            if i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
                headers = [h.lower() for h in cells(lines[i])]
                i += 2
                while i < len(lines) and lines[i].lstrip().startswith("|"):
                    vals = cells(lines[i])
                    if len(vals) < len(headers):
                        vals += [""] * (len(headers) - len(vals))
                    row = dict(zip(headers, vals))
                    task_id = row.get("task") or row.get("id") or ""
                    if task_id and task_id != "Task":
                        tasks.append({"sprint": active, "sprint_title": title, "id": task_id,
                                      "title": row.get("title", ""), "acceptance": row.get("acceptance") or row.get("acceptance criteria", ""),
                                      "status": row.get("status", ""), "evidence": row.get("evidence", ""),
                                      "owner": row.get("owner", ""), "depends": row.get("depends", ""), "commit": row.get("commit", "")})
                    i += 1
            continue
        if re.match(r"^##\s+Roadmap\s*$", lines[i], re.IGNORECASE):
            i += 1
            while i < len(lines) and not lines[i].lstrip().startswith("|"):
                i += 1
            if i < len(lines) and lines[i].lstrip().startswith("|"):
                headers = [h.lower() for h in cells(lines[i])]
                i += 2
                while i < len(lines) and lines[i].lstrip().startswith("|"):
                    vals = cells(lines[i])
                    vals += [""] * max(0, len(headers) - len(vals))
                    roadmap.append(dict(zip(headers, vals)))
                    i += 1
            continue
        i += 1
    return meta, tasks, {"roadmap": roadmap, "sprints": sprint_meta}


def remote_task_commits() -> dict[str, list[tuple[str, int, str]]]:
    log = git("log", REMOTE, "--format=%H%x09%ct%x09%s").splitlines()
    tasks: dict[str, list[tuple[str, int, str]]] = {}
    plan_ids = [t["id"] for t in parse_plan()[1]]
    for line in log:
        sha, ts, subject = line.split("\t", 2)
        for task_id in plan_ids:
            if re.search(r"(?<![A-Z0-9])" + re.escape(task_id) + r"(?![A-Z0-9])", subject, re.IGNORECASE):
                tasks.setdefault(task_id, []).append((sha, int(ts), subject))
    return tasks


def current_kind(t: dict[str, str]) -> str:
    ev = t["evidence"].lower()
    status = t["status"].upper()
    if status == "BOUNDED_SCOPE_COMPLETE" or (t["id"] in {f"R2-US-{n:03d}" for n in range(1, 7)} and "not_run" in ev):
        return "bounded"
    if "queued; no task-id commits" in ev:
        return "queued"
    return "unknown"


def commit_info(t: dict[str, str], commits: dict[str, list[tuple[str, int, str]]]) -> str:
    linked = commits.get(t["id"], [])
    if not linked:
        return f"NR — no exact-ID commit message on {REMOTE}; absence does not prove no code"
    linked = sorted(linked, key=lambda x: x[1])
    first = datetime.fromtimestamp(linked[0][1], UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    last = datetime.fromtimestamp(linked[-1][1], UTC).astimezone().strftime("%Y-%m-%d %H:%M")
    info = f"{len(linked)}; first {linked[0][0][:12]} {first}; last {linked[-1][0][:12]} {last} Europe/Chisinau; on {REMOTE}"
    if t["sprint"] == "FIN":
        info += "; diff share NR"
    return info


def plan_commit(t: dict[str, str]) -> str:
    ref = t["commit"].strip()
    if not ref:
        return "—"
    try:
        full = git("rev-parse", "--verify", ref + "^{commit}")
        reachable = subprocess.run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", full, REMOTE], check=False, capture_output=True).returncode == 0
        return f"{html.escape(ref)} — {html.escape(full[:12])}; {'remote reachable' if reachable else 'not on remote ref'}"
    except subprocess.CalledProcessError:
        return f"{html.escape(ref)} — NOT VERIFIED"


def state_label(kind: str, lang: str) -> str:
    t = TEXT[lang]
    return {"bounded": t["bounded_label"], "unknown": t["unverified_label"], "queued": t["queued_label"]}[kind]


def render(lang: str, meta: dict[str, str], tasks: list[dict[str, str]], info: dict[str, dict[str, str]], gates: dict[str, Counter[str]], commit_map: dict[str, list[tuple[str, int, str]]], head: str, remote_head: str) -> str:
    t = TEXT[lang]
    e = html.escape
    by_sprint: dict[str, list[dict[str, str]]] = {}
    for task in tasks:
        by_sprint.setdefault(task["sprint"], []).append(task)
    bounded = sum(current_kind(x) == "bounded" for x in tasks)
    program_sprints = [f"S{i}" for i in range(20)] + ["FIN"]
    active = meta.get("active_sprint", "")
    active_rows = by_sprint.get(active, [])
    css = """
    :root{color-scheme:light;--ink:#172033;--muted:#526078;--line:#cbd5e1;--green:#17803d;--dark:#075b35;--blue:#2563eb;--gray:#667085;--amber:#ad6500;--bg:#f4f7fb}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,Segoe UI,Arial,sans-serif}main{max-width:1600px;margin:auto;padding:24px}header,.panel{background:#fff;border:1px solid var(--line);border-radius:12px;padding:20px;margin:0 0 18px;box-shadow:0 2px 8px #0f172a0b}h1{font-size:2rem;margin:.2em 0}h2{margin:.2em 0 .7em}h3{margin:.2em 0 .5em}.muted,.small{color:var(--muted);font-size:.92rem}.hero-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.stat{border:1px solid var(--line);padding:12px;border-radius:8px}.legend{display:flex;flex-wrap:wrap;gap:10px 18px;margin-top:12px}.key{display:inline-flex;align-items:center;gap:7px}.swatch{display:inline-block;width:22px;height:15px;border:1px solid #667085;border-radius:3px}.bounded{background:var(--dark)}.queued{background:#98a2b3}.unknown{background:repeating-linear-gradient(135deg,#e5e7eb 0 5px,#7b8494 5px 7px)}.bar{height:17px;display:flex;border:1px solid #6b7280;border-radius:4px;overflow:hidden;min-width:180px}.bar span{display:block;min-width:0}.bar .bounded{background:var(--dark)}.bar .queued{background:#98a2b3}.bar .unknown{background:repeating-linear-gradient(135deg,#d1d5db 0 5px,#667085 5px 7px)}.sprint-row{display:grid;grid-template-columns:minmax(170px,1.1fr) minmax(180px,2fr) minmax(110px,.7fr);gap:12px;align-items:center;padding:7px 0;border-bottom:1px solid #e5e7eb}.table-wrap{overflow-x:auto;max-width:100%}.table-wrap:focus-visible{outline:3px solid #1d4ed8;outline-offset:3px;border-radius:4px}table{border-collapse:collapse;width:100%;min-width:1450px;font-size:.88rem;table-layout:fixed}th,td{border:1px solid var(--line);padding:8px;vertical-align:top;overflow-wrap:anywhere;word-break:normal}th{position:sticky;top:0;background:#eaf0f8;text-align:left;z-index:1}td.state-bounded{background:#e4f3e9;border-left:5px solid var(--dark)}td.state-queued{background:#f1f3f5;border-left:5px solid #98a2b3}td.state-unknown{background:repeating-linear-gradient(135deg,#f4f5f7 0 8px,#e1e4e8 8px 10px);border-left:5px solid #7b8494}.pill{display:inline-block;padding:2px 7px;border-radius:12px;background:#e8edf5;font-weight:650}.sprint{scroll-margin-top:12px;margin-top:22px}.copy{float:right;padding:8px 12px;border:1px solid var(--line);border-radius:6px;background:white;cursor:pointer}@media(max-width:700px){main{padding:10px}header,.panel{padding:13px}.sprint-row{grid-template-columns:1fr;gap:4px}h1{font-size:1.55rem}}
    """
    out = [f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(t["title"])}</title><style>{css}</style></head><body><main>',
           '<header>',
           f'<p class="muted">{e(t["asof"])}: {e(meta.get("as_of", ""))} {e(t["tz"])} · {e(t["source"])}: PROJECT_PLAN.md + in-repository evidence · {e(t["current_head"])}: <code>{e(head)}</code> · {e(t["remote"])}: <code>{e(REMOTE)} @ {e(remote_head)}</code></p>',
           f'<h1>{e(t["h1"])}</h1><h2>{e(t["hero"])}</h2><div class="hero-grid"><div class="stat"><b>{e(t["not_calc"])}</b></div><div class="stat"><b>{e(t["scope"])}</b><br>{e(t["scope_value"])}</div><div class="stat"><b>{e(t["inventory"])}</b></div><div class="stat"><b>{bounded}</b> {e(t["bounded"])}</div></div>',
           f'<p class="small">{e(t["fin_note"])}</p><h3>{e(t["legend"])}</h3><div class="legend"><span class="key"><i class="swatch bounded"></i>{e(t["legend_bounded"])}</span><span class="key"><i class="swatch unknown"></i>{e(t["legend_unknown"])}</span><span class="key"><i class="swatch queued"></i>{e(t["legend_queued"])}</span></div></header>',
           f'<section class="panel"><h2>{e(t["sprint"])} S0–S19 + FIN</h2><p class="small">{e(t["not_calc"])}</p><p class="small">{e(t["chart_formula"])}</p><p class="small">{e(t["evidence_legend"])}</p><div class="legend"><span class="key"><i class="swatch bounded"></i>{e(t["legend_bounded"])}</span><span class="key"><i class="swatch unknown"></i>{e(t["legend_unknown"])}</span><span class="key"><i class="swatch queued"></i>{e(t["legend_queued"])}</span></div>']
    for sid in program_sprints:
        sprint_tasks = by_sprint.get(sid, [])
        if sid == "S11" and not sprint_tasks:
            roadmap_status = next((r.get("status", "") for r in info["roadmap"] if r.get("sprint") == sid), "UNKNOWN")
            out.append(f'<div class="sprint-row"><b>{sid} — {e(info["sprints"].get(sid, {}).get("title", ""))}</b><span class="pill">{e(t["rollup_label"])}: {e(roadmap_status)}</span><span>task denominator: UNKNOWN</span></div>')
            continue
        if not sprint_tasks:
            continue
        counts = Counter(current_kind(x) for x in sprint_tasks)
        total = len(sprint_tasks)
        segments = "".join(f'<span class="{k}" style="width:{100*v/total:.4f}%" title="{k}: {v}"></span>' for k,v in counts.items() if v)
        out.append(f'<div class="sprint-row"><b>{e(sid)} — {e(info["sprints"].get(sid, {}).get("title", ""))}</b><div class="bar" role="img" aria-label="{total} {e(t["task_rows"])}">{segments}</div><span>{counts["bounded"]} bounded · {counts["queued"]} queued · {counts["unknown"]} unverified / {total}</span></div>')
    out.append('</section>')
    out.append(f'<section class="panel"><h2>{e(t["active"])}: {e(active)}</h2><div class="table-wrap" role="region" tabindex="0" aria-label="{e(t["active_table_label"])}">{render_table(active_rows, t, lang, commit_map, active=True)}</div></section>')
    out.append(f'<section class="panel"><h2>{e(t["all_tasks"])}</h2><p>{e(t["note"])}</p>')
    order = program_sprints + ["FOLLOW_ON"]
    for sid in order:
        rows_for = by_sprint.get(sid, [])
        if sid == "S11" and not rows_for:
            status = next((r.get("status", "UNKNOWN") for r in info["roadmap"] if r.get("sprint") == sid), "UNKNOWN")
            out.append(f'<section class="sprint" id="sprint-S11"><h3>S11 — {e(info["sprints"].get("S11", {}).get("title", ""))}</h3><p class="state-unknown">{e(t["rollup_label"])} · {e(t["sprint_status"])}: {e(status)}. {e(t["no_child"])}</p></section>')
            continue
        if not rows_for:
            continue
        out.append(f'<section class="sprint" id="sprint-{e(sid)}"><h3>{e(sid)} — {e(info["sprints"].get(sid, {}).get("title", ""))}</h3><div class="table-wrap" role="region" tabindex="0" aria-label="{e(sid)} — {e(t["table_scroll"])}">{render_table(rows_for, t, lang, commit_map)}</div></section>')
    out.append('</section>')
    if gates:
        total_gates = sum(sum(c.values()) for c in gates.values())
        summaries = []
        for source, counter in gates.items():
            passed = counter.get("PASSED", 0)
            pct = f"{100 * passed / sum(counter.values()):.1f}%" if sum(counter.values()) else "NR"
            summaries.append(f'<p><b>{e(source)}</b>: ' + ' · '.join(f'{e(k)} {v}' for k,v in sorted(counter.items())) + f' · {passed}/{sum(counter.values())} ({pct})</p>')
        out.append(f'<section class="panel"><h2>{e(t["gate"])}</h2>{"".join(summaries)}<p>{e(t["gate_formula"])}</p><p>{e(t["gate_note"])} Total registered gate rows: {total_gates}.</p></section>')
    out.append(f'<footer class="panel small">{e(t["note"])}</footer></main></body></html>')
    return "\n".join(out)


def render_table(rows: list[dict[str, str]], t: dict[str, object], lang: str, commit_map: dict[str, list[tuple[str, int, str]]], active: bool = False) -> str:
    e = html.escape
    headers = list(t["columns"])
    out = ['<table><thead><tr>' + ''.join(f'<th>{e(h)}</th>' for h in headers) + '</tr></thead><tbody>']
    for task in rows:
        kind = current_kind(task)
        localized_state = state_label(kind, lang)
        if kind == "unknown":
            localized_state += f" ({e(t['recorded'])} {e(task['status'])})"
        evidence = e(task["evidence"])
        rem_key = {"bounded": "remaining_bounded", "queued": "remaining_queued", "unknown": "remaining_unknown"}[kind]
        next_key = {"bounded": "next_bounded", "queued": "next_queued", "unknown": "next_unknown"}[kind]
        rem = e(t[rem_key])
        if task["depends"]:
            rem += f'<br><b>{e(t["depends"])}:</b> {e(task["depends"])}'
        reference = plan_commit(task)
        commits = e(commit_info(task, commit_map))
        owner_next = f'{e(task["owner"] or "Codex")}<br>{e(t[next_key])}'
        vals = [f'<b>{e(task["id"])}</b><br>{e(task["title"])}', e(task["acceptance"]), localized_state, e(task["status"]), evidence, rem, owner_next, reference]
        vals.append(commits)
        out.append(f'<tr><td>{vals[0]}</td><td>{vals[1]}</td><td class="state-{kind}">{vals[2]}</td><td>{vals[3]}</td><td>{vals[4]}</td><td>{vals[5]}</td><td>{vals[6]}</td><td>{vals[7]}</td>')
        out.append(f'<td>{vals[8]}</td>')
        out.append('</tr>')
    out.append('</tbody></table>')
    return ''.join(out)


def main() -> None:
    meta, tasks, info = parse_plan()
    head = git("rev-parse", "HEAD")
    remote_head = git("rev-parse", REMOTE)
    commit_map = remote_task_commits()
    gate_path = ROOT / "governance" / "GATE_MANIFEST.json"
    gates: dict[str, Counter[str]] = {}
    if gate_path.exists():
        import json
        manifest = json.loads(gate_path.read_text(encoding="utf-8"))
        gates["governance/GATE_MANIFEST.json"] = Counter(g.get("gate_status", "UNKNOWN") for g in manifest.get("gates", []))
    OUT.mkdir(exist_ok=True)
    for lang, suffix in (("ru", ".ru.html"), ("en", ".html")):
        path = OUT / ("ERP_MCP_FULL_PROGRAM_STATUS_2026-11-05" + suffix)
        path.write_text(render(lang, meta, tasks, info, gates, commit_map, head, remote_head), encoding="utf-8", newline="\n")
        print(path)
    print(f"HEAD={head} tasks={len(tasks)} exact_task_ids_with_remote_commits={len(commit_map)}")


if __name__ == "__main__":
    main()
