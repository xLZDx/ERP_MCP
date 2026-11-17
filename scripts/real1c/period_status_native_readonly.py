"""Read the target 1C close-month routine's temporary status table on the fixed clone.

Candidate evidence only. The common module builds temporary tables and executes read
queries; this script emits only grouped counts and never exposes organization or operation
names, document references, amounts, or credentials. It does not bind the observation to
the gateway's source/company registry and does not claim PERIOD_CLOSED acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime

from scripts.real1c.com_fingerprint import metadata_names
from scripts.real1c.com_oracle import Oracle
from scripts.real1c.period_lock_evidence_readonly import _verify_export_metadata_matches_live

MAX_ORGANIZATIONS = 100
MAX_STATUS_ROWS = 1000
STATUS_QUERY = """ВЫБРАТЬ ПЕРВЫЕ 1001
    Т.Требуется КАК Требуется,
    ПРЕДСТАВЛЕНИЕ(Т.Состояние) КАК Состояние,
    Т.Устарела КАК Устарела,
    Т.РучнаяКорректировка КАК РучнаяКорректировка,
    ВЫБОР
        КОГДА Т.Требуется
            И НЕ(
                Т.Состояние = ЗНАЧЕНИЕ(Перечисление.ВидыСостоянийРегламентныхОпераций.Пропущено)
                ИЛИ Т.Состояние = ЗНАЧЕНИЕ(Перечисление.ВидыСостоянийРегламентныхОпераций.Выполнено)
                    И НЕ Т.Устарела
            )
            ТОГДА ИСТИНА
        ИНАЧЕ ЛОЖЬ
    КОНЕЦ КАК БлокируетПродолжение
ИЗ ДетальныйСтатусЗакрытияМесяца КАК Т"""
ORGANIZATIONS_QUERY = """ВЫБРАТЬ ПЕРВЫЕ 101
    Т.Ссылка КАК Ссылка,
    Т.ПометкаУдаления КАК ПометкаУдаления
ИЗ Справочник.Организации КАК Т"""


def _period_date(value: str) -> datetime:
    try:
        return datetime.strptime(value + "-01", "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("PERIOD_MONTH_INVALID") from exc


def _status_summary(rows) -> list[dict]:
    counts: dict[tuple[bool, str, bool, bool], int] = {}
    for row in rows:
        state = str(row["Состояние"]).strip()
        if not state:
            raise ValueError("PERIOD_STATUS_STATE_INVALID")
        key = (
            bool(row["Требуется"]),
            state,
            bool(row["Устарела"]),
            bool(row["РучнаяКорректировка"]),
        )
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "required": required,
            "state": state,
            "stale": stale,
            "manually_corrected": corrected,
            "count": count,
        }
        for (required, state, stale, corrected), count in sorted(counts.items())
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--period", default="2026-06", help="calendar month YYYY-MM")
    args = parser.parse_args()

    oracle = None
    try:
        period = _period_date(args.period)
        oracle = Oracle()  # fixed 818HA_test_ready clone; protected credential remains private
        conn = oracle._conn
        metadata = oracle.platform_and_config()
        export_match = _verify_export_metadata_matches_live(
            metadata, metadata_names(conn)
        )

        organizations = oracle.rows(
            ORGANIZATIONS_QUERY, ("Ссылка", "ПометкаУдаления")
        )
        if len(organizations) > MAX_ORGANIZATIONS:
            raise ValueError("PERIOD_ORGANIZATION_LIMIT_REACHED")
        active = [row["Ссылка"] for row in organizations if not bool(row["ПометкаУдаления"])]
        if len(active) != 1:
            raise ValueError("PERIOD_ACTIVE_ORGANIZATION_NOT_UNIQUE")
        organization = active[0]

        # This exported 1C routine derives required/stale status from configuration and
        # business data into session-local temporary tables; it does not persist 1C rows.
        manager = conn.NewObject("МенеджерВременныхТаблиц")
        close_month = getattr(conn, "ЗакрытиеМесяца")
        getattr(close_month, "СоздатьДетальныйСтатусЗакрытияМесяца")(
            manager, period, organization
        )
        query = conn.NewObject("Запрос")
        query.МенеджерВременныхТаблиц = manager
        query.Текст = STATUS_QUERY
        table = query.Выполнить().Выгрузить()
        row_count = int(table.Count())
        if row_count > MAX_STATUS_ROWS:
            raise ValueError("PERIOD_STATUS_ROW_LIMIT_REACHED")
        rows = [
            {
                "Требуется": table.Get(index).Требуется,
                "Состояние": table.Get(index).Состояние,
                "Устарела": table.Get(index).Устарела,
                "РучнаяКорректировка": table.Get(index).РучнаяКорректировка,
                "БлокируетПродолжение": table.Get(index).БлокируетПродолжение,
            }
            for index in range(row_count)
        ]
        blocking_required_operations = sum(
            bool(row["БлокируетПродолжение"]) for row in rows
        )

        organization_id = oracle.guid(organization)
        result = {
            "classification": "CANDIDATE_NATIVE_CLOSE_STATUS",
            "source_clone": "818HA_test_ready",
            "authentication": "protected COM credential accepted; value and identity omitted",
            "configuration": {
                "version": metadata["configuration_version"],
                "metadata_names_match_export": export_match["metadata_names_match_live"],
                "metadata_name_fingerprint": export_match["metadata_fingerprint"],
                "bsl_source_bytes_compared": False,
            },
            "period": args.period,
            "active_organization_count": 1,
            "organization_reference_sha256": hashlib.sha256(
                organization_id.encode("ascii")
            ).hexdigest(),
            "native_status_rows": row_count,
            "status_summary": _status_summary(rows),
            "blocking_required_operation_count": blocking_required_operations,
            "close_flow_ready": row_count > 0 and blocking_required_operations == 0,
            "scope_limit": (
                "The configured 1C close-month routine produced the temporary status rows. "
                "blocking_required_operation_count follows the exported form's query condition; "
                "close_flow_ready means only that this diagnostic found no blocking required "
                "operation. It does not establish accounting-period closure. This diagnostic is "
                "not bound to gateway source_id/company_id; the live BSL bytes are not compared "
                "to the export; no PERIOD_CLOSED or FIN-S1.2 acceptance claim is made."
            ),
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - do not leak COM details or user/business data
        print(
            json.dumps(
                {
                    "classification": "CANDIDATE_NATIVE_CLOSE_STATUS",
                    "error": "PERIOD_NATIVE_STATUS_UNAVAILABLE",
                    "exception_type": type(exc).__name__,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    finally:
        if oracle is not None:
            oracle._conn = None


if __name__ == "__main__":
    raise SystemExit(main())
