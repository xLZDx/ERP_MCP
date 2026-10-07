"""U11-U13 - unsupported entity, unconfirmed business capability, and bounded results.

Source-level reads (onec_read) need a source-wide grant for UC1 (see the module docstring of
test_u02_u04_discovery_and_read.py); U12 business tools run under the baseline company grant.
"""

from __future__ import annotations

import re

import pytest
from user_support import (
    audit_since,
    completion_rows,
    db_clock,
    find_leaks,
    seed,
)

pytestmark = [pytest.mark.user]

REGISTER_WORDS = ("Balance", "Movements")
UNSUPPORTED_CODES = re.compile(
    r"^(SEMANTIC_\w+|CAPABILITY_\w+|METADATA_\w+|Semantic\w+|Capability\w+|MetadataDrift\w+)$")


# ------------------------------------------------------------------------------------- U11


@pytest.mark.parametrize("entity_set", ["Catalog_DoesNotExist", "InformationRegister_Anything"])
async def test_u11_unsupported_entity_fails_closed_without_alternative_query(
        e2e_env, db, call, tokens, ids, grants, fake1c_log, entity_set):
    with grants.temporary_source_wide(ids["uc1"]):
        # Control run: which entity paths does capability detection alone touch?
        control_mark = fake1c_log.mark()
        warm = await call(tokens["uc1"], "onec_capabilities",
                          {"source_id": ids["source"], "refresh": True})
        assert warm.ok, warm.text
        detector_paths = fake1c_log.entity_paths(fake1c_log.since(control_mark))

        since, mark = await db_clock(db), fake1c_log.mark()
        outcome = await call(tokens["uc1"], "onec_read", {
            "source_id": ids["source"], "entity_set": entity_set, "top": 5})
    assert outcome.is_error and outcome.payload is None and outcome.transport_error is None
    assert "Traceback" not in outcome.text and find_leaks(outcome.text, e2e_env) == []
    assert "odata/standard.odata" not in outcome.text

    queried = fake1c_log.entity_paths(fake1c_log.since(mark))
    assert entity_set not in queried
    assert queried <= detector_paths, queried - detector_paths  # no alternative entity queried
    assert fake1c_log.all_methods_read_only(mark)

    rows = completion_rows(await audit_since(db, since, subject=ids["uc1"], tool="onec_read"))
    assert [r["outcome"] for r in rows] == ["error"], rows
    assert rows[0]["detail_code"] and rows[0]["source_id"] == ids["source"]


# ------------------------------------------------------------------------------------- U12

_AS_OF = "2026-04-30T00:00:00+00:00"
_APRIL = {"start_period": "2026-04-01T00:00:00+00:00", "end_period": "2026-04-30T00:00:00+00:00"}

# The reviewed synthetic fixture profile has NO mapping for these concepts, so the tools must
# still fail closed (no native reconciliation evidence, nothing fabricated).
_UNCONFIRMED_CALLS = (
    ("receivable_balance", {"period": _AS_OF}),
    ("payable_balance", {"period": _AS_OF}),
    ("payable_aging", {"as_of": _AS_OF}),
)
# Concepts the fixture profile DOES confirm: answered, but labelled synthetic L1 (never native).
_FIXTURE_CALLS = (
    ("bank_balance", {"period": "2026-05-01T00:00:00+00:00"}),
    ("inventory_balance", {"period": _AS_OF}),
    ("accounting_balance_and_turnovers", _APRIL),
    ("cash_movements", _APRIL),
    ("inventory_movements", _APRIL),
    ("accounting_posting_rows", _APRIL),
    ("receivable_aging", {"as_of": _AS_OF}),
)


def _seed_amounts() -> set[str]:
    values: set[str] = set()
    for key in ("bank_balances", "receivable_balances", "payable_balances",
                "inventory_balances", "cash_movements", "sales", "purchases"):
        for row in seed().get(key, []):
            for field, value in row.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool) \
                        and abs(value) >= 100 and "Number" not in field:
                    values.add(str(int(value)))
    return values


