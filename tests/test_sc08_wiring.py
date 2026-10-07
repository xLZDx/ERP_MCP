"""SC08 wiring pins: operator CLI concept choice, CLI mapping validation, metrics tool name."""

from __future__ import annotations

import argparse
import json

import pytest

from business_ai_gateway.duplicate_counterparties import DUPLICATE_CONCEPT
from business_ai_gateway.observability import OperationalMetrics
from business_ai_gateway.semantic import SemanticMappingUnconfirmed
from scripts import semantic_profiles

GOOD_MAPPING = {
    "entity_set": "Catalog_Counterparties",
    "output_fields": {"counterparty_ref": "Ref_Key", "code": "Code", "name": "Description"},
    "company_activity": {
        "entity_set": "AccumulationRegister_SettlementItems",
        "counterparty_field": "Counterparty_Key",
        "company_scope": {"field": "Company_Key", "value_type": "guid"},
    },
    "match_rule": "normalized_name_v1",
    "required_register_capabilities": [],
}


class _Conn:
    """Minimal connection: a DRAFT profile row; any write is recorded."""

    def __init__(self) -> None:
        self.writes: list[str] = []

    async def fetchrow(self, *_args, **_kwargs):
        return {"profile_id": "p", "status": "DRAFT"}

    async def execute(self, sql: str, *_args, **_kwargs):
        self.writes.append(sql)

    async def fetchval(self, *_args, **_kwargs):
        return None


def _args(tmp_path, mapping: dict) -> argparse.Namespace:
    path = tmp_path / "mapping.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    return argparse.Namespace(
        profile_id="00000000-0000-0000-0000-0000000000aa", concept=DUPLICATE_CONCEPT,
        mapping_file=str(path), evidence_file=None, actor="tester",
    )


def test_cli_accepts_the_duplicate_concept_choice():
    parsed = semantic_profiles.parser().parse_args([
        "add-mapping", "--profile-id", "00000000-0000-0000-0000-0000000000aa",
        "--concept", DUPLICATE_CONCEPT, "--mapping-file", "m.json", "--actor", "tester",
    ])
    assert parsed.concept == DUPLICATE_CONCEPT


@pytest.mark.parametrize("mutate", [
    lambda m: m.update(extra=1),
    lambda m: m.update(entity_set="Document_Sales"),
    lambda m: m["company_activity"].update(entity_set="Catalog_Counterparties"),
    lambda m: m.update(required_register_capabilities=[{"entity_set": "X", "method": "Y"}]),
    lambda m: m.update(match_rule="fuzzy"),
])
async def test_cli_add_mapping_rejects_invalid_duplicate_mapping_before_any_write(tmp_path, mutate):
    mapping = json.loads(json.dumps(GOOD_MAPPING))
    mutate(mapping)
    conn = _Conn()
    with pytest.raises(SemanticMappingUnconfirmed):
        await semantic_profiles.add_mapping(_args(tmp_path, mapping), conn)
    assert conn.writes == []


def test_duplicate_tool_name_is_a_registered_metrics_label():
    metrics = OperationalMetrics()
    assert "counterparty_duplicate_candidates" in OperationalMetrics.TOOLS
    metrics.record_operation("counterparty_duplicate_candidates", "success")
    assert metrics._operations[("counterparty_duplicate_candidates", "success")] == 1
    assert ("other", "success") not in metrics._operations
