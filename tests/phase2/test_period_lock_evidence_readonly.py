from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from scripts.real1c import period_lock_evidence_readonly as report


class FakeOracle:
    def __init__(self, posted):
        self._conn = object()
        self.posted = posted

    def platform_and_config(self):
        return {"configuration_version": "test"}

    def rows(self, _query, fields):
        if "Проведен" in fields:
            return [{"Дата": "2025-12-01", "Состояние": "Проверка", "Проведен": self.posted}]
        return [{"Раздел": "Тест", "Объект": "Тест", "Пользователь": "Для всех пользователей",
                 "ДатаЗапрета": "2025-12-01"}]


class PeriodLockEvidenceTests(unittest.TestCase):
    def run_report(self, posted):
        output = io.StringIO()
        with (
            patch.object(report, "Oracle", side_effect=lambda: FakeOracle(posted)),
            patch.object(report, "metadata_names", return_value=["Test.Metadata"]),
            patch.object(report, "_verify_export_metadata_matches_live", return_value={"match": True}),
            patch.object(report, "_sha", return_value="0" * 64),
            contextlib.redirect_stdout(output),
        ):
            exit_code = report.main()
        return exit_code, json.loads(output.getvalue())

    def test_boolean_posted_flag_is_reported(self):
        exit_code, result = self.run_report(True)
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["period_operation_summary"][0]["posted"], True)

    def test_non_boolean_posted_flag_fails_closed(self):
        for malformed in ("false", 0, 1):
            with self.subTest(value=malformed):
                exit_code, result = self.run_report(malformed)
                self.assertEqual(exit_code, 2)
                self.assertEqual(result["error"], "PERIOD_LOCK_OBSERVATION_UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
