"""Generate/verify the reviewed TEST-ONLY synthetic fixture profile file for Fake1C.

    python scripts/synthetic_fixture_profiles.py            # print fingerprint + file sha256
    python scripts/synthetic_fixture_profiles.py --write    # regenerate the pinned file

The file is re-pinned whenever the Fake1C $metadata changes (its fingerprint is the SHA-256 of the
served metadata bytes). Synthetic evidence is never native reconciliation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from business_ai_gateway.testbed.fake1c import METADATA, SEED

FIXTURE_PATH = ROOT / "testbed" / "fake1c" / "fixtures" / "synthetic_profiles.json"
SOURCE_ID = "fake1c-local"
GUID_SCOPE = {"field": "Организация_Key", "value_type": "guid"}


def metadata_fingerprint() -> str:
    return hashlib.sha256(METADATA).hexdigest()


def concept_mappings() -> dict[str, dict]:
    return {
        "inventory.movements": {
            "entity_set": "AccumulationRegister_InventoryMovements",
            "company_scope": GUID_SCOPE,
            "output_fields": {
                "period": "Period",
                "item_ref": "Номенклатура_Key",
                "warehouse_ref": "Склад_Key",
                "quantity": "Количество",
                "record_type": "RecordType",
                "recorder_ref": "Recorder_Key",
            },
            "record_type_values": {"receipt": ["Receipt"], "expense": ["Expense"]},
            "quantity_encoding": "positive_magnitude_by_record_type",
            "source_timezone": "UTC",
            "order_by": "Period",
            "required_register_capabilities": [],
        },
        "cash.movements": {
            "entity_set": "AccumulationRegister_CashMovements",
            "company_scope": GUID_SCOPE,
            "output_fields": {
                "period": "Period",
                "line_number": "LineNumber",
                "cash_account_ref": "СчетДенежныхСредств_Key",
                "currency_ref": "Валюта_Key",
                "amount": "Сумма",
                "record_type": "RecordType",
                "recorder_ref": "Recorder",
            },
            "record_type_values": {"receipt": ["Receipt"], "expense": ["Expense"]},
            "amount_encoding": "positive_magnitude_by_record_type",
            "source_timezone": "UTC",
            "required_register_capabilities": [],
        },
    }


def build_document() -> dict:
    companies = {
        org["Ref_Key"]: {"concepts": concept_mappings()} for org in SEED["organizations"]
    }
    return {
        "schema_version": 1,
        "fixture_id": "erp-mcp-synthetic-v1-profiles",
        "review": {
            "kind": "SYNTHETIC_FIXTURE",
            "notes": "Reviewed against testbed/fake1c metadata and seed; L1 only, never native "
            "reconciliation, never a bag.semantic_profiles row.",
        },
        "sources": {
            SOURCE_ID: {"metadata_fingerprint": metadata_fingerprint(), "companies": companies}
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
        FIXTURE_PATH.write_bytes(data)
    print("metadata_fingerprint", metadata_fingerprint())
    print("file_sha256", hashlib.sha256(data).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
