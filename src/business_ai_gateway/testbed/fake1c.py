# ruff: noqa: I001
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


SEED_PATH = Path(__file__).resolve().parents[3] / "testbed" / "fake1c" / "fixtures" / "seed.json"
SEED = json.loads(SEED_PATH.read_text(encoding="utf-8"))

METADATA = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema xmlns="http://schemas.microsoft.com/ado/2008/09/edm" Namespace="Fake1C">
      <EntityType Name="Catalog_Organizations">
        <Property Name="Ref_Key" Type="Edm.Guid"/>
        <Property Name="Code" Type="Edm.String"/>
        <Property Name="Description" Type="Edm.String"/>
        <NavigationProperty Name="Owner" Relationship="Fake1C.Owner"/>
      </EntityType>
      <EntityType Name="Catalog_Counterparties">
        <Property Name="Ref_Key" Type="Edm.Guid"/>
        <Property Name="Code" Type="Edm.String"/>
        <Property Name="Description" Type="Edm.String"/>
      </EntityType>
      <EntityType Name="Document_Sales">
        <Property Name="Ref_Key" Type="Edm.Guid"/>
        <Property Name="Number" Type="Edm.String"/>
        <Property Name="Date" Type="Edm.DateTime"/>
        <Property Name="Контрагент_Key" Type="Edm.Guid"/>
        <Property Name="Валюта_Key" Type="Edm.String"/>
        <Property Name="Posted" Type="Edm.Boolean"/>
        <Property Name="Amount" Type="Edm.Decimal"/>
        <Property Name="Организация_Key" Type="Edm.Guid"/>
      </EntityType>
      <EntityType Name="Document_Purchases">
        <Property Name="Ref_Key" Type="Edm.Guid"/>
        <Property Name="Number" Type="Edm.String"/>
        <Property Name="Date" Type="Edm.DateTime"/>
        <Property Name="Контрагент_Key" Type="Edm.Guid"/>
        <Property Name="Валюта_Key" Type="Edm.String"/>
        <Property Name="Posted" Type="Edm.Boolean"/>
        <Property Name="Amount" Type="Edm.Decimal"/>
        <Property Name="Организация_Key" Type="Edm.Guid"/>
      </EntityType>
      <EntityType Name="AccumulationRegister_InventoryBalances">
        <Property Name="Номенклатура_Key" Type="Edm.Guid"/>
        <Property Name="Склад_Key" Type="Edm.Guid"/>
        <Property Name="КоличествоBalance" Type="Edm.Decimal"/>
        <Property Name="Организация_Key" Type="Edm.Guid"/>
      </EntityType>
      <EntityType Name="AccumulationRegister_InventoryMovements">
        <Property Name="Period" Type="Edm.DateTime"/>
        <Property Name="Номенклатура_Key" Type="Edm.Guid"/>
        <Property Name="Склад_Key" Type="Edm.Guid"/>
        <Property Name="Количество" Type="Edm.Decimal"/>
        <Property Name="RecordType" Type="Edm.String"/>
        <Property Name="Recorder_Key" Type="Edm.Guid"/>
        <Property Name="Организация_Key" Type="Edm.Guid"/>
      </EntityType>
      <EntityType Name="AccumulationRegister_CashMovements">
        <Property Name="Period" Type="Edm.DateTime"/>
        <Property Name="LineNumber" Type="Edm.Int32"/>
        <Property Name="СчетДенежныхСредств_Key" Type="Edm.Guid"/>
        <Property Name="Валюта_Key" Type="Edm.String"/>
        <Property Name="Сумма" Type="Edm.Decimal"/>
        <Property Name="RecordType" Type="Edm.String"/>
        <Property Name="Recorder" Type="Edm.Guid"/>
        <Property Name="Организация_Key" Type="Edm.Guid"/>
      </EntityType>
      <EntityType Name="AccumulationRegister_BankBalances">
        <Property Name="БанковскийСчет_Key" Type="Edm.Guid"/>
        <Property Name="Валюта_Key" Type="Edm.String"/>
        <Property Name="СуммаBalance" Type="Edm.Decimal"/>
        <Property Name="Организация_Key" Type="Edm.Guid"/>
      </EntityType>
      <EntityType Name="AccumulationRegister_ReceivableBalances">
        <Property Name="Контрагент_Key" Type="Edm.Guid"/>
        <Property Name="Договор_Key" Type="Edm.Guid"/>
        <Property Name="СуммаBalance" Type="Edm.Decimal"/>
        <Property Name="Организация_Key" Type="Edm.Guid"/>
      </EntityType>
      <EntityType Name="AccumulationRegister_PayableBalances">
        <Property Name="Контрагент_Key" Type="Edm.Guid"/>
        <Property Name="Договор_Key" Type="Edm.Guid"/>
        <Property Name="СуммаBalance" Type="Edm.Decimal"/>
        <Property Name="Организация_Key" Type="Edm.Guid"/>
      </EntityType>
      <EntityType Name="AccountingRegister_Ledger">
        <Property Name="Period" Type="Edm.DateTime"/>
        <Property Name="Recorder" Type="Edm.Guid"/>
        <Property Name="LineNumber" Type="Edm.Int32"/>
        <Property Name="Active" Type="Edm.Boolean"/>
        <Property Name="AccountDr_Key" Type="Edm.Guid"/>
        <Property Name="AccountCr_Key" Type="Edm.Guid"/>
        <Property Name="Организация_Key" Type="Edm.Guid"/>
      </EntityType>
      <EntityType Name="AccumulationRegister_SettlementItems">
        <Property Name="Period" Type="Edm.DateTime"/>
        <Property Name="Counterparty_Key" Type="Edm.Guid"/>
        <Property Name="Contract_Key" Type="Edm.Guid"/>
        <Property Name="DocumentRef" Type="Edm.Guid"/>
        <Property Name="DueDate" Type="Edm.DateTime"/>
        <Property Name="Amount" Type="Edm.Decimal"/>
        <Property Name="RecordType" Type="Edm.String"/>
        <Property Name="SettledDocumentRef" Type="Edm.Guid"/>
        <Property Name="Организация_Key" Type="Edm.Guid"/>
      </EntityType>
      <EntityContainer Name="Container">
        <EntitySet Name="Catalog_Organizations" EntityType="Fake1C.Catalog_Organizations"/>
        <EntitySet Name="Catalog_Counterparties" EntityType="Fake1C.Catalog_Counterparties"/>
        <EntitySet Name="Document_Sales" EntityType="Fake1C.Document_Sales"/>
        <EntitySet Name="Document_Purchases" EntityType="Fake1C.Document_Purchases"/>
        <EntitySet Name="AccumulationRegister_InventoryBalances" EntityType="Fake1C.AccumulationRegister_InventoryBalances"/>
        <EntitySet Name="AccumulationRegister_InventoryMovements" EntityType="Fake1C.AccumulationRegister_InventoryMovements"/>
        <EntitySet Name="AccumulationRegister_CashMovements" EntityType="Fake1C.AccumulationRegister_CashMovements"/>
        <EntitySet Name="AccumulationRegister_BankBalances" EntityType="Fake1C.AccumulationRegister_BankBalances"/>
        <EntitySet Name="AccumulationRegister_ReceivableBalances" EntityType="Fake1C.AccumulationRegister_ReceivableBalances"/>
        <EntitySet Name="AccumulationRegister_PayableBalances" EntityType="Fake1C.AccumulationRegister_PayableBalances"/>
        <EntitySet Name="AccountingRegister_Ledger" EntityType="Fake1C.AccountingRegister_Ledger"/>
        <EntitySet Name="AccumulationRegister_SettlementItems" EntityType="Fake1C.AccumulationRegister_SettlementItems"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>""".encode()


def _rows(entity: str):
    mapping = {
        "Catalog_Organizations": SEED["organizations"],
        "Catalog_Counterparties": SEED["counterparties"],
        "Document_Sales": SEED["sales"],
        "Document_Purchases": SEED["purchases"],
        "AccumulationRegister_InventoryBalances": SEED["inventory_balances"],
        "AccumulationRegister_InventoryMovements": SEED["inventory_movements"],
        "AccumulationRegister_CashMovements": SEED["cash_movements"],
        "AccumulationRegister_BankBalances": SEED["bank_balances"],
        "AccumulationRegister_ReceivableBalances": SEED["receivable_balances"],
        "AccumulationRegister_PayableBalances": SEED["payable_balances"],
        "AccountingRegister_Ledger": SEED["accounting_postings"],
        "AccumulationRegister_SettlementItems": SEED["settlement_items"],
    }
    if entity not in mapping:
        raise KeyError(entity)
    return mapping[entity]


_COND = re.compile(
    r"^(?P<f>[\w\u0080-\uffff]+)\s+(?P<op>eq|ne|ge|gt|le|lt)\s+"
    r"(?P<v>guid'[^']*'|datetime'[^']*'|'(?:[^']|'')*'|[^\s']+)$"
)


def _literal(text: str):
    if text.startswith("guid'"):
        return text[5:-1].lower()
    if text.startswith("datetime'"):
        return datetime.fromisoformat(text[9:-1])
    if text.startswith("'"):
        return text[1:-1].replace("''", "'")
    if text in {"true", "false"}:
        return text == "true"
    return float(text)


def _coerce(value, literal):
    if isinstance(literal, datetime):
        return datetime.fromisoformat(str(value))
    if isinstance(literal, str):
        return str(value).lower() if re.fullmatch(r"[0-9a-fA-F-]{36}", str(value)) else str(value)
    if isinstance(literal, bool):
        return bool(value)
    return float(value)


def apply_filter(rows, expression: str | None):
    """Evaluate the conjunctive eq/ne/ge/gt/le/lt filters the gateway builds (read-only)."""
    if not expression:
        return rows
    conditions = []
    for part in re.split(r"\s+and\s+", expression.strip()):
        match = _COND.match(part.strip())
        if match is None:
            raise ValueError("unsupported $filter")
        conditions.append((match["f"], match["op"], _literal(match["v"])))
    ops = {
        "eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "ge": lambda a, b: a >= b,
        "gt": lambda a, b: a > b, "le": lambda a, b: a <= b, "lt": lambda a, b: a < b,
    }
    result = []
    for row in rows:
        if all(
            field in row and row[field] is not None
            and ops[op](_coerce(row[field], lit), lit)
            for field, op, lit in conditions
        ):
            result.append(row)
    return result


def apply_query(rows, params):
    rows = apply_filter(rows, params.get("$filter"))
    order = params.get("$orderby")
    if order:
        for item in reversed([x.strip() for x in order.split(",") if x.strip()]):
            field, _, direction = item.partition(" ")
            rows = sorted(rows, key=lambda r, f=field: str(r.get(f, "")),
                          reverse=direction.strip().lower() == "desc")
    skip = int(params.get("$skip", 0))
    top = int(params.get("$top", len(rows)))
    rows = rows[max(0, skip): max(0, skip) + max(0, top)]
    select = params.get("$select")
    if select:
        keep = [x.strip() for x in select.split(",") if x.strip()]
        rows = [{k: r[k] for k in keep if k in r} for r in rows]
    return rows


def _atom(rows) -> bytes:
    atom = "http://www.w3.org/2005/Atom"
    metadata_ns = "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
    data_ns = "http://schemas.microsoft.com/ado/2007/08/dataservices"
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<feed xmlns="{atom}" xmlns:m="{metadata_ns}" xmlns:d="{data_ns}">',
    ]
    for row in rows:
        parts.append("<entry><content><m:properties>")
        for key, value in row.items():
            if value is None:
                parts.append(f"<d:{key} m:null=\"true\" />")
            else:
                text = str(value).lower() if isinstance(value, bool) else str(value)
                parts.append(f"<d:{key}>{html.escape(text)}</d:{key}>")
        parts.append("</m:properties></content></entry>")
    parts.append("</feed>")
    return "".join(parts).encode("utf-8")


def create_app(profile: str = "json") -> Starlette:
    if profile not in {"json", "atom"}:
        raise ValueError("profile must be json or atom")

    async def metadata(_: Request):
        return Response(METADATA, media_type="application/xml")

    async def entity(request: Request):
        name = request.path_params["entity"]
        try:
            rows = _rows(name)
        except KeyError:
            return JSONResponse({"error": "unknown entity"}, status_code=404)

        try:
            rows = apply_query(rows, request.query_params)
        except ValueError:
            return JSONResponse({"error": "unsupported query"}, status_code=400)
        accept = request.headers.get("accept", "")

        if profile == "atom":
            if "json" in accept:
                return Response(status_code=406)
            return Response(_atom(rows), media_type="application/atom+xml")

        if "atom" in accept:
            return Response(_atom(rows), media_type="application/atom+xml")
        return JSONResponse({"d": {"results": rows}})

    return Starlette(
        routes=[
            Route("/odata/standard.odata/$metadata", metadata, methods=["GET", "HEAD"]),
            Route("/odata/standard.odata/{entity}", entity, methods=["GET"]),
        ]
    )


# Registers that expose read-only virtual tables to the fake sidecar (capability evidence is
# derived from this table; the plain Fake1C OData app does not serve virtual tables itself).
VIRTUAL_TABLES: dict[str, list[str]] = {
    "AccumulationRegister_InventoryBalances": ["Balance"],
    "AccumulationRegister_BankBalances": ["Balance"],
    "AccumulationRegister_ReceivableBalances": ["Balance"],
    "AccumulationRegister_PayableBalances": ["Balance"],
    "AccountingRegister_Ledger": ["balanceAndTurnovers"],
}
_BALANCE_SOURCES = {
    "AccumulationRegister_InventoryBalances": "inventory_balances",
    "AccumulationRegister_BankBalances": "bank_balances",
    "AccumulationRegister_ReceivableBalances": "receivable_balances",
    "AccumulationRegister_PayableBalances": "payable_balances",
}


def virtual_table_rows(entity_set: str, method: str, args: dict) -> list[dict]:
    """Read-only virtual-table results from the seed; LookupError => CAPABILITY_UNSUPPORTED."""
    if method == "Balance" and entity_set in _BALANCE_SOURCES:
        return apply_filter(SEED[_BALANCE_SOURCES[entity_set]], args.get("Condition"))
    if method == "balanceAndTurnovers" and entity_set == "AccountingRegister_Ledger":
        window = args.get("Period") or {}
        start = datetime.fromisoformat(window["from"])
        end = datetime.fromisoformat(window["to"])
        rows = [
            r for r in apply_filter(SEED["account_turnovers"], args.get("Condition"))
            if start <= datetime.fromisoformat(r["PeriodFrom"])
            and datetime.fromisoformat(r["PeriodTo"]) <= end
        ]
        hidden = {"PeriodFrom", "PeriodTo"}
        return [{k: v for k, v in r.items() if k not in hidden} for r in rows]
    raise LookupError(f"{entity_set}/{method}")
