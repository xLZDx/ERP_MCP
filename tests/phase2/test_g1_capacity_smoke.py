"""G1 capacity drill smoke (S4b E5): runs the real CLI at a SMALL size and asserts the recount.

Needs ERP_PHASE2_TEST_DSN. Without it: skip NOT_RUN, or fail when ERP_PHASE2_REQUIRE_PG=1.
The expected numbers are derived here from the parameters, independently of the script's own
``all_ok`` flag, so a drill that loses or duplicates a page/event turns this test red.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from _pg_harness import require_dsn

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "phase2_capacity_drill.py"


def test_capacity_drill_small_run_recounts_clean(tmp_path):
    dsn = require_dsn()
    n, workers, pages, k = 5, 2, 3, 2
    out = tmp_path / "drill.json"
    env = dict(os.environ, ERP_PHASE2_TEST_DSN=dsn)  # DSN only via the environment
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--sources", str(n), "--workers", str(workers),
         "--pages", str(pages), "--out", str(out)],
        env=env, capture_output=True, text=True, timeout=600, check=False)
    assert r.returncode == 0, (r.returncode, r.stdout[-1500:], r.stderr[-1500:])
    rep = json.loads(out.read_text(encoding="utf-8"))
    rc = rep["db_recount"]
    assert rc["cursor_version_sum"] == n * pages
    assert rc["cursors_at_final_page"] == n
    assert rc["outbox_rows"] == n * pages * k
    assert rc["outbox_distinct_event_ids"] == n * pages * k
    assert rc["jobs_succeeded"] == n and rc["jobs_with_fence_not_1"] == 0
    assert rep["error_count"] == 0
    assert rep["latency"]["commit_cursor_page"]["count"] == n * pages
    assert rep["latency"]["acquire_job"]["count"] == n
    assert rep["latency"]["finish_job"]["count"] == n
    assert rep["invariants"]["all_ok"] is True
    assert dsn not in out.read_text(encoding="utf-8")  # the DSN never reaches the report
