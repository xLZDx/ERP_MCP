"""Supplier receipts (real 818 HA shape): profile-owned filters and exact per-currency totals."""
from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

from business_ai_gateway.analytics_balance import AnalyticsBalanceError, summarize_document_amounts
from business_ai_gateway.fixture_profiles import ProvisionalProfiles
from business_ai_gateway.registry import Registry
from business_ai_gateway.semantic import build_document_filter, normalize_document_rows

PROFILE = Path(__file__).resolve().parents[1] / "testbed" / "real1c" / "provisional_profiles_818ha.json"
COMPANY = uuid.UUID("3e31afc5-351f-4f36-8074-99129fa3d911")
ORG = "019bbaa8-5131-11ee-aa2f-d85ed30dc416"
MOLDRETAIL = "70d8027a-942c-11ee-aa37-d85ed30dc416"
MDL = "6d74f7a9-5098-11ee-aa2f-d85ed30dc416"


@pytest.fixture(scope="module")
def mapping():
    provider = ProvisionalProfiles(PROFILE, hashlib.sha256(PROFILE.read_bytes()).hexdigest(), environment="test")
    return provider.lookup("onec-818ha-reference", COMPANY, "purchases")


def native(number, date, amount, posted=True, currency=MDL):
    return {"Ref_Key": str(uuid.uuid4()), "Number": number, "Date": date, "Контрагент_Key": MOLDRETAIL,
            "СуммаДокумента": amount, "ВалютаДокумента_Key": currency, "Posted": posted}


def test_committed_profile_passes_the_shared_validator(mapping):
    Registry.check_concept_mapping("purchases", mapping)


def test_filter_is_company_counterparty_and_posted_with_profile_names(mapping):
    flt = build_document_filter(mapping, ORG, counterparty_ref=MOLDRETAIL.upper(), posted_only=True)
    assert flt == (f"Организация_Key eq guid'{ORG}' and Контрагент_Key eq guid'{MOLDRETAIL}' "
                   "and Posted eq true")
    assert build_document_filter(mapping, ORG) == f"Организация_Key eq guid'{ORG}'"


@pytest.mark.parametrize("bad", ["x", "' or 1 eq 1 or '", "", 7, MOLDRETAIL + " or Posted eq false"])
def test_counterparty_ref_must_be_a_guid(mapping, bad):
    with pytest.raises(ValueError):
        build_document_filter(mapping, ORG, counterparty_ref=bad)


def test_receipt_rows_and_totals_match_the_real_moldretail_documents(mapping):
    rows = normalize_document_rows([
        native("0000-00000186", "2026-08-31T07:00:00", 21510.29),
        native("0000-00000156", "2026-07-31T07:00:00", 25125.91),
    ], mapping, "purchases")

    assert rows[0]["document_number"] == "0000-00000186" and rows[0]["posted"] is True
    assert summarize_document_amounts(rows) == [{"currency": MDL, "amount": "46636.2", "document_count": 2}]


def test_totals_are_separated_per_currency_and_exact():
    rows = [{"currency": "a", "amount": 0.1}, {"currency": "a", "amount": 0.2}, {"currency": "b", "amount": 5}]
    assert summarize_document_amounts(rows) == [
        {"currency": "a", "amount": "0.3", "document_count": 2},
        {"currency": "b", "amount": "5", "document_count": 1},
    ]
    assert Decimal(summarize_document_amounts(rows)[0]["amount"]) == Decimal("0.3")


def test_malformed_amount_fails_closed():
    with pytest.raises(AnalyticsBalanceError):
        summarize_document_amounts([{"currency": "a", "amount": "NaN"}])
