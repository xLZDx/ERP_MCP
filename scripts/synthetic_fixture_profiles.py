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


def _balance(entity_set: str, fields: dict) -> dict:
    return {
        "entity_set": entity_set,
        "method": "Balance",
        "company_scope": GUID_SCOPE,
        "output_fields": fields,
        "required_register_capabilities": [{"entity_set": entity_set, "method": "Balance"}],
    }


def _open_items() -> dict:
    return {
        "entity_set": "AccumulationRegister_SettlementItems",
        "company_scope": GUID_SCOPE,
        "output_fields": {
            "counterparty_ref": "Counterparty_Key",
            "contract_ref": "Contract_Key",
            "document_ref": "DocumentRef",
            "date": "Period",
            "due_date": "DueDate",
            "amount": "Amount",
            "record_type": "RecordType",
            "settled_document_ref": "SettledDocumentRef",
        },
        "record_type_values": {"charge": ["Charge"], "payment": ["Payment"]},
        "currency": "MDL",
        "opening_items_known": True,
        "required_register_capabilities": [],
    }


def _duplicate_candidates() -> dict:
    return {
        "entity_set": "Catalog_Counterparties",
        "output_fields": {"counterparty_ref": "Ref_Key", "code": "Code", "name": "Description"},
        "company_activity": {
            "entity_set": "AccumulationRegister_SettlementItems",
            "counterparty_field": "Counterparty_Key",
            "company_scope": GUID_SCOPE,
        },
        "match_rule": "normalized_name_v1",
        "required_register_capabilities": [],
    }


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
        "sales": {
            "entity_set": "Document_Sales",
            "company_scope": GUID_SCOPE,
            "output_fields": {
                "document_ref": "Ref_Key",
                "document_number": "Number",
                "date": "Date",
                "counterparty": "Контрагент_Key",
                "amount": "Amount",
                "currency": "Валюта_Key",
                "posted": "Posted",
            },
            "order_by": "Date",
        },
        "accounting.posting_rows": {
            "entity_set": "AccountingRegister_Ledger",
            "company_scope": GUID_SCOPE,
            "output_fields": {
                "period": "Period",
                "recorder_ref": "Recorder",
                "line_number": "LineNumber",
                "active": "Active",
                "account_dr_ref": "AccountDr_Key",
                "account_cr_ref": "AccountCr_Key",
            },
            "source_timezone": "UTC",
            "required_register_capabilities": [],
        },
        "account.balance_and_turnovers": {
            "entity_set": "AccountingRegister_Ledger",
            "method": "balanceAndTurnovers",
            "company_scope": GUID_SCOPE,
            "output_fields": {
                "account": "Account_Key",
                "opening_debit": "OpeningDebit",
                "opening_credit": "OpeningCredit",
                "debit_turnover": "DebitTurnover",
                "credit_turnover": "CreditTurnover",
                "closing_debit": "ClosingDebit",
                "closing_credit": "ClosingCredit",
            },
            "required_register_capabilities": [
                {"entity_set": "AccountingRegister_Ledger", "method": "balanceAndTurnovers"}
            ],
        },
        "receivable.open_items": _open_items(),
        "counterparty.duplicate_candidates": _duplicate_candidates(),
        "inventory.balance": _balance(
            "AccumulationRegister_InventoryBalances",
            {
                "item_ref": "Номенклатура_Key",
                "warehouse_ref": "Склад_Key",
                "quantity": "КоличествоBalance",
            },
        ),
        "bank.balance": _balance(
            "AccumulationRegister_BankBalances",
            {
                "bank_account_ref": "БанковскийСчет_Key",
                "currency_ref": "Валюта_Key",
                "amount": "СуммаBalance",
            },
        ),
    }


def build_document(source_id: str = SOURCE_ID) -> dict:
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
            source_id: {"metadata_fingerprint": metadata_fingerprint(), "companies": companies}
        },
    }


def render(source_id: str = SOURCE_ID) -> bytes:
    text = json.dumps(build_document(source_id), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
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
