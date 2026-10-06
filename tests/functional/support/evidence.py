"""Per-case evidence collector. Tests call record(); scripts/ft/make_report.py renders it.

Output is git-ignored (var/ft/case_evidence.json). It never stores response payload rows:
only counts, audit outcomes/detail codes, request ids and HTTP method sets.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from tests.functional.support.harness import REPO_ROOT

OUT = Path(os.environ.get("FT_EVIDENCE_OUT") or REPO_ROOT / "var" / "ft" / "case_evidence.json")


def record(case_id: str, **fields) -> None:
    data = {}
    if OUT.exists():
        try:
            data = json.loads(OUT.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    entry = data.setdefault(case_id, {})
    for key, value in fields.items():
        if isinstance(value, list) and isinstance(entry.get(key), list):
            entry[key] = entry[key] + [v for v in value if v not in entry[key]]
        else:
            entry[key] = value
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, sort_keys=True, default=str), encoding="utf-8")


def reset() -> None:
    if OUT.exists():
        OUT.unlink()
