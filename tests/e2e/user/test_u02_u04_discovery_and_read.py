"""U02-U04 - discovery and bounded read for UC1 against the synthetic Fake1C.

Finding documented by `test_u02_company_grant_alone_does_not_open_source_level_tools`: the
baseline seed gives UC1 a company-one grant only, and the product's source-level tools
(source_health, onec_*) require a source-wide grant (`g.company_id IS NULL` in the registry).
The positive source-level cases therefore run under a temporary source-wide grant created and
removed through the Admin API (see GrantAdmin.temporary_source_wide). Company isolation (U05/U06)
is always exercised under the baseline company-scoped grants.
"""

from __future__ import annotations

import re
from collections import Counter

import httpx
import pytest
from user_support import (
    audit_since,
    completion_rows,
    db_clock,
    find_leaks,
    jsonable,
)

pytestmark = [pytest.mark.user]


def _fake_entity_sets(e2e_env) -> list[str]:
    xml = httpx.get(e2e_env.fake1c_url + "/$metadata", trust_env=False, timeout=10).text
    return re.findall(r'<EntitySet Name="([^"]+)"', xml)


# ------------------------------------------------------------------------------------- U02


async def test_u02_sources_and_companies_only_as_granted(e2e_env, call, tokens, ids):
    sources = await call(tokens["uc1"], "sources_list")
    assert sources.ok, sources.text
    assert [s["id"] for s in sources.payload] == [ids["source"]]
    companies = await call(tokens["uc1"], "companies_list", {"source_id": ids["source"]})
    assert companies.ok, companies.text
    assert [c["company_id"] for c in companies.payload] == [ids["one"]]  # not company two

    blob = jsonable([sources.payload, companies.payload])
    assert find_leaks(blob, e2e_env) == []
    assert "FAKE1C_USERNAME" not in blob and "FAKE1C_PASSWORD" not in blob  # no credential refs
    assert "secret" not in blob.lower() and "password" not in blob.lower()

    una = await call(tokens["una"], "sources_list")
    assert una.ok and una.payload == []  # nothing granted -> nothing listed


async def test_u02_company_grant_alone_does_not_open_source_level_tools(
        db, call, tokens, ids, fake1c_log):
    since, mark = await db_clock(db), fake1c_log.mark()
    outcome = await call(tokens["uc1"], "source_health", {"source_id": ids["source"]})
    assert outcome.is_error and outcome.payload is None
    rows = await audit_since(db, since, subject=ids["uc1"], tool="source_health")
    assert [r["outcome"] for r in rows] == ["denied"]
    assert fake1c_log.since(mark) == []  # denied before any upstream request


async def test_u02_source_health_reports_fake1c_reachable(
        e2e_env, db, call, tokens, ids, grants, fake1c_log):
    with grants.temporary_source_wide(ids["uc1"]):
        since, mark = await db_clock(db), fake1c_log.mark()
        health = await call(tokens["uc1"], "source_health", {"source_id": ids["source"]})
        sources = await call(tokens["uc1"], "sources_list")
    assert health.ok, health.text
    assert health.payload == {"status_code": 200, "ok": True}
    upstream = fake1c_log.since(mark)
    assert [(r["method"], r["path"].rsplit("/", 1)[-1]) for r in upstream] == [
        ("HEAD", "$metadata")]
    assert upstream[0]["had_authorization"] is True  # secret refs resolved by the gateway
    rows = await audit_since(db, since, subject=ids["uc1"], tool="source_health")
    assert [r["outcome"] for r in rows] == ["success", "success"]  # receipt + completion
    assert {r["source_id"] for r in rows} == {ids["source"]}
    blob = jsonable([health.payload, health.text, sources.payload])
    assert find_leaks(blob, e2e_env) == []
    assert "FAKE1C_" not in blob and "odata/standard.odata" not in blob


# ------------------------------------------------------------------------------------- U03


async def test_u03_capabilities_and_metadata_derive_from_observed_fake1c(
        e2e_env, call, tokens, ids, grants, fake1c_log):
    observed = _fake_entity_sets(e2e_env)
    assert observed, "Fake1C returned no EntitySets"
    expected_groups = dict(sorted(Counter(n.split("_", 1)[0] for n in observed).items()))
    with grants.temporary_source_wide(ids["uc1"]):
        mark = fake1c_log.mark()
        caps = await call(tokens["uc1"], "onec_capabilities",
                          {"source_id": ids["source"], "refresh": True})
        summary = await call(tokens["uc1"], "onec_metadata_summary",
                             {"source_id": ids["source"], "refresh": True})
        found = await call(tokens["uc1"], "onec_find_entities",
                           {"source_id": ids["source"], "contains": "", "limit": 200})
        nothing = await call(tokens["uc1"], "onec_find_entities",
                             {"source_id": ids["source"], "contains": "NoSuchEntity_zzz"})
    for outcome in (caps, summary, found, nothing):
        assert outcome.ok, (outcome.tool, outcome.text)

    assert caps.payload["metadata_supported"] is True
    assert caps.payload["entity_set_count"] == len(observed)
    assert caps.payload["metadata_fingerprint"]  # derived from the observed $metadata
    assert summary.payload["entity_set_count"] == len(observed)
    assert summary.payload["groups"] == expected_groups
    assert sorted(item["name"] for item in found.payload) == sorted(observed)  # only synthetic
    assert nothing.payload == []  # no guessed entity or register name
    assert fake1c_log.all_methods_read_only(mark)


# ------------------------------------------------------------------------------------- U04


async def test_u04_onec_read_returns_only_requested_fields_and_bounded_rows(
        db, call, tokens, ids, grants, fake1c_log):
    fields = ["Ref_Key", "Description"]
    with grants.temporary_source_wide(ids["uc1"]):
        since, mark = await db_clock(db), fake1c_log.mark()
        outcome = await call(tokens["uc1"], "onec_read", {
            "source_id": ids["source"], "entity_set": "Catalog_Organizations",
            "select": fields, "top": 1})
    assert outcome.ok, outcome.text
    rows = outcome.payload["value"]
    assert len(rows) == 1
    assert all(set(row) == set(fields) for row in rows), rows  # no unrelated fields

    upstream = fake1c_log.since(mark)
    reads = [r for r in upstream if r["path"].endswith("Catalog_Organizations")]
    assert reads and all(r["method"] == "GET" for r in reads)
    assert any("$select" in r["query_keys"] and r["numeric_params"].get("$top") == 1
               for r in reads), reads
    assert fake1c_log.all_methods_read_only(mark)  # no write verb ever reaches Fake1C

    completion = completion_rows(await audit_since(db, since, subject=ids["uc1"],
                                                   tool="onec_read"))
    assert [r["outcome"] for r in completion] == ["success"]
    assert completion[0]["returned_items"] == 1