@pytest.mark.parametrize(("tool", "extra"), _FIXTURE_CALLS, ids=[c[0] for c in _FIXTURE_CALLS])
async def test_u12_fixture_profile_answers_are_labelled_synthetic_l1_not_native(
        db, call, tokens, ids, tool, extra):
    outcome = await call(tokens["uc1"], tool, {"source_id": ids["source"],
                                                "company_id": ids["one"], **extra})
    assert outcome.ok, outcome.text
    assert outcome.payload["profile_kind"] == "SYNTHETIC_FIXTURE"
    assert outcome.payload["evidence_level"] == "L1"
    assert outcome.payload["native_reconciliation"] == "NOT_RUN"
    assert "SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE" in outcome.payload["warnings"]


@pytest.mark.parametrize(("tool", "extra"), _UNCONFIRMED_CALLS,
                         ids=[c[0] for c in _UNCONFIRMED_CALLS])
async def test_u12_unconfirmed_capability_fails_closed_without_fabricated_numbers(
        e2e_env, db, call, tokens, ids, fake1c_log, tool, extra):
    profiles = await db.fetch(
        "SELECT 1 FROM bag.semantic_profiles WHERE company_id=$1::uuid AND status='VALIDATED' "
        "LIMIT 1", ids["one"], role="admin")
    assert not profiles, "baseline seed must not contain a validated semantic profile"

    since, mark = await db_clock(db), fake1c_log.mark()
    outcome = await call(tokens["uc1"], tool, {"source_id": ids["source"],
                                                "company_id": ids["one"], **extra})
    assert outcome.is_error and outcome.payload is None and outcome.transport_error is None
    assert find_leaks(outcome.text, e2e_env) == []
    for amount in _seed_amounts():
        assert not re.search(rf"\b{amount}\b", outcome.text), f"fixture number {amount} in error"

    rows = completion_rows(await audit_since(db, since, subject=ids["uc1"], tool=tool))
    assert [r["outcome"] for r in rows] == ["denied"], rows
    assert UNSUPPORTED_CODES.match(rows[0]["detail_code"] or ""), rows[0]["detail_code"]
    assert str(rows[0]["company_id"]) == ids["one"]
    # fail-closed: no register/business data was fetched from Fake1C
    paths = fake1c_log.entity_paths(fake1c_log.since(mark))
    assert not [p for p in paths if any(w in p for w in REGISTER_WORDS)], paths


# ------------------------------------------------------------------------------------- U13


async def test_u13_oversized_request_is_clamped_to_the_row_limit(
        db, call, tokens, ids, grants, fake1c_log):
    with grants.temporary_source_wide(ids["uc1"]):
        status = await call(tokens["uc1"], "system_status")
        max_rows = status.payload["max_rows"]
        since, mark = await db_clock(db), fake1c_log.mark()
        outcome = await call(tokens["uc1"], "onec_read", {
            "source_id": ids["source"], "entity_set": "Catalog_Counterparties",
            "top": max_rows * 50})
    assert outcome.ok, outcome.text
    assert len(outcome.payload["value"]) <= max_rows
    assert len(outcome.text.encode("utf-8")) <= 5_000_000  # response size bound

    reads = [r for r in fake1c_log.since(mark) if r["path"].endswith("Catalog_Counterparties")]
    assert reads and all(r["numeric_params"].get("$top") == max_rows for r in reads), reads
    rows = completion_rows(await audit_since(db, since, subject=ids["uc1"], tool="onec_read"))
    assert [r["outcome"] for r in rows] == ["success"]
    assert rows[0]["returned_items"] <= max_rows
    assert 0 < rows[0]["response_bytes"] <= 5_000_000
    # Observed contract: onec_read bounds by clamping $top; the product exposes no truncation
    # flag for raw reads (audit.truncated stays False). Recorded, not widened.
    assert rows[0]["truncated"] is False


@pytest.mark.parametrize("bad", [{"top": 0}, {"top": -5}, {"skip": -1}])
async def test_u13_invalid_paging_is_rejected_before_any_upstream_request(
        call, tokens, ids, fake1c_log, bad):
    mark = fake1c_log.mark()
    outcome = await call(tokens["uc1"], "sales_documents",
                         {"source_id": ids["source"], "company_id": ids["one"], **bad})
    assert outcome.is_error and outcome.payload is None
    assert fake1c_log.since(mark, gateway_only=False) == []
