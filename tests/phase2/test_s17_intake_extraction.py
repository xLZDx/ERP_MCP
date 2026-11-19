from __future__ import annotations

from decimal import Decimal, localcontext

import pytest

from business_ai_gateway.phase2 import intake_extraction as intake
from business_ai_gateway.phase2.safe_parser import ParseResult, ParseStats, SheetValues, Status


def _missing_slots(cls: type, **values: object) -> object:
    instance = object.__new__(cls)
    for name, value in values.items():
        object.__setattr__(instance, name, value)
    return instance


@pytest.mark.parametrize("malformed", ["parse_result", "stats", "sheet"])
def test_incomplete_slotted_parser_records_fail_with_fixed_refusal(
    monkeypatch: pytest.MonkeyPatch, malformed: str,
) -> None:
    stats = ParseStats()
    sheet = SheetValues("csv", (("value",),))
    parsed = ParseResult(Status.OK, "OK", (sheet,), stats)
    if malformed == "parse_result":
        parsed = _missing_slots(ParseResult, status=Status.OK)
    elif malformed == "stats":
        partial_stats = _missing_slots(ParseStats, members=1)
        parsed = ParseResult(Status.OK, "OK", (sheet,), partial_stats)
    else:
        partial_sheet = _missing_slots(SheetValues, name="csv")
        parsed = ParseResult(Status.OK, "OK", (partial_sheet,), stats)

    monkeypatch.setattr(intake, "run_isolated", lambda *args, **kwargs: parsed)

    result = intake.extract_upload(b"bounded bytes", intake.UploadFormat.XLSX)

    assert result.state is intake.ExtractionState.REFUSED
    assert result.code == "MALFORMED_PARSE_RESULT"
    assert result.values == ()
    assert result.proposal_allowed is False


@pytest.mark.parametrize(
    ("includes_vat", "expected_multiplier"),
    [(True, 1), (False, 2)],
)
def test_explicit_total_is_exact_at_max_component_count_and_precision(
    includes_vat: bool, expected_multiplier: int,
) -> None:
    amount = "999999999999999999.999999"
    components = (amount,) * intake.MAX_TOTAL_COMPONENTS
    vats = (amount,) * intake.MAX_TOTAL_COMPONENTS
    with localcontext() as context:
        context.prec = 60
        expected = format(
            Decimal(amount) * intake.MAX_TOTAL_COMPONENTS * expected_multiplier,
            "f",
        )

    result = intake.cross_check_explicit_total(
        components,
        vats,
        expected,
        amount_currency="MDL",
        vat_currency="MDL",
        total_currency="MDL",
        includes_vat=includes_vat,
    )

    assert result.state is intake.TotalCheckState.MATCH_REVIEW
    assert result.computed_total == expected
    assert result.difference is not None
    assert Decimal(result.difference) == Decimal("0")
    assert result.proposal_allowed is False


@pytest.mark.parametrize("source_format", [intake.UploadFormat.PDF, intake.UploadFormat.IMAGE])
def test_pdf_and_image_remain_manual_review_only(source_format: intake.UploadFormat) -> None:
    result = intake.extract_upload(b"opaque unqualified document", source_format)

    assert result.state is intake.ExtractionState.BEST_EFFORT_REVIEW
    assert result.code == "MANUAL_REVIEW_ONLY"
    assert result.values == ()
    assert result.proposal_allowed is False


def test_mixed_currency_total_is_uncomputable_without_proposal() -> None:
    result = intake.cross_check_explicit_total(
        ("20.00",), ("1.82",), "21.82",
        amount_currency="MDL", vat_currency="EUR", total_currency="MDL",
        includes_vat=False,
    )

    assert result.state is intake.TotalCheckState.UNCOMPUTABLE_REVIEW
    assert result.code == "TOTAL_INPUT_UNSUPPORTED"
    assert result.computed_total is None
    assert result.proposal_allowed is False
