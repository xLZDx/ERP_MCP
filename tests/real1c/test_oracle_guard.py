"""The COM oracle is read-only by construction; these tests need no 1C (the connection is a stub)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from scripts.real1c import native_checks
from scripts.real1c.catalog import load_catalog
from scripts.real1c.com_oracle import Oracle, OracleReadOnlyViolation
from scripts.real1c.report import build_csv


class _StubConn:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def NewObject(self, kind, text=None):
        self.queries.append(text)
        raise RuntimeError("stub: no 1C available")


def _oracle() -> Oracle:
    o = Oracle.__new__(Oracle)
    o._conn = _StubConn()
    o.query_log = []
    o.label = ""
    return o


@pytest.mark.parametrize("text", ["УДАЛИТЬ Т ИЗ Справочник.Контрагенты", "  ; ВЫБРАТЬ 1", "UPDATE x", "", "Записать()"])
def test_non_select_text_never_reaches_com(text):
    o = _oracle()
    with pytest.raises(OracleReadOnlyViolation):
        o.query(text)
    assert o._conn.queries == []


def test_select_reaches_com_and_connection_is_not_public():
    o = _oracle()
    with pytest.raises(RuntimeError, match="stub"):
        o.query("ВЫБРАТЬ 1")
    assert o._conn.queries == ["ВЫБРАТЬ 1"]
    assert not hasattr(o, "conn")


@pytest.mark.parametrize("bad", ['A" ИЛИ 1=1 --', "x\"; УДАЛИТЬ", "a b", ""])
def test_owner_csv_values_with_quotes_are_refused_before_a_query_is_built(bad):
    with pytest.raises(ValueError, match="unsafe"):
        native_checks._safe(bad, native_checks._SAFE_NUMBER, "invoice number")


def test_plain_owner_values_are_accepted():
    assert native_checks._safe("EBK000866266", native_checks._SAFE_NUMBER, "n") == "EBK000866266"
    assert native_checks._safe("211.1", native_checks._SAFE_CODE, "c") == "211.1"
    assert native_checks._safe("ORANGE MOLDOVA", native_checks._SAFE_NAME, "s") == "ORANGE MOLDOVA"


def test_csv_formula_cells_are_neutralised():
    cat = load_catalog(Path(__file__).resolve().parents[2] / "docs" / "REAL_1C_STORY_CATALOG_818HA.md")
    hostile = dataclasses.replace(cat.stories[0], title="=HYPERLINK(\"http://x\")")
    cat2 = dataclasses.replace(cat, stories=(hostile, *cat.stories[1:]))
    results = [
        {"schema_version": 1, "case_id": s.id, "kind": s.kind, "title": s.title, "catalogue_class": s.catalogue_class,
         "disposition": "INCONCLUSIVE", "reason_code": "x", "evidence_classes": ["NONE"],
         "observations": [{"probe": "p", "outcome": "o", "detail": "d"}], "tools_called": [], "oracle": "o",
         "git_sha": "a" * 40, "manifest_sha256": "b" * 64, "finished_at": "2026-10-07T10:00:00Z"}
        for s in cat2.stories
    ]
    first_row = build_csv(results, cat2).splitlines()[1]
    assert first_row.split(",")[1].startswith("'=") or "'=HYPERLINK" in first_row
