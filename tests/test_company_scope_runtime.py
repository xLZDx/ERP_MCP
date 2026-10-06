from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from business_ai_gateway.company_scope import (
    CompanyScopeMapping,
    CompanyScopeResolver,
    CompanyScopeUnavailable,
)
from business_ai_gateway.models import Company


def company(external_ref="c6ae9800-c10e-46e1-bd82-1be1ea93add8"):
    return Company(
        id=UUID("56d6426c-aeee-4c65-ab8e-cb5a38c8a15f"),
        source_id="s1",
        external_ref=external_ref,
        display_name="A",
        legal_name=None,
        country_code="MD",
        enabled=True,
        is_default=False,
    )


def mapping(kind="guid"):
    return CompanyScopeMapping(
        profile_id=UUID("c2331f1e-11d4-436c-8921-404648701807"),
        entity_set="Document_Sale",
        company_property="Организация_Key",
        literal_kind=kind,
        profile_fingerprint="profile-fp",
    )


def test_guid_filter_is_server_constructed_from_company_external_ref():
    result = CompanyScopeResolver.filter_for(mapping(), company())

    assert result == (
        "Организация_Key eq guid'c6ae9800-c10e-46e1-bd82-1be1ea93add8'"
    )


def test_string_filter_escapes_odata_string_literal():
    result = CompanyScopeResolver.filter_for(mapping("string"), company("ACME 'MD'"))

    assert result == "Организация_Key eq 'ACME ''MD'''"


def test_company_filter_is_always_parenthesized_before_caller_filter():
    result = CompanyScopeResolver.combine("Org eq 'A'", "Amount gt 0 or Amount lt -1")

    assert result == "(Org eq 'A') and (Amount gt 0 or Amount lt -1)"


@pytest.mark.parametrize("caller", ["Amount gt 0) or true or (Amount gt 0", "Name eq 'x", "((Amount gt 0)"])
def test_caller_filter_cannot_escape_server_company_predicate(caller):
    with pytest.raises(CompanyScopeUnavailable):
        CompanyScopeResolver.combine("Org eq 'A'", caller)


def test_caller_filter_accepts_parentheses_inside_escaped_string():
    assert CompanyScopeResolver.combine("Org eq 'A'", "Name eq 'O''Brien (MD)' and (Amount gt 0)")


def test_invalid_guid_fails_closed():
    with pytest.raises(CompanyScopeUnavailable):
        CompanyScopeResolver.filter_for(mapping(), company("not-a-guid"))


def test_live_metadata_must_contain_mapped_company_property():
    index = SimpleNamespace(
        entities=[
            SimpleNamespace(name="Document_Sale", properties=("Ref_Key", "Организация_Key"))
        ]
    )
    CompanyScopeResolver.verify_metadata_property(
        index, entity_set="Document_Sale", property_name="Организация_Key"
    )

    with pytest.raises(CompanyScopeUnavailable):
        CompanyScopeResolver.verify_metadata_property(
            index, entity_set="Document_Sale", property_name="Missing"
        )
