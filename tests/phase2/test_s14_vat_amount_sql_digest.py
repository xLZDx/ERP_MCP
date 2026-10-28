"""Python-versus-SQL payload digest equivalence for the six-field CREATE_DRAFT line (``vat_amount``).

Needs ERP_PHASE2_TEST_DSN (superuser DSN of a disposable cluster); without it the test is skipped as NOT_RUN
(or fails when ERP_PHASE2_REQUIRE_PG=1). One throwaway database g1x_<uuid8> with migrations 001-018 is created.

Run: .venv\\Scripts\\python.exe -m pytest -p no:cacheprovider -q -rs tests/phase2/test_s14_vat_amount_sql_digest.py
"""
from __future__ import annotations

import json

import pytest
from _pg_harness import require_dsn, throwaway_db

from business_ai_gateway.phase2.change import ChangeKind, Scope
from business_ai_gateway.phase2.change.proposal import (
    DraftPayload,
    canonical_json,
    parse_writer_payload,
    payload_digest,
    payload_to_dict,
)

pytestmark = pytest.mark.integration

SCOPE = Scope("tenant-1", "company-1", "org-1", "base-1")
# CR-395: VAT20 would refuse every value but 3.5; a rate code outside the closed table leaves vat_amount free data here
VAT_VALUES = ("0", "3.5", "1234.56")


def _typed(vat_amount: str) -> DraftPayload:
    raw = {
        "organization_ref": "org-1", "counterparty_ref": "cp-1", "contract_ref": "ct-1",
        "supplier_document_number": "N-1", "supplier_document_date": "2026-10-01", "currency": "RUB",
        "lines": [{"item_ref": "it-1", "quantity": "2", "price": "10.5", "vat_rate_code": "VATX",
                   "amount": "21", "vat_amount": vat_amount}],
        "comment": "note",
    }
    parsed = parse_writer_payload(raw, ChangeKind.CREATE_DRAFT, SCOPE)
    assert type(parsed) is DraftPayload, parsed
    return parsed


async def _sql_digest(conn, payload: DraftPayload, target_version: str | None) -> str:
    return await conn.fetchval("SELECT change_ledger.payload_digest_of($1::jsonb,$2)",
                               json.dumps(payload_to_dict(payload)), target_version)


async def test_python_and_sql_payload_digest_agree_for_vat_amount_values() -> None:
    dsn = require_dsn()
    async with throwaway_db(dsn, seed=False) as db:
        conn = db.conn
        sql_digests = {}
        for vat in VAT_VALUES:
            payload = _typed(vat)
            assert payload.lines[0].vat_amount == vat
            for target_version in (None, "v1"):
                py = payload_digest(payload, target_version)
                sql = await _sql_digest(conn, payload, target_version)
                assert sql == py, (vat, target_version)
            # the canonical text itself (not only its hash) is byte-equal and contains the new field
            text = canonical_json({"payload": payload_to_dict(payload), "target_version": "v1"})
            sql_text = await conn.fetchval(
                "SELECT change_ledger.canon_json(jsonb_build_object('payload',$1::jsonb,'target_version',$2::text))",
                json.dumps(payload_to_dict(payload)), "v1")
            assert sql_text == text
            assert f'"vat_amount":"{vat}"' in sql_text
            sql_digests[vat] = await _sql_digest(conn, payload, "v1")
        # vat_amount is digest-bound on the SQL side too: three distinct values give three distinct digests
        assert len(set(sql_digests.values())) == len(VAT_VALUES)
        # a line WITHOUT vat_amount (old five-field shape) must not collide with any six-field digest
        legacy = payload_to_dict(_typed("0"))
        del legacy["lines"][0]["vat_amount"]
        legacy_sql = await conn.fetchval("SELECT change_ledger.payload_digest_of($1::jsonb,$2)",
                                         json.dumps(legacy), "v1")
        assert legacy_sql not in sql_digests.values()
