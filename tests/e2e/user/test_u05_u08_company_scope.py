"""U05-U08 - company isolation, group-grant access and denial of users without access.

All four rows run under the BASELINE seed: UC1 has a company-one subject grant, the
company-two-readers group has a company-two grant, UNA has nothing. The environment runs the
reviewed synthetic fixture profile (BAG_ENVIRONMENT=test, source tag synthetic-fixture), so the
company-scoped business tools return real rows (L1 synthetic evidence, never native
reconciliation). Row content is asserted against the committed Fake1C seed, together with:

* the access decision through the authorization receipt in the audit log (`ACCESS_AUTHORIZED`,
  written only after the grants allow the exact source+company);
* the absence/presence of upstream Fake1C traffic for denied calls.
"""

from __future__ import annotations

import json
import re

import jwt
import pytest
from user_support import (
    E2E_DIR,
    audit_since,
    db_clock,
    find_leaks,
    jsonable,
    receipts,
    run_fault,
    seed,
    wait_until,
)

pytestmark = [pytest.mark.user]

def _sales_args(ids, company: str) -> dict:
    return {"source_id": ids["source"], "company_id": company, "top": 20}


def _doc_numbers_for(company: str) -> set[str]:
    return {row["Number"] for row in seed()["sales"] if row["Организация_Key"] == company}


# ------------------------------------------------------------------------------------- U05


async def test_u05_uc1_sees_only_company_one_and_is_authorized_for_it(
        db, call, tokens, ids, fake1c_log):
    companies = await call(tokens["uc1"], "companies_list", {"source_id": ids["source"]})
    assert companies.ok, companies.text
    assert [c["company_id"] for c in companies.payload] == [ids["one"]]
    assert ids["two"] not in jsonable(companies.payload)

    since = await db_clock(db)
    await call(tokens["uc1"], "sales_documents", _sales_args(ids, ids["one"]))
    rows = await audit_since(db, since, subject=ids["uc1"], tool="sales_documents")
    assert [str(r["company_id"]) for r in receipts(rows)] == [ids["one"]]  # authorized: company one
    assert {str(r["company_id"]) for r in rows} == {ids["one"]}  # never company two


async def test_u05_company_one_rows_are_exactly_the_company_one_documents(
        db, call, tokens, ids):
    outcome = await call(tokens["uc1"], "sales_documents", _sales_args(ids, ids["one"]))
    assert outcome.ok, outcome.text
    assert outcome.payload["company_id"] == ids["one"]
    assert outcome.payload["profile_kind"] == "SYNTHETIC_FIXTURE"  # L1 synthetic, not native
    assert outcome.payload["native_reconciliation"] == "NOT_RUN"
    numbers = {row["document_number"] for row in outcome.payload["value"]}
    assert numbers == _doc_numbers_for(ids["one"]) != set(), numbers  # all of them, only them
    assert not numbers & _doc_numbers_for(ids["two"])


# ------------------------------------------------------------------------------------- U06


async def test_u06_uc1_is_denied_company_two_before_any_fake1c_request(
        e2e_env, db, call, tokens, ids, fake1c_log):
    since, mark = await db_clock(db), fake1c_log.mark()
    outcome = await call(tokens["uc1"], "sales_documents", _sales_args(ids, ids["two"]))
    assert outcome.is_error and outcome.payload is None
    assert not any(n in outcome.text for n in ("SALE-", "PUR-", "Synthetic"))
    assert find_leaks(outcome.text, e2e_env) == []

    rows = await audit_since(db, since, subject=ids["uc1"], tool="sales_documents")
    assert [r["outcome"] for r in rows] == ["denied"], rows
    assert str(rows[0]["company_id"]) == ids["two"] and rows[0]["detail_code"]
    assert receipts(rows) == []  # no authorization receipt for company two
    assert fake1c_log.since(mark, gateway_only=False) == []  # denial precedes any upstream call


async def test_u06_uc2_group_grant_authorizes_company_two_only(
        db, call, tokens, ids, fake1c_log):
    since = await db_clock(db)
    allowed = await call(tokens["uc2"], "sales_documents", _sales_args(ids, ids["two"]))
    assert allowed.ok, allowed.text
    mark = fake1c_log.mark()
    denied = await call(tokens["uc2"], "sales_documents", _sales_args(ids, ids["one"]))
    assert denied.is_error and denied.payload is None
    assert fake1c_log.since(mark, gateway_only=False) == []

    rows = await audit_since(db, since, subject=ids["uc2"], tool="sales_documents")
    assert [str(r["company_id"]) for r in receipts(rows)] == [ids["two"]]
    assert [r["outcome"] for r in rows if str(r["company_id"]) == ids["one"]] == ["denied"]
    companies = await call(tokens["uc2"], "companies_list", {"source_id": ids["source"]})
    assert [c["company_id"] for c in companies.payload] == [ids["two"]]


async def test_u06_company_two_rows_for_uc2_only(db, call, tokens, ids):
    outcome = await call(tokens["uc2"], "sales_documents", _sales_args(ids, ids["two"]))
    assert outcome.ok, outcome.text  # UC2 (group grant) reads company two
    assert outcome.payload["company_id"] == ids["two"]
    numbers = {row["document_number"] for row in outcome.payload["value"]}
    assert numbers == _doc_numbers_for(ids["two"]) != set(), numbers
    assert not numbers & _doc_numbers_for(ids["one"])
    uc1 = await call(tokens["uc1"], "sales_documents", _sales_args(ids, ids["two"]))
    assert uc1.is_error and uc1.payload is None  # UC1 is denied company two


