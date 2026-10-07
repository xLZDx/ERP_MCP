"""Authorization and company/source isolation negatives (dev mode + needs-oidc-identity cases).

Dev mode has one fixed principal, so the grant is manipulated with scripts/admin.py (revoke and
re-add the EXACT grant) and restored in `finally`. Cases that need a second identity activate only
when FT_BEARER_TOKEN_NO_ACCESS / FT_BEARER_TOKEN_COMPANY_TWO are provided.
"""

from __future__ import annotations

import pytest

from tests.functional.support import harness as h
from tests.functional.support.evidence import record

DEV_MODE = not h.env("FT_BEARER_TOKEN")
needs_dev = pytest.mark.skipif(not DEV_MODE, reason="grant manipulation via admin.py is a dev-mode case")

SALES = {"source_id": h.SOURCE_ID, "company_id": h.COMPANY_ONE}


def _revoke(company: str | None = None):
    extra = ["--company-id", company] if company else []
    h.admin_cli("grant-revoke", "--kind", "subject", "--principal", h.PRINCIPAL, "--source-id", h.SOURCE_ID, *extra)


def _add(company: str | None = None):
    extra = ["--company-id", company] if company else []
    h.admin_cli("grant-add", "--kind", "subject", "--principal", h.PRINCIPAL, "--source-id", h.SOURCE_ID, *extra)


@needs_dev
async def test_revoked_source_grant_denies_before_any_upstream_request_and_restores():
    _revoke()
    try:
        out = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": "Document_Sales", "top": 5})
        assert out.is_error
        last = h.final_audit(out)
        assert (last["outcome"], last["detail_code"]) == ("denied", "AccessDenied")
        assert out.upstream == [], "denied call reached 1C"
        listed = await h.call("sources_list")
        assert listed.ok and listed.data == []
        biz = await h.call("sales_documents", SALES)
        assert biz.is_error and h.final_audit(biz)["detail_code"] == "AccessDenied" and biz.upstream == []
        record("SC04", negative_revoked_grant="source grant revoked -> AccessDenied, zero upstream requests",
               audit_negative=[{"tool": "onec_read", "outcome": "denied", "detail": "AccessDenied"}])
    finally:
        _add()
    again = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": "Document_Sales", "top": 1})
    assert again.ok, "grant re-add must restore access without gateway restart"


@needs_dev
async def test_company_scoped_grant_isolates_company_two_from_company_one():
    _revoke()
    _add(h.COMPANY_TWO)
    try:
        one = await h.call("sales_documents", SALES)
        assert one.is_error and h.final_audit(one)["detail_code"] == "AccessDenied"
        assert str(h.final_audit(one)["company_id"]) == h.COMPANY_ONE and one.upstream == []
        two = await h.call("sales_documents", {**SALES, "company_id": h.COMPANY_TWO})
        # ACL passes for company two and returns ONLY company two's documents.
        assert two.ok
        codes = [r["detail_code"] for r in two.audit]
        assert "ACCESS_AUTHORIZED" in codes and "AccessDenied" not in codes
        numbers = {r["document_number"] for r in two.data["value"]}
        assert numbers.isdisjoint({"SALE-001", "SALE-003", "SALE-004"}), numbers
        record("SC04", negative_company_scope="company-two-only grant: company one AccessDenied, company two passes ACL")
        record("SC09", negative_company_scope="company-two-only grant: company one AccessDenied")
    finally:
        _revoke(h.COMPANY_TWO)
        _add()
    assert (await h.call("companies_list", {"source_id": h.SOURCE_ID})).ok


async def test_unknown_source_and_company_source_mismatch_denied():
    out = await h.call("sales_documents", {"source_id": "no-such-source", "company_id": h.COMPANY_ONE})
    assert out.is_error and h.final_audit(out)["detail_code"] == "AccessDenied" and out.upstream == []
    out = await h.call("sales_documents", {"source_id": h.SOURCE_ID, "company_id": "not-a-uuid"})
    assert out.is_error and h.final_audit(out)["detail_code"] == "INVALID_COMPANY_ID" and out.upstream == []
    record("SC04", negative_scope="unknown source and malformed/foreign company id denied pre-dispatch")


async def test_unsupported_entities_fail_closed_without_guessing():
    # Outside the source allow-list (Catalog_/Document_/AccumulationRegister_ only).
    a = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": "InformationRegister_Guess"})
    assert a.is_error and h.final_audit(a)["detail_code"] == "PermissionError"
    assert not [r for r in a.upstream if "InformationRegister" in r["path"]]
    # Allowed pattern but absent from live metadata: must not be fetched.
    b = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": "Document_Guess"})
    assert b.is_error and h.final_audit(b)["detail_code"] == "ValueError"
    assert not [r for r in b.upstream if "Document_Guess" in r["path"]]
    # Path-traversal style entity names are rejected before transport.
    c = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": "Document_Sales/../x"})
    assert c.is_error and not [r for r in c.upstream if ".." in r["path"]]
    record("SC08", negative_unsupported_entity="allow-list and live-metadata gates reject guessed entity names")


async def test_mutation_surface_absent_and_no_write_reaches_1c():
    names = await h.list_tool_names()
    import re
    assert not [n for n in names if re.search(r"create|update|delete|post_|write|merge|insert|set_", n)], names
    out = await h.call("onec_post_document", {"source_id": h.SOURCE_ID})
    assert out.is_error and "Unknown tool" in out.text and out.upstream == []
    # Injection attempt inside a read filter must still be a GET with the string only in query.
    inj = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": "Document_Sales",
                                     "filter_expr": "Posted eq true; DELETE", "top": 1})
    assert h.no_write_reached_1c(inj)
    record("SC08", no_write="no mutation tool exists; probe + injected filter produced GET/HEAD only")


@pytest.mark.skipif(not h.env("FT_BEARER_TOKEN_NO_ACCESS"), reason="needs-oidc-identity: set FT_BEARER_TOKEN_NO_ACCESS")
async def test_oidc_identity_without_grants_is_denied():
    tok = h.env("FT_BEARER_TOKEN_NO_ACCESS")
    listed = await h.call("sources_list", token=tok)
    assert listed.ok and listed.data == []
    out = await h.call("sales_documents", SALES, token=tok)
    assert out.is_error and h.final_audit(out)["detail_code"] == "AccessDenied" and out.upstream == []


@pytest.mark.skipif(not h.env("FT_BEARER_TOKEN_COMPANY_TWO"), reason="needs-oidc-identity: set FT_BEARER_TOKEN_COMPANY_TWO")
async def test_oidc_company_two_identity_cannot_read_company_one():
    tok = h.env("FT_BEARER_TOKEN_COMPANY_TWO")
    out = await h.call("sales_documents", SALES, token=tok)
    assert out.is_error and h.final_audit(out)["detail_code"] == "AccessDenied" and out.upstream == []


@pytest.mark.skipif(not h.env("FT_EXPECT_CAPABILITY_ENFORCEMENT") or not h.env("FT_BEARER_TOKEN_NO_ACCESS"),
                    reason="needs-oidc-identity + business-capability enforcement environment (E2E)")
async def test_business_capability_denied_for_identity_without_capability():
    out = await h.call("onec_read", {"source_id": h.SOURCE_ID, "entity_set": "Document_Sales"},
                       token=h.env("FT_BEARER_TOKEN_NO_ACCESS"))
    assert out.is_error and out.upstream == []
