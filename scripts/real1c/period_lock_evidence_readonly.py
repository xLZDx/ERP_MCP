"""Collect bounded, sanitized period-candidate observations from the fixed clone.

This is candidate source evidence only. It does not derive a fiscal-period status or
claim FIN-S1.2 acceptance; a qualified PeriodSnapshotReader is still required.
The existing COM oracle pins the target to 818HA_test_ready and accepts SELECT only.
"""
from __future__ import annotations

import json
import re

from scripts.real1c.com_fingerprint import _sha, metadata_names
from scripts.real1c.com_oracle import Oracle

MAX_ROWS = 100
MAX_OPERATION_ROWS = 1000
QUERY = """ВЫБРАТЬ ПЕРВЫЕ 100
    ПРЕДСТАВЛЕНИЕ(Т.Раздел) КАК Раздел,
    ПРЕДСТАВЛЕНИЕ(Т.Объект) КАК Объект,
    ПРЕДСТАВЛЕНИЕ(Т.Пользователь) КАК Пользователь,
    Т.ДатаЗапрета КАК ДатаЗапрета
ИЗ РегистрСведений.ДатыЗапретаИзменения КАК Т"""
OPERATIONS_QUERY = """ВЫБРАТЬ ПЕРВЫЕ 1001
    Т.Дата КАК Дата,
    ПРЕДСТАВЛЕНИЕ(Т.Состояние) КАК Состояние,
    Т.Проведен КАК Проведен
ИЗ Документ.РегламентнаяОперация КАК Т
УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ"""
_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:\s|$)")


def _date_only(value: object) -> str:
    match = _DATE.match(str(value))
    if match is None:
        raise ValueError("PERIOD_LOCK_DATE_INVALID")
    return match.group(1)


def main() -> int:
    oracle = None
    try:
        oracle = Oracle()  # fixed 818HA_test_ready clone; protected credential is never emitted
        metadata = oracle.platform_and_config()
        names = metadata_names(oracle._conn)
        rows = oracle.rows(
            QUERY,
            ("Раздел", "Объект", "Пользователь", "ДатаЗапрета"),
        )
        if len(rows) >= MAX_ROWS:
            raise ValueError("PERIOD_LOCK_ROW_LIMIT_REACHED")
        operation_rows = oracle.rows(
            OPERATIONS_QUERY,
            ("Дата", "Состояние", "Проведен"),
        )
        if len(operation_rows) > MAX_OPERATION_ROWS:
            raise ValueError("PERIOD_OPERATION_ROW_LIMIT_REACHED")
        operation_counts: dict[tuple[str, str, bool], int] = {}
        for row in operation_rows:
            date = _date_only(row["Дата"])
            state = str(row["Состояние"]).strip()
            if not state:
                raise ValueError("PERIOD_OPERATION_STATE_INVALID")
            key = (date[:7], state, bool(row["Проведен"]))
            operation_counts[key] = operation_counts.get(key, 0) + 1
        operation_summary = [
            {
                "period": period,
                "state": state,
                "posted": posted,
                "count": count,
            }
            for (period, state, posted), count in sorted(operation_counts.items())
        ]
        observations = []
        for row in rows:
            user = str(row["Пользователь"]).strip()
            observations.append(
                {
                    "section_specific": bool(str(row["Раздел"]).strip()),
                    "object_specific": bool(str(row["Объект"]).strip()),
                    "user_scope": "all_users" if user == "Для всех пользователей" else "scoped_or_other",
                    "restriction_date": _date_only(row["ДатаЗапрета"]),
                }
            )
        result = {
            "classification": "CANDIDATE_NOT_GATE_ACCEPTANCE",
            "source_clone": "818HA_test_ready",
            "authentication": "protected COM reader credential accepted; value and identity omitted",
            "platform_config": metadata,
            "metadata_object_count": len(names),
            "metadata_fingerprint": _sha(names),
            "register": "ДатыЗапретаИзменения",
            "rows_returned": len(observations),
            "row_limit": MAX_ROWS,
            "observations": observations,
            "period_operation_records": len(operation_rows),
            "period_operation_row_limit": MAX_OPERATION_ROWS,
            "period_operation_summary": operation_summary,
            "scope_limit": (
                "raw date-lock and close-operation facts only; no fiscal-period mapping "
                "or gateway acceptance claim"
            ),
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 - never expose COM/1C text or secrets
        print(
            json.dumps(
                {
                    "classification": "CANDIDATE_NOT_GATE_ACCEPTANCE",
                    "error": "PERIOD_LOCK_OBSERVATION_UNAVAILABLE",
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
