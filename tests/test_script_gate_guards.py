import subprocess
import sys
from pathlib import Path

import pytest

from scripts.acl_load_drill import require_authorization_count
from scripts.postgres_restore_drill import fingerprint


@pytest.mark.parametrize('actual,expected', [(0, 30), (True, 1), (1, True), (0, 0), (None, 30)])
def test_acl_measurement_cannot_claim_pass_for_missing_or_noninteger_authorization(actual, expected):
    with pytest.raises(RuntimeError, match='ACL_LOAD_AUTHORIZATION_COUNT_MISMATCH'):
        require_authorization_count(actual, expected)


def test_acl_guard_is_executed_even_when_python_optimization_disables_asserts():
    require_authorization_count(30, 30)
    result = subprocess.run(
        [sys.executable, '-O', '-c', ('from scripts.acl_load_drill import require_authorization_count; '
         'require_authorization_count(30, 30); require_authorization_count(0, 30)')],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode != 0 and 'ACL_LOAD_AUTHORIZATION_COUNT_MISMATCH' in result.stderr


@pytest.mark.parametrize('identifier', ['sources;DROP TABLE bag.sources', 'sources"', 'other.sources', 'sources-escape', 'SourceUpperCase'])
async def test_restore_fingerprint_identifier_guard_prevents_dynamic_sql_escape(identifier):
    calls = []

    class Connection:
        async def fetch(self, statement):
            calls.append(statement)
            return [{'tablename': identifier}]

    with pytest.raises(RuntimeError, match='Unsafe schema table identifier'):
        await fingerprint(Connection())
    assert len(calls) == 1 and identifier not in calls[0]
