"""Public-report sanitizer: private business figures must not survive into any committed artifact form."""

from __future__ import annotations

import html
import json
from pathlib import Path

import pytest

from scripts.real1c import documentation
from scripts.real1c.catalog import load_catalog
from scripts.real1c.details_report import build_details
from scripts.real1c.sanitize import money_literals, public_copy, redact_business_values

CATALOG = Path(__file__).resolve().parents[2] / "docs" / "REAL_1C_STORY_CATALOG_818HA.md"
AMOUNTS = ["123456.78", "-4321.09", "987.65", "55,555.55", "22222.22"]
SUPPLIER, INVOICE = "ACMEFOOD", "ZZ12345"


@pytest.mark.parametrize("amount", AMOUNTS)
def test_monetary_values_are_removed(amount):
    out = redact_business_values(f'{{"x": "{amount}"}} gateway={amount} com={amount}')
    assert amount not in out and "<amount>" in out


def test_non_monetary_numbers_survive():
    text = "answered in 6.76s; 1184 tables; account 216.1; version 8.3.27.2342; 2026-08-31"
    assert redact_business_values(text) == text


def test_query_literals_for_amounts_suppliers_and_invoice_numbers_are_masked():
    query = (f'ВЫБРАТЬ 1 ГДЕ Т.Сумма = 987.65 И Т.НомерВходящегоДокумента = "{INVOICE}" И Т.Наименование ПОДОБНО "%{SUPPLIER}%"')
    cleaned = documentation.clean_query(query)
    assert "987.65" not in cleaned and INVOICE not in cleaned and SUPPLIER not in cleaned


def test_every_artifact_form_is_free_of_canaries():
    cat = load_catalog(CATALOG)
    result = {"schema_version": 1, "case_id": "NR-02", "kind": "NR", "title": "t", "catalogue_class": "EV",
              "disposition": "EVIDENCE_REQUIRED", "reason_code": "com_agrees_native_ui_report_required",
              "evidence_classes": ["NATIVE_COM_QUERY"], "tools_called": [], "oracle": "o", "git_sha": "a" * 40,
              "manifest_sha256": "b" * 64, "finished_at": "2026-10-07T10:00:00+03:00",
              "observations": [{"probe": "p", "outcome": "AGREES", "detail": " ".join(f"v={a}" for a in AMOUNTS)}],
              "queries": [{"text": documentation.clean_query(f'Т.Сумма = 216 И Т.Наименование ПОДОБНО "%{SUPPLIER}%"')}],
              "calls": [], "calls_total": 0, "channel_note": ""}
    public = public_copy(result)
    blobs = [json.dumps(public, ensure_ascii=False),
             build_details([public], cat, "a" * 40, "2026-10-07T10:00:00+03:00", lang="en", summary_href="x.html"),
             build_details([public], cat, "a" * 40, "2026-10-07T10:00:00+03:00", lang="ru", summary_href="x.html")]
    for blob in blobs:
        for canary in [*AMOUNTS, SUPPLIER, INVOICE]:
            for form in (canary, html.escape(canary), json.dumps(canary)[1:-1], canary.replace(".", ",")):
                assert form not in blob, (canary, form)


def test_money_literals_feed_the_output_sweep():
    found = money_literals('detail "123456.78" and 0.00 and 1.5 and 6.76s and -4321.09')
    assert found == {"123456.78", "-4321.09"}
