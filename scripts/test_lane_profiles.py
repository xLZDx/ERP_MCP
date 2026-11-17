"""Generate/verify the reviewed TEST-LANE UNRECONCILED profile file for the real test source.

    python scripts/test_lane_profiles.py            # print fingerprint + file sha256
    python scripts/test_lane_profiles.py --write    # regenerate the pinned file

The file is served only when BAG_ENVIRONMENT=test and the source is listed in
BAG_TEST_LANE_UNRECONCILED_SOURCES (see docs/SEMANTIC_PROFILES.md, "Test-lane unreconciled
profiles"). Every response is labelled TEST_LANE_UNRECONCILED / L1 / native NOT_RUN; it is never a
native or machine reconciliation. Entity-set and field names come from the live $metadata of the
real test base (pinned by its SHA-256, the same value stored in bag.source_capabilities).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "testbed" / "real1c" / "fixtures" / "test_lane_profiles.json"
SOURCE_ID = "onec-818ha-reference"
COMPANY_ID = "3e31afc5-351f-4f36-8074-99129fa3d911"
# SHA-256 of the served $metadata of the real test base (bag.source_capabilities.metadata_fingerprint).
METADATA_FINGERPRINT = "56337576ddf06821456a7ab4701a619f9c2457e3e1757c723dcc8907196ebbeb"
SCOPE = {"field": "Организация_Key", "value_type": "guid"}
LEDGER = "AccountingRegister_Хозрасчетный"
# Assumption (not verified against the base): Moldovan accounting base, local time.
SOURCE_TIMEZONE = "Europe/Chisinau"


def _document(entity_set: str) -> dict:
    return {
        "entity_set": entity_set,
        "company_scope": SCOPE,
        "output_fields": {
            "document_ref": "Ref_Key",
            "document_number": "Number",
            "date": "Date",
            "counterparty": "Контрагент_Key",
            "amount": "СуммаДокумента",
            "currency": "ВалютаДокумента_Key",
            "posted": "Posted",
        },
        "order_by": "Date",
    }


def concept_mappings() -> dict[str, dict]:
    return {
        "account.balance_and_turnovers": {
            "entity_set": LEDGER,
            "method": "balanceAndTurnovers",
            "company_scope": SCOPE,
            "output_fields": {
                "account": "Account_Key",
                "opening_debit": "СуммаOpeningSplittedBalanceDr",
                "opening_credit": "СуммаOpeningSplittedBalanceCr",
                "debit_turnover": "СуммаTurnoverDr",
                "credit_turnover": "СуммаTurnoverCr",
                "closing_debit": "СуммаClosingSplittedBalanceDr",
                "closing_credit": "СуммаClosingSplittedBalanceCr",
            },
            "required_register_capabilities": [
                {"entity_set": LEDGER, "method": "balanceAndTurnovers"}
            ],
        },
        "accounting.posting_rows": {
            "entity_set": LEDGER + "_RecordType",
            "company_scope": SCOPE,
            "output_fields": {
                "period": "Period",
                "recorder_ref": "Recorder",
                "line_number": "LineNumber",
                "active": "Active",
                "account_dr_ref": "AccountDr_Key",
                "account_cr_ref": "AccountCr_Key",
            },
            "source_timezone": SOURCE_TIMEZONE,
            "required_register_capabilities": [],
        },
        "sales": _document("Document_РеализацияТоваровУслуг"),
        "purchases": _document("Document_ПоступлениеТоваровУслуг"),
        "counterparty.duplicate_candidates": {
            "entity_set": "Catalog_Контрагенты",
            "output_fields": {"counterparty_ref": "Ref_Key", "code": "Code", "name": "Description"},
            "company_activity": {
                "entity_set": "AccumulationRegister_Продажи_RecordType",
                "counterparty_field": "Контрагент_Key",
                "company_scope": SCOPE,
            },
            "match_rule": "normalized_name_v1",
            "required_register_capabilities": [],
        },
    }


def build_document() -> dict:
    return {
        "schema_version": 1,
        "fixture_id": "erp-mcp-test-lane-unreconciled-v1",
        "review": {
            "kind": "TEST_LANE_UNRECONCILED",
            "notes": "Authored from the live $metadata of the real test base; L1 only, native "
            "reconciliation NOT_RUN, never native or machine evidence, never a "
            "bag.semantic_profiles row.",
        },
        "sources": {
            SOURCE_ID: {
                "metadata_fingerprint": METADATA_FINGERPRINT,
                "companies": {COMPANY_ID: {"concepts": concept_mappings()}},
            }
        },
    }


def render() -> bytes:
    text = json.dumps(build_document(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    data = render()
    if args.write:
        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_bytes(data)
    print("metadata_fingerprint", METADATA_FINGERPRINT)
    print("file_sha256", hashlib.sha256(data).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
