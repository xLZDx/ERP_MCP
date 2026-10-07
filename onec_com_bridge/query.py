"""The ONE query the bridge runs, and the row reading for it.

Everything that is unverified against a live 1C lives in :class:`AnalyticsBalanceQuery` so it can be adjusted after
a check on a disposable clone. The template is a module constant and is never formatted with request data: every
request value reaches 1C through ``Query.SetParameter`` only.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import COM_INTERNAL, BridgeFault

# Live-confirmed (disposable clone, reader): an EMPTY subconto-kinds parameter returns per-subconto rows, and the SPLIT
# fields СуммаРазвернутыйОстатокДт/Кт equal OData's split balance exactly (СуммаОстатокДт/Кт would put a debit
# balance as a negative credit, so they must not be used).
BALANCE_QUERY_TEMPLATE = (
    "ВЫБРАТЬ Остатки.Счет КАК Счет, Остатки.Субконто1 КАК Субконто1, Остатки.Субконто2 КАК Субконто2, "
    "Остатки.Субконто3 КАК Субконто3, Остатки.Валюта КАК Валюта, "
    "Остатки.СуммаРазвернутыйОстатокДт КАК Дт, Остатки.СуммаРазвернутыйОстатокКт КАК Кт "
    "ИЗ РегистрБухгалтерии.Хозрасчетный.Остатки(&Период, Счет В (&Счета), , Организация = &Организация) "
    "КАК Остатки"
)

# Live-confirmed type names for TypeDescription (resolved to the Type value for XMLValue).
ACCOUNT_REF_TYPE = "ПланСчетовСсылка.Хозрасчетный"
COMPANY_REF_TYPE = "СправочникСсылка.Организации"

# Russian metadata kind (first segment of the full metadata name) -> canonical type prefix. Unknown kind fails closed.
KIND_MAP = {
    "Справочник": "Catalog",
    "Документ": "Document",
    "ПланСчетов": "ChartOfAccounts",
    "ПланВидовХарактеристик": "ChartOfCharacteristicTypes",
    "Перечисление": "Enum",
}

_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_NAME_RE = re.compile(r"^\w+$")
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"


def _fail() -> BridgeFault:
    return BridgeFault(COM_INTERNAL)


def to_decimal_string(value: Any) -> str:
    """Exact decimal string; ``None`` is zero; non-finite or non-numeric values fail closed."""
    if value is None:
        return "0"
    if isinstance(value, bool):
        raise _fail()
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise _fail() from None
    if not number.is_finite():
        raise _fail()
    text = format(number, "f")
    return "0" if Decimal(text) == 0 else text


class AnalyticsBalanceQuery:
    """Runs the fixed template on an open reader connection and converts rows to the wire shape."""

    def run(
        self,
        conn: Any,
        *,
        as_of: dt.datetime,
        company_ref: str,
        account_keys: tuple[str, ...],
        max_rows: int,
    ) -> tuple[list[dict[str, Any]], bool]:
        requested = set(account_keys)
        accounts = conn.NewObject("Array")
        for key in account_keys:
            accounts.Add(self._ref(conn, ACCOUNT_REF_TYPE, key))
        company = self._ref(conn, COMPANY_REF_TYPE, company_ref)
        # 1C dates are timezone-naive wall-clock values; the offset of ``as_of`` is dropped, the wall clock is kept.
        period = as_of.replace(tzinfo=None)

        query = conn.NewObject("Query")
        query.Text = BALANCE_QUERY_TEMPLATE
        query.SetParameter("Период", period)
        query.SetParameter("Счета", accounts)
        query.SetParameter("Организация", company)

        selection = query.Execute().Select()
        rows: list[dict[str, Any]] = []
        truncated = False
        while selection.Next():
            if len(rows) >= max_rows:
                truncated = True
                break
            rows.append(self._row(conn, selection, requested))
        return rows, truncated

    @staticmethod
    def _ref(conn: Any, type_name: str, key: str) -> Any:
        # Live-confirmed: the COM connector exposes no Type(); a TypeDescription yields the Type value for XMLValue.
        return conn.XMLValue(conn.NewObject("TypeDescription", type_name).Types().Get(0), key)

    # Live-confirmed on the disposable clone (reader): column access, XMLString GUIDs and Metadata().FullName() kinds.
    def _row(self, conn: Any, selection: Any, requested: set[str]) -> dict[str, Any]:
        account_key = self._guid(conn, selection.Счет)
        if account_key is None or account_key not in requested:
            raise _fail()  # a row outside the requested account set is never returned
        return {
            "account_key": account_key,
            "analytics": [
                self._analytics(conn, selection.Субконто1),
                self._analytics(conn, selection.Субконто2),
                self._analytics(conn, selection.Субконто3),
            ],
            "debit": to_decimal_string(selection.Дт),
            "credit": to_decimal_string(selection.Кт),
            "currency_ref": self._guid(conn, selection.Валюта),
        }

    def _guid(self, conn: Any, value: Any) -> str | None:
        if value is None or not conn.ValueIsFilled(value):
            return None
        text = str(conn.XMLString(value)).lower()
        if not _GUID_RE.match(text) or text == _EMPTY_GUID:
            raise _fail()
        return text

    def _analytics(self, conn: Any, value: Any) -> dict[str, Any]:
        if value is None:
            return {"ref": None, "type": None}
        try:
            full_name = str(value.Metadata().FullName())  # a non-reference value has no metadata: fail closed
        except Exception:  # noqa: BLE001
            raise _fail() from None
        ref = self._guid(conn, value)
        if ref is None:
            return {"ref": None, "type": None}
        kind, _, name = full_name.partition(".")
        prefix = KIND_MAP.get(kind)
        if prefix is None or not _NAME_RE.match(name):
            raise _fail()
        return {"ref": ref, "type": f"{prefix}.{name}"}
