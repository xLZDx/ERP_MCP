"""Native reconciliation evidence fails closed until a trusted verifier exists."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from business_ai_gateway.admin_mutations import AdminActor, AdminMutationService
from scripts.semantic_profiles import validate_profile

def _fake_native_evidence() -> dict[str, object]:
    return {
        "native_reconciliation_cases": [
            {"case_id": f"case-{i}", "status": "PASS", "native_report_ref": f"reports/{i}"}
            for i in range(10)
        ]
    }

@pytest.mark.asyncio
async def test_admin_native_evidence_is_rejected_before_any_database_mutation():
    def unexpected_pool():
        raise AssertionError("native evidence must be refused before database access")

    service = AdminMutationService(SimpleNamespace(require_pool=unexpected_pool), production=False)
    with pytest.raises(ValueError, match="not independently verifiable"):
        await service.validate_semantic_profile(
            actor=AdminActor(str(uuid4()), "client"),
            profile_id=uuid4(),
            validation_evidence_data=_fake_native_evidence(),
            reason="test fail-closed native evidence",
            request_id=uuid4(),
            idempotency_key=str(uuid4()),
        )

@pytest.mark.asyncio
async def test_cli_native_evidence_is_rejected_before_profile_update(tmp_path):
    evidence_file = tmp_path / "native-evidence.json"
    evidence_file.write_text(json.dumps(_fake_native_evidence()), encoding="utf-8")

    class UnexpectedConnection:
        def __getattr__(self, name):
            raise AssertionError(f"native evidence must be refused before DB access: {name}")

    args = SimpleNamespace(profile_id=str(uuid4()), evidence_file=evidence_file, actor="operator-1")
    with pytest.raises(ValueError, match="not independently verifiable"):
        await validate_profile(args, UnexpectedConnection())
