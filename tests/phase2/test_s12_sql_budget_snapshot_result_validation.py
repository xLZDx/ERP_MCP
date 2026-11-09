"""Malformed budget snapshot result shapes must become fixed ledger refusals."""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from business_ai_gateway.phase2.change_ledger._common import LedgerError, Scope
from business_ai_gateway.phase2.change_ledger.sql_ledger import SqlChangeLedger


class StubInvoke:
    def __init__(self, result: object) -> None:
        self.result = result

    async def invoke(self, *args: object, **kwargs: object) -> object:
        return self.result


@pytest.mark.asyncio
@pytest.mark.parametrize("check", [["EXHAUSTED"], {"value": "EXHAUSTED"}])
async def test_budget_snapshot_unhashable_check_becomes_sql_result_invalid(check: object) -> None:
    ledger = StubInvoke({"check": check})

    with pytest.raises(LedgerError) as error:
        await SqlChangeLedger.budget_snapshot(
            ledger, Scope("tenant", "company"), uuid4(), Decimal("1"), "EUR"
        )

    assert error.value.code == "SQL_RESULT_INVALID"
