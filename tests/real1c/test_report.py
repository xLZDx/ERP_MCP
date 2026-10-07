from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from scripts.real1c.catalog import load_catalog
from scripts.real1c.report import ReportIncomplete, build_csv, build_report

CATALOG = Path(__file__).resolve().parents[2] / "docs" / "REAL_1C_STORY_CATALOG_818HA.md"
H = "b" * 64


@pytest.fixture(scope="module")
def cat():
    return load_catalog(CATALOG)


def _results(cat):
    return [
        {
            "schema_version": 1, "case_id": s.id, "kind": s.kind, "title": s.title,
            "catalogue_class": s.catalogue_class, "disposition": "INCONCLUSIVE",
            "reason_code": "oracle_not_compared", "evidence_classes": ["GATEWAY_OBSERVATION"],
            "observations": [{"probe": "p", "outcome": "o", "detail": "d"}],
            "tools_called": list(s.tools), "oracle": s.oracle, "git_sha": "a" * 40,
            "manifest_sha256": H, "finished_at": "2026-10-07T10:00:00Z",
        }
        for s in cat.stories
    ]  # fmt: skip


def _build(cat, results, lang="en"):
    return build_report(results, cat, {"manifest_sha256": H}, "a" * 40,
                        "2026-09-15", "2026-10-07T10:00:00Z", lang=lang)  # fmt: skip


def test_report_builds_en_and_ru(cat):
    res = _results(cat)
    en, ru = _build(cat, res, "en"), _build(cat, res, "ru")
    assert "ERP_MCP real 1C 818HA L2 report" in en and '<html lang="en">' in en
    assert "Отчёт ERP_MCP" in ru and '<html lang="ru">' in ru
    assert "<header>" in en and "prefers-color-scheme:dark" in en
    assert "NATIVE_COM_QUERY comparison never validates" in en
    assert "REQ-GAP means a gap in requirements" in en
    for sid in ("ST-001", "ST-090", "AX-040", "REQ-GAP-27"):
        assert sid in en
    assert "http://" not in en + ru and "https://" not in en + ru


def test_every_story_appears_in_table_exactly_once(cat):
    out = _build(cat, _results(cat))
    for s in cat.stories:
        assert out.count(f"<td>{s.id}</td>") == 1


def test_missing_or_duplicate_story_raises(cat):
    res = _results(cat)
    with pytest.raises(ReportIncomplete):
        _build(cat, res[1:])
    with pytest.raises(ReportIncomplete):
        _build(cat, [*res, res[0]])
    with pytest.raises(ReportIncomplete):
        build_csv(res[:-1], cat)


def test_html_escaping_of_result_and_catalogue_text(cat):
    res = _results(cat)
    res[0]["observations"][0]["detail"] = "<script>alert(1)</script>"
    res[0]["title"] = "<script>x</script>"
    evil = dataclasses.replace(cat.stories[1], title="<script>evil</script>")
    cat2 = dataclasses.replace(cat, stories=(cat.stories[0], evil, *cat.stories[2:]))
    out = _build(cat2, res)
    assert "<script>" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "&lt;script&gt;evil&lt;/script&gt;" in out


def test_supplementary_table_and_secrets_redacted(cat):
    res = _results(cat)
    res.append({**res[0], "case_id": "NR-01", "kind": "NR", "title": "native one",
                "observations": [{"probe": "p", "outcome": "o", "detail": "password=hunter2"}]})  # fmt: skip
    out = _build(cat, res)
    assert "NR-01" in out and "hunter2" not in out


def test_csv_one_row_per_story_and_sanitised(cat):
    res = _results(cat)
    res[0]["observations"][0]["detail"] = "=cmd token=abc123"
    csv_text = build_csv(res, cat)
    lines = csv_text.strip().split("\n")
    assert len(lines) == 131
    assert "abc123" not in csv_text
    assert "http://" not in csv_text
