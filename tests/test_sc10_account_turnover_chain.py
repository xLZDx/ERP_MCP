"""SC10: opening + debit - credit = closing through the public MCP tool (synthetic L1 only)."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal

import pytest
from mcp.server.mcpserver.exceptions import UnexpectedToolError

from business_ai_gateway.testbed.fake_sidecar import create_sidecar_app
from scripts import synthetic_fixture_profiles as fixture_gen
from tests.sc_stack import (
    ORG_ONE,
    ORG_TWO,
    ServerThread,
    build_stack,
    fixture_document,
    write_fixture_file,
)
from tests.test_synthetic_fixture_profiles import _stack

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="requires disposable PostgreSQL")
WINDOW = {"start_period": "2026-04-01T00:00:00+00:00", "end_period": "2026-04-30T00:00:00+00:00"}


@pytest.mark.asyncio
async def test_sc10_opening_plus_turnover_equals_closing_via_tool(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        result = await stack.call(
            "accounting_balance_and_turnovers", source_id=stack.source_id,
            company_id=str(stack.companies[ORG_ONE]), **WINDOW,
        )
        body = stack.payload(result)
        assert body["profile_kind"] == "SYNTHETIC_FIXTURE"
        assert body["native_reconciliation"] == "NOT_RUN"
        assert "SYNTHETIC_FIXTURE_PROFILE_NOT_NATIVE" in body["warnings"]
        (row,) = body["value"]
        assert set(row) == set(fixture_gen.concept_mappings()["account.balance_and_turnovers"]["output_fields"])
        opening, debit, credit, closing = (
            Decimal(str(row[k]))
            for k in ("opening_debit", "debit_turnover", "credit_turnover", "closing_debit")
        )
        assert (opening, debit, credit, closing) == (100, 40, 15, 125)
        assert opening + debit - credit == closing
        audit = await stack.audit_rows("accounting_balance_and_turnovers")
        assert any(r["detail_code"] == "SYNTHETIC_FIXTURE_PROFILE" for r in audit)
        other = stack.payload(await stack.call(
            "accounting_balance_and_turnovers", source_id=stack.source_id,
            company_id=str(stack.companies[ORG_TWO]), **WINDOW,
        ))
        assert other["value"] == []
    finally:
        await stack.db.close()


@pytest.mark.asyncio
async def test_sc10_naive_timestamps_are_rejected_before_any_register_read(
    fake1c, fake_sidecar, tmp_path, monkeypatch
):
    stack = await _stack(fake1c, fake_sidecar, tmp_path, monkeypatch)
    try:
        with pytest.raises(UnexpectedToolError):
            await stack.call(
                "accounting_balance_and_turnovers", source_id=stack.source_id,
                company_id=str(stack.companies[ORG_ONE]),
                start_period="2026-04-01", end_period="2026-04-30",
            )
    finally:
        await stack.db.close()


@pytest.mark.asyncio
async def test_sc10_missing_register_capability_is_capability_unsupported(
    fake1c, tmp_path, monkeypatch
):
    no_ledger = {
        k: v for k, v in __import__("business_ai_gateway.testbed.fake1c", fromlist=["x"]).VIRTUAL_TABLES.items()
        if k != "AccountingRegister_Ledger"
    }
    companies = {ORG_ONE: uuid.uuid4(), ORG_TWO: uuid.uuid4()}
    source_id = f"psc-{uuid.uuid4().hex[:12]}"
    path = tmp_path / "profiles.json"
    sha = write_fixture_file(path, fixture_document(source_id, companies))
    with ServerThread(create_sidecar_app("t" * 40, no_ledger)) as sidecar:
        stack = await build_stack(
            DATABASE_URL, fake1c, f"http://127.0.0.1:{sidecar.port}", fixture_file=path,
            fixture_sha=sha, source_id=source_id, companies=companies, env_setter=monkeypatch.setenv,
        )
        try:
            with pytest.raises(UnexpectedToolError):
                await stack.call(
                    "accounting_balance_and_turnovers", source_id=source_id,
                    company_id=str(companies[ORG_ONE]), **WINDOW,
                )
            rows = await stack.audit_rows("accounting_balance_and_turnovers")
            assert rows[-1]["outcome"] == "denied"
            assert rows[-1]["detail_code"] == "CAPABILITY_UNSUPPORTED"
        finally:
            await stack.db.close()
