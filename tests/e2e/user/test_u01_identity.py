"""U01 - token acceptance and principal binding over the public MCP endpoint."""

from __future__ import annotations

import pytest
from user_support import audit_since, call_tool, db_clock, raw_initialize

pytestmark = [pytest.mark.user]


def _tamper_signature(token: str) -> str:
    head, payload, signature = token.split(".")
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    return f"{head}.{payload}.{flipped}"


async def test_u01_valid_token_binds_principal_and_audit_actor(e2e_env, db, call, tokens, ids):
    since = await db_clock(db)
    uc1 = await call(tokens["uc1"], "system_status")
    uc2 = await call(tokens["uc2"], "system_status")
    assert uc1.ok and uc2.ok, (uc1.text, uc1.transport_error, uc2.text, uc2.transport_error)
    assert uc1.payload["subject"] == ids["uc1"]
    assert uc2.payload["subject"] == ids["uc2"]  # UC1 never appears as UC2 (and vice versa)

    rows = [r for r in await audit_since(db, since, tool="system_status")]
    by_subject = {}
    for row in rows:
        by_subject.setdefault(row["principal_subject"], []).append(row)
    assert set(by_subject) == {ids["uc1"], ids["uc2"]}, sorted(by_subject)
    for subject, subject_rows in by_subject.items():
        assert [r["outcome"] for r in subject_rows] == ["success"], subject
        assert subject_rows[0]["client_id"] == e2e_env.raw["idp"]["headless_client_id"]
        assert subject_rows[0]["request_id"]


async def test_u01_user_without_grants_authenticates_but_has_no_sources(call, tokens, ids):
    outcome = await call(tokens["una"], "system_status")
    assert outcome.ok, (outcome.text, outcome.transport_error)
    assert outcome.payload["subject"] == ids["una"]
    assert outcome.payload["accessible_sources"] == 0


async def test_u01_caller_supplied_identity_is_ignored(db, call, tokens, ids):
    since = await db_clock(db)
    outcome = await call(tokens["uc1"], "system_status", {"subject": ids["uc2"],
                                                          "principal": ids["uc2"]})
    if outcome.ok:  # extra arguments tolerated: they must have no effect
        assert outcome.payload["subject"] == ids["uc1"]
    rows = await audit_since(db, since)
    assert ids["uc2"] not in {r["principal_subject"] for r in rows}


def test_u01_rejected_tokens_get_401_and_the_valid_one_gets_200(e2e_env, idp, ids):
    valid = idp.token(ids["uc1"])
    # Instrument check first: the bare initialize request is accepted for a valid token, so a
    # 401 below can only come from the token, not from a malformed request.
    assert raw_initialize(e2e_env.mcp_url, valid).status_code == 200

    wrong_audience = idp.token(ids["uc1"], audience="admin", scope="onec:read")
    expired = idp.token(ids["uc1"], ttl=-120)
    bad_signature = _tamper_signature(valid)
    cases = {"wrong-audience": wrong_audience, "expired": expired,
             "bad-signature": bad_signature, "no-token": None, "garbage": "not-a-jwt"}
    statuses = {name: raw_initialize(e2e_env.mcp_url, token).status_code
                for name, token in cases.items()}
    assert statuses == dict.fromkeys(cases, 401), statuses


async def test_u01_rejected_token_never_reaches_a_tool(e2e_env, db, idp, mcp_client, ids):
    since = await db_clock(db)
    outcome = await call_tool(mcp_client, idp.token(ids["uc1"], ttl=-120), "system_status")
    assert outcome.is_error and outcome.transport_error and outcome.payload is None
    assert await audit_since(db, since, tool="system_status") == []
