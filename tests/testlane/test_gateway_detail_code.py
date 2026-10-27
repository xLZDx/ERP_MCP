"""The test lane names a gateway refusal by its bare code and never carries free text."""
from __future__ import annotations

import json

import pytest

from testlane.phase2_mcp.gateway_client import _safe_detail_code


def _text_result(body: object) -> dict:
    return {"isError": True, "content": [{"type": "text", "text": body if isinstance(body, str) else json.dumps(body)}]}


def test_refusal_code_is_read_from_the_json_text_of_the_first_content_item() -> None:
    result = _text_result({"error": {"code": "SEMANTIC_PROFILE_UNVALIDATED", "safe_message": "no profile"}})
    assert _safe_detail_code(result) == "SEMANTIC_PROFILE_UNVALIDATED"


def test_refusal_code_is_read_from_structured_content() -> None:
    result = {"isError": True, "structuredContent": {"error": {"code": "SOURCE_UNAVAILABLE"}}}
    assert _safe_detail_code(result) == "SOURCE_UNAVAILABLE"


@pytest.mark.parametrize("text", [
    "Error executing tool purchase_documents: 2 validation errors",
    "{not json",
    json.dumps({"error": {"code": "lower_case_code"}}),
    json.dumps({"error": {"code": "HAS SPACE AND TEXT"}}),
    json.dumps({"error": {"code": "A" * 80}}),
    json.dumps({"error": "SEMANTIC_PROFILE_UNVALIDATED"}),
    json.dumps(["SEMANTIC_PROFILE_UNVALIDATED"]),
])
def test_free_text_and_malformed_errors_yield_no_detail(text: str) -> None:
    assert _safe_detail_code(_text_result(text)) is None


def test_missing_content_yields_no_detail() -> None:
    assert _safe_detail_code({"isError": True}) is None
    assert _safe_detail_code({"isError": True, "content": []}) is None