# ------------------------------------------------------------------------------------- U07

_UNA_CALLS = (
    ("source_health", lambda i: {"source_id": i["source"]}),
    ("companies_list", lambda i: {"source_id": i["source"]}),
    ("onec_capabilities", lambda i: {"source_id": i["source"]}),
    ("onec_read", lambda i: {"source_id": i["source"], "entity_set": "Catalog_Organizations",
                             "top": 1}),
    ("sales_documents", lambda i: {"source_id": i["source"], "company_id": i["one"]}),
    ("bank_balance", lambda i: {"source_id": i["source"], "company_id": i["one"],
                                "period": "2026-04-30T00:00:00"}),
)


@pytest.mark.parametrize(("tool", "make_args"), _UNA_CALLS, ids=[c[0] for c in _UNA_CALLS])
async def test_u07_user_without_access_is_denied_with_sanitized_error(
        e2e_env, db, call, tokens, ids, fake1c_log, tool, make_args):
    since, mark = await db_clock(db), fake1c_log.mark()
    outcome = await call(tokens["una"], tool, make_args(ids))
    if tool == "companies_list":  # list-style tool: empty result is the denial
        assert outcome.is_error or outcome.payload == []
    else:
        assert outcome.is_error and outcome.payload is None, outcome
    blob = outcome.text + jsonable(outcome.payload)
    assert not any(n in blob for n in ("Synthetic", "SALE-", "Ref_Key", ids["one"]))
    assert find_leaks(blob, e2e_env) == []
    assert fake1c_log.since(mark, gateway_only=False) == []

    rows = await audit_since(db, since, subject=ids["una"], tool=tool)
    if tool == "companies_list":
        # The list tool filters instead of failing: the audited outcome is a successful call that
        # returned ZERO items (nothing about the source/companies is revealed).
        assert rows and {r["outcome"] for r in rows} == {"success"}, rows
        assert all(r["returned_items"] == 0 for r in rows), rows
    else:
        assert rows and {r["outcome"] for r in rows} <= {"denied", "error"}, rows
        assert any(r["outcome"] == "denied" for r in rows), rows
    assert all(r["detail_code"] != "ACCESS_AUTHORIZED" for r in rows)  # never authorized


async def test_u07_denial_does_not_reveal_whether_a_source_exists(call, tokens, ids):
    real = await call(tokens["una"], "source_health", {"source_id": ids["source"]})
    fake = await call(tokens["una"], "source_health", {"source_id": "no-such-source-e2e"})
    assert real.is_error and fake.is_error

    def normalised(outcome, source_id):
        return re.sub(re.escape(source_id), "<SOURCE>", outcome.text)

    assert normalised(real, ids["source"]) == normalised(fake, "no-such-source-e2e")


async def authorised_for_company_two(db, call, token, ids) -> bool:
    """True when the exact source+company-two access was authorized (receipt in audit)."""
    since = await db_clock(db)
    await call(token, "sales_documents", _sales_args(ids, ids["two"]))
    rows = await audit_since(db, since, subject=ids["uc2"], tool="sales_documents")
    return bool(receipts(rows))


# ------------------------------------------------------------------------------------- U08


def _claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


async def test_u08_group_membership_is_the_only_basis_and_removal_denies(
        e2e_env, db, call, idp, ids):
    group = "erp-company-two-readers"
    config_path = E2E_DIR / "idp-config.json"
    original = config_path.read_bytes()
    config = json.loads(original)
    assert group in config["groups"][ids["uc2"]]

    old_token = idp.token(ids["uc2"])
    assert group in _claims(old_token)["groups"]
    assert await authorised_for_company_two(db, call, old_token, ids)  # allowed via group grant only

    config["groups"][ids["uc2"]] = []
    try:
        config_path.write_bytes(json.dumps(config, indent=2).encode("utf-8"))
        run_fault("idp", "restart")
        wait_until(lambda: idp.token(ids["uc2"]), timeout=30, what="IdP serving tokens")
        new_token = idp.token(ids["uc2"])
        assert _claims(new_token)["groups"] == []
        since = await db_clock(db)
        denied = await call(new_token, "sales_documents", _sales_args(ids, ids["two"]))
        assert denied.is_error and denied.payload is None
        rows = await audit_since(db, since, subject=ids["uc2"], tool="sales_documents")
        assert [r["outcome"] for r in rows] == ["denied"] and receipts(rows) == []
        assert (await call(new_token, "companies_list", {"source_id": ids["source"]})
                ).payload in ([], None)

        # Documented stale-group behaviour (not widened): a token minted BEFORE the removal
        # carries its own group snapshot and stays valid until it expires; only new tokens change.
        assert await authorised_for_company_two(db, call, old_token, ids)
    finally:
        config_path.write_bytes(original)
        run_fault("idp", "restart")
        wait_until(lambda: group in _claims(idp.token(ids["uc2"]))["groups"], timeout=30,
                   what="IdP restored with the original group")
