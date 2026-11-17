from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from business_ai_gateway.admin_mutations import (
    AdminActor,
    AdminMutationService,
    AdminValidationError,
)
from business_ai_gateway.company_scope import CompanyScopeResolver, CompanyScopeUnavailable


class _ResolverPool:
    async def fetchrow(self, query, *_args):
        assert "AND FALSE" in query
        return None

    async def fetchval(self, _query, *_args):
        return False


class _ResolverDatabase:
    def require_pool(self):
        return _ResolverPool()


@pytest.mark.asyncio
async def test_legacy_native_company_scope_mapping_is_not_runtime_usable():
    resolver = CompanyScopeResolver(_ResolverDatabase())

    with pytest.raises(CompanyScopeUnavailable, match="no validated company-scope mapping"):
        await resolver.mapping(
            source=SimpleNamespace(id="source-1"),
            company=SimpleNamespace(id="company-1"),
            entity_set="Document_Sale",
            metadata_fingerprint="metadata-fingerprint",
            drift_status="STABLE",
        )


@pytest.mark.asyncio
async def test_native_company_scope_mapping_creation_fails_before_insert(monkeypatch):
    profile_id = uuid4()
    inserted = False

    class _Connection:
        async def fetchrow(self, _query, _profile_id):
            return {
                "profile_id": profile_id,
                "source_id": "source-1",
                "company_id": "company-1",
                "status": "VALIDATED",
                "metadata_fingerprint": "metadata-fingerprint",
                "validation_evidence_json": {
                    "native_reconciliation_cases": [
                        {
                            "case_id": f"case-{index}",
                            "status": "PASS",
                            "native_report_ref": f"reports/{index}",
                        }
                        for index in range(10)
                    ]
                },
            }

        async def execute(self, query, *_args):
            nonlocal inserted
            if "INSERT INTO bag.company_scope_mappings" in query:
                inserted = True

    async def execute_captured_mutation(self, **kwargs):
        return await kwargs["mutation"](_Connection())

    service = AdminMutationService(SimpleNamespace(), production=False)
    monkeypatch.setattr(service, "_execute", execute_captured_mutation.__get__(service))

    with pytest.raises(AdminValidationError, match="not independently verifiable"):
        await service.create_company_scope_mapping(
            actor=AdminActor("operator-1", "admin-client"),
            profile_id=profile_id,
            entity_set="Document_Sale",
            company_property="Organization_Key",
            literal_kind="guid",
            reason="test fail-closed native mapping",
            request_id=uuid4(),
            idempotency_key="b3-native-mapping-refusal",
        )

    assert inserted is False
