
import pytest

from business_ai_gateway.supplier_debt_summary import summarize_supplier_5211, supplier_refs

A = "70d8027a-942c-11ee-aa37-d85ed30dc416"
B = "ddea8b70-9054-11ee-aa37-d85ed30dc416"
CONTRACT = "47bca97c-d242-11ee-aa3e-d85ed30dc416"


def row(ref=A, credit="100.20", debit="0", account="521.1", currency=None):
    return {"account": account, "balance_credit": credit, "balance_debit": debit,
            "currency_ref": currency,
            "analytics": [
                {"role": "counterparty", "type": "Catalog.Контрагенты", "ref": ref},
                {"role": "contract", "type": "Catalog.ДоговорыКонтрагентов", "ref": CONTRACT},
            ]}


def test_complete_supplier_report_groups_credits_without_netting_debits():
    report = summarize_supplier_5211([row(), row(credit="17.10", debit="5.05"),
                                      row(ref=B, credit="0", debit="4.15")],
                                     names={A: "MOLDRETAIL", B: "Other"})
    assert report["status"] == "COMPLETE"
    assert report["total_balance_credit"] == "117.30"
    assert report["total_balance_debit"] == "9.20"
    assert report["suppliers"][0]["supplier_name"] == "MOLDRETAIL"
    assert report["suppliers"][0]["balance_credit"] == "117.30"
    assert report["suppliers"][0]["balance_debit"] == "5.05"
    assert report["not_an_aging_report"] is True
    assert report["netting_performed"] is False


def test_truncated_source_never_reports_a_total():
    result = summarize_supplier_5211([row()], truncated=True)
    assert result["status"] == "INCOMPLETE"
    assert "total_balance_credit" not in result
    assert summarize_supplier_5211([row()], max_rows=1)["status"] == "INCOMPLETE"


def test_other_account_never_pretends_to_be_5211():
    result = summarize_supplier_5211([row(account="211.1")])
    assert result["status"] == "NOT_APPLICABLE"
    assert result.get("suppliers") is None


@pytest.mark.parametrize("wrong", ["nan", "Infinity", "-1", "1e9999", "0x10"])
def test_invalid_amounts_fail_closed(wrong):
    with pytest.raises(ValueError, match="SUPPLIER_SUMMARY_INVALID_AMOUNT"):
        summarize_supplier_5211([row(credit=wrong)])


def test_missing_supplier_name_is_not_invented():
    report = summarize_supplier_5211([row()], names={})
    assert report["suppliers"][0]["supplier_name"] is None


def test_mixed_currency_never_sums_different_units():
    result = summarize_supplier_5211([row(), row(
        currency="019bbaa8-5131-11ee-aa2f-d85ed30dc416")])
    assert result["currency_status"] == "MIXED_NO_AGGREGATION"
    assert result["total_balance_credit"] is None


def test_guid_filter_inputs_extracted_only_from_confirmed_analytics():
    assert supplier_refs([row(), row()]) == [A]
    bad = row()
    bad["analytics"][0]["type"] = "Catalog.ЧужойТип"
    with pytest.raises(ValueError, match="SUPPLIER_SUMMARY_INVALID_ANALYTICS"):
        supplier_refs([bad])


def test_all_zero_is_zero_when_complete():
    report = summarize_supplier_5211([])
    assert report["status"] == "COMPLETE"
    assert report["total_balance_credit"] == "0"
    assert report["counterparty_count"] == 0


def test_very_large_decimal_sums_exactly_without_roundoff():
    from decimal import Decimal, localcontext
    huge = "99999999999999999999999999.99"
    report = summarize_supplier_5211([row(credit=huge) for _ in range(200)], max_rows=201)
    with localcontext() as ctx:
        ctx.prec = 80
        exact = format(Decimal(huge) * 200, "f")
    assert report["status"] == "COMPLETE"
    assert report["total_balance_credit"] == exact
    assert report["suppliers"][0]["balance_credit"] == exact


def test_null_contract_is_reported_as_incomplete_analytics_not_zero_debt():
    item = row()
    item["analytics"][1]["ref"] = None
    report = summarize_supplier_5211([item])
    assert report["status"] == "COMPLETE"
    assert report["suppliers"][0]["contract_refs"] == []
    assert report["suppliers"][0]["contract_refs_complete"] is False
