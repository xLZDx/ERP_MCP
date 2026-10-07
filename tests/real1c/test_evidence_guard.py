from __future__ import annotations

from unittest.mock import Mock

import pytest

from scripts.real1c.evidence import (
    ValidateRefused,
    assert_can_validate,
    guarded_validate,
    would_validate,
)

SHA = "a" * 64


def _cases(n, klass, *, start=0, sha=SHA):
    return [
        {"case_id": f"C{start + i}", "evidence_class": klass, "native_report_sha256": sha}
        for i in range(n)
    ]


def test_ten_com_cases_never_reach_validate():
    validate = Mock()
    manifest = {"cases": _cases(10, "NATIVE_COM_QUERY")}
    with pytest.raises(ValidateRefused):
        guarded_validate(manifest, validate)
    validate.assert_not_called()
    assert not would_validate(manifest)


def test_nine_ui_cases_refused():
    with pytest.raises(ValidateRefused):
        assert_can_validate({"cases": _cases(9, "NATIVE_UI_REPORT")})


def test_ten_distinct_ui_cases_pass_and_call_validate():
    validate = Mock(return_value="ok")
    manifest = {"cases": _cases(10, "NATIVE_UI_REPORT")}
    assert guarded_validate(manifest, validate) == "ok"
    validate.assert_called_once_with()
    assert would_validate(manifest)


def test_duplicates_do_not_count():
    manifest = {"cases": _cases(10, "NATIVE_UI_REPORT")[:9] * 3}
    assert not would_validate(manifest)


def test_ui_without_valid_sha_does_not_count():
    cases = _cases(9, "NATIVE_UI_REPORT") + _cases(1, "NATIVE_UI_REPORT", start=50, sha="xyz")
    assert not would_validate({"cases": cases})
    cases = _cases(9, "NATIVE_UI_REPORT") + [
        {"case_id": "C99", "evidence_class": "NATIVE_UI_REPORT"}
    ]
    assert not would_validate({"cases": cases})


def test_mixed_six_ui_plus_ten_com_refused():
    validate = Mock()
    manifest = {"cases": _cases(6, "NATIVE_UI_REPORT") + _cases(10, "NATIVE_COM_QUERY", start=100)}
    with pytest.raises(ValidateRefused):
        guarded_validate(manifest, validate)
    validate.assert_not_called()


@pytest.mark.parametrize("bad", [{}, {"cases": None}, {"cases": ["x"]}, None])
def test_malformed_manifest_refused(bad):
    assert not would_validate(bad)
