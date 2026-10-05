from __future__ import annotations

import json
import os
import time
import uuid
from argparse import Namespace
from dataclasses import replace

import asyncpg
import pytest

from business_ai_gateway.audit import Audit, query_fingerprint
from business_ai_gateway.compatibility import (
    AdapterProfile,
    CompatibilityStatus,
    OneCCapabilities,
)
from business_ai_gateway.principal import Principal
from business_ai_gateway.registry import AccessDenied, Registry
from business_ai_gateway.semantic import SemanticProfileUnavailable
from scripts.admin import capability_ack_drift
from scripts.semantic_profiles import (
    add_mapping,
    confirm_mapping,
    create_profile,
    validate_profile,
)

DATABASE_URL = os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="requires the disposable PostgreSQL database configured by CI",
)


class ConnectionDatabase:
    def __init__(self, connection):
        self.connection = connection

    def require_pool(self):
        return self.connection


@pytest.mark.asyncio
async def test_postgres_company_grants_deny_precedence_and_live_revocation():
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    source_id = f"acl-test-{uuid.uuid4()}"
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    grant_a = uuid.uuid4()
    grant_b = uuid.uuid4()
    subject = f"subject-{uuid.uuid4()}"
    try:
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'ACL integration source',
                   'https://onec.example.test/odata')
            """,
            source_id,
        )
        await conn.executemany(
            """
            INSERT INTO bag.companies(company_id, source_id, external_ref, display_name)
            VALUES($1,$2,$3,$4)
            """,
            [
                (company_a, source_id, "a", "Company A"),
                (company_b, source_id, "b", "Company B"),
            ],
        )
        await conn.executemany(
            """
            INSERT INTO bag.access_grants(
              grant_id, principal_kind, principal_id, source_id, company_id, effect
            ) VALUES($1, 'subject', $2, $3, $4, $5)
            """,
            [
                (grant_a, subject, source_id, company_a, "allow"),
                (grant_b, subject, source_id, company_b, "allow"),
                (uuid.uuid4(), subject, source_id, company_b, "deny"),
            ],
        )
        principal = Principal(
            subject=subject,
            client_id="acl-integration-test",
            scopes=frozenset({"onec:read"}),
            groups=frozenset(),
            claims={},
        )
        registry = Registry(ConnectionDatabase(conn), production=True)

        assert [c.id for c in await registry.list_allowed_companies(principal, source_id)] == [
            company_a
        ]
        assert (await registry.require_company(principal, source_id, company_a)).id == company_a
        assert (await registry.require_source_for_company(principal, source_id, company_a)).id == source_id
        with pytest.raises(AccessDenied):
            await registry.require_company(principal, source_id, company_b)
        with pytest.raises(AccessDenied):
            await registry.require_source_for_company(principal, source_id, company_b)
        with pytest.raises(AccessDenied):
            await registry.require_source(principal, source_id)

        await conn.execute(
            "UPDATE bag.access_grants SET revoked_at=now() WHERE grant_id=$1", grant_a
        )
        with pytest.raises(AccessDenied):
            await registry.require_company(principal, source_id, company_a)
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_semantic_profile_validation_is_scoped_and_requires_ten_native_cases():
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    source_id = f"semantic-test-{uuid.uuid4()}"
    company_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    try:
        await conn.execute("SET LOCAL ROLE business_ai_admin")
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'Semantic test source',
                   'https://onec.example.test/odata')
            """,
            source_id,
        )
        await conn.execute(
            """
            INSERT INTO bag.companies(company_id, source_id, external_ref, display_name)
            VALUES($1, $2, 'semantic-company', 'Semantic test company')
            """,
            company_id,
            source_id,
        )
        await conn.execute(
            """
            INSERT INTO bag.semantic_profiles(
                profile_id, source_id, company_id, preset_id, profile_name, profile_version,
                status, metadata_fingerprint, capability_fingerprint, profile_fingerprint,
                preset_repository, preset_upstream_sha, created_by
            ) VALUES($1, $2, $3, 'bp30', 'BP 3.0 candidate', 1, 'DRAFT', $4, $5, $6, $7, $8, $9)
            """,
            profile_id,
            source_id,
            company_id,
            "metadata-" + "a" * 64,
            "capability-" + "b" * 64,
            "profile-" + "c" * 64,
            "https://github.com/theYahia/WWmcp",
            "7b62c90e1fe74324605dc28d76f195200bb97252",
            "integration-test",
        )
        await conn.execute(
            """
            INSERT INTO bag.semantic_mappings(
                mapping_id, profile_id, canonical_concept, mapping_json
            ) VALUES($1, $2, 'receivable', '{"status":"candidate"}'::jsonb)
            """,
            uuid.uuid4(),
            profile_id,
        )

        await conn.execute("SET LOCAL ROLE business_ai_app")
        assert await conn.fetchval(
            "SELECT count(*) FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        ) == 1
        assert not await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.semantic_profiles', 'UPDATE')"
        )
        await conn.execute("RESET ROLE")

        evidence = {
            "native_reconciliation_cases": [
                {"case_id": f"case-{i}", "status": "PASS", "native_report_ref": f"native/{i}"}
                for i in range(9)
            ]
        }
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE bag.semantic_profiles
                    SET status='VALIDATED', validated_by='tester', validated_at=now(),
                        validation_evidence_json=$2::jsonb
                    WHERE profile_id=$1
                    """,
                    profile_id,
                    json.dumps(evidence),
                )
        evidence["native_reconciliation_cases"].append(
            {"case_id": "case-9", "status": "FAIL", "native_report_ref": "native/9"}
        )
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE bag.semantic_profiles
                    SET status='VALIDATED', validated_by='tester', validated_at=now(),
                        validation_evidence_json=$2::jsonb
                    WHERE profile_id=$1
                    """,
                    profile_id,
                    json.dumps(evidence),
                )
        evidence["native_reconciliation_cases"][-1]["status"] = "PASS"
        await conn.execute(
            """
            UPDATE bag.semantic_profiles
            SET status='VALIDATED', validated_by='tester', validated_at=now(),
                validation_evidence_json=$2::jsonb
            WHERE profile_id=$1
            """,
            profile_id,
            json.dumps(evidence),
        )
        assert await conn.fetchval(
            "SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        ) == "VALIDATED"

        current_capability = OneCCapabilities(
            source_id=source_id,
            platform_version=None,
            metadata_fingerprint="metadata-" + "a" * 64,
            metadata_supported=True,
            json_supported=True,
            atom_supported=False,
            expand_supported=True,
            entity_set_count=1,
            adapter_profile=AdapterProfile.ODATA_JSON_V3,
            compatibility_status=CompatibilityStatus.SUPPORTED,
            evidence={"metadata": "ok"},
        )
        registry = Registry(ConnectionDatabase(conn), production=False)
        await registry.save_capabilities(current_capability)
        changed_capability = replace(
            current_capability, metadata_fingerprint="metadata-" + "d" * 64
        )
        await registry.save_capabilities(changed_capability)
        assert await conn.fetchval(
            "SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        ) == "STALE"
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_semantic_profile_admin_lifecycle_and_append_only_events(tmp_path):
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    source_id = f"semantic-admin-{uuid.uuid4()}"
    company_id = uuid.uuid4()
    try:
        await conn.execute("SET LOCAL ROLE business_ai_admin")
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'Semantic admin source',
                   'https://onec.example.test/odata')
            """,
            source_id,
        )
        await conn.execute(
            """
            INSERT INTO bag.companies(company_id, source_id, external_ref, display_name)
            VALUES($1, $2, 'semantic-admin-company', 'Semantic admin company')
            """,
            company_id,
            source_id,
        )
        await conn.execute("RESET ROLE")

        metadata_fingerprint = "semantic-metadata-" + "e" * 64
        register_capabilities = {
            "source_id": source_id,
            "metadata_fingerprint": metadata_fingerprint,
            "registers": [
                {
                    "entity_set": "AccountingRegister_Хозрасчетный",
                    "methods": {
                        "drCrTurnovers": {
                            "available": True,
                            "evidence": {"metadata_fingerprint": metadata_fingerprint},
                        },
                        "balanceAndTurnovers": {
                            "available": True,
                            "evidence": {"metadata_fingerprint": metadata_fingerprint},
                        },
                    },
                },
                {
                    "entity_set": "AccumulationRegister_ТоварыНаСкладах",
                    "methods": {
                        "Balance": {
                            "available": True,
                            "evidence": {"metadata_fingerprint": metadata_fingerprint},
                        }
                    },
                },
                {
                    "entity_set": "AccumulationRegister_ДенежныеСредстваБезналичные",
                    "methods": {
                        "Balance": {
                            "available": True,
                            "evidence": {"metadata_fingerprint": metadata_fingerprint},
                        }
                    },
                },
                {
                    "entity_set": "AccumulationRegister_РасчетыСКлиентами",
                    "methods": {
                        "Balance": {
                            "available": True,
                            "evidence": {"metadata_fingerprint": metadata_fingerprint},
                        }
                    },
                },
                {
                    "entity_set": "AccumulationRegister_РасчетыСПоставщиками",
                    "methods": {
                        "Balance": {
                            "available": True,
                            "evidence": {"metadata_fingerprint": metadata_fingerprint},
                        }
                    },
                },
            ],
        }
        capability = OneCCapabilities(
            source_id=source_id,
            platform_version=None,
            metadata_fingerprint=metadata_fingerprint,
            metadata_supported=True,
            json_supported=True,
            atom_supported=False,
            expand_supported=True,
            entity_set_count=1,
            adapter_profile=AdapterProfile.ODATA_JSON_V3,
            compatibility_status=CompatibilityStatus.SUPPORTED,
            evidence={"metadata": "ok"},
            register_capabilities=register_capabilities,
        )
        await Registry(ConnectionDatabase(conn), production=False).save_capabilities(capability)
        await conn.execute("SET LOCAL ROLE business_ai_admin")
        profile_id = await create_profile(
            Namespace(
                preset_id="bp30",
                source_id=source_id,
                company_id=str(company_id),
                profile_name="BP candidate",
                profile_file=None,
                actor="integration-operator",
            ),
            conn,
        )
        stored_profile_json = await conn.fetchval(
            "SELECT profile_json FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        )
        if isinstance(stored_profile_json, str):
            stored_profile_json = json.loads(stored_profile_json)
        candidate_entities = stored_profile_json["candidate_entities"]
        assert candidate_entities
        assert all(item["status"] == "CANDIDATE_ONLY" for item in candidate_entities)
        mapping_file = tmp_path / "mapping.json"
        mapping_file.write_text(
            json.dumps(
                {
                    "description": "integration candidate",
                    "required_register_capabilities": [
                        {
                            "entity_set": "AccountingRegister_Хозрасчетный",
                            "method": "drCrTurnovers",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        await add_mapping(
            Namespace(
                profile_id=str(profile_id),
                concept="receivable",
                mapping_file=str(mapping_file),
                evidence_file=None,
                actor="integration-operator",
            ),
            conn,
        )
        account_mapping_file = tmp_path / "account-mapping.json"
        account_mapping_file.write_text(
            json.dumps(
                {
                    "entity_set": "AccountingRegister_Хозрасчетный",
                    "method": "balanceAndTurnovers",
                    "company_scope": {"field": "Организация_Key", "value_type": "string"},
                    "output_fields": {
                        "account": "Account",
                        "opening_debit": "OpeningDebit",
                        "opening_credit": "OpeningCredit",
                        "debit_turnover": "DebitTurnover",
                        "credit_turnover": "CreditTurnover",
                        "closing_debit": "ClosingDebit",
                        "closing_credit": "ClosingCredit",
                    },
                }
            ),
            encoding="utf-8",
        )
        await add_mapping(
            Namespace(
                profile_id=str(profile_id),
                concept="account.balance_and_turnovers",
                mapping_file=str(account_mapping_file),
                evidence_file=None,
                actor="integration-operator",
            ),
            conn,
        )
        sales_mapping_file = tmp_path / "sales-mapping.json"
        sales_mapping_file.write_text(
            json.dumps(
                {
                    "entity_set": "Document_РеализацияТоваровУслуг",
                    "company_scope": {"field": "Организация_Key", "value_type": "string"},
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
            ),
            encoding="utf-8",
        )
        await add_mapping(
            Namespace(
                profile_id=str(profile_id),
                concept="sales",
                mapping_file=str(sales_mapping_file),
                evidence_file=None,
                actor="integration-operator",
            ),
            conn,
        )
        purchase_mapping_file = tmp_path / "purchase-mapping.json"
        purchase_mapping_file.write_text(
            json.dumps(
                {
                    "entity_set": "Document_ПоступлениеТоваровУслуг",
                    "company_scope": {"field": "Организация_Key", "value_type": "string"},
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
            ),
            encoding="utf-8",
        )
        await add_mapping(
            Namespace(
                profile_id=str(profile_id),
                concept="purchases",
                mapping_file=str(purchase_mapping_file),
                evidence_file=None,
                actor="integration-operator",
            ),
            conn,
        )
        inventory_mapping_file = tmp_path / "inventory-mapping.json"
        inventory_mapping_file.write_text(
            json.dumps(
                {
                    "entity_set": "AccumulationRegister_ТоварыНаСкладах",
                    "method": "Balance",
                    "company_scope": {"field": "Организация_Key", "value_type": "string"},
                    "output_fields": {
                        "item_ref": "Номенклатура_Key",
                        "warehouse_ref": "Склад_Key",
                        "quantity": "КоличествоBalance",
                    },
                }
            ),
            encoding="utf-8",
        )
        await add_mapping(
            Namespace(
                profile_id=str(profile_id),
                concept="inventory.balance",
                mapping_file=str(inventory_mapping_file),
                evidence_file=None,
                actor="integration-operator",
            ),
            conn,
        )
        bank_mapping_file = tmp_path / "bank-mapping.json"
        bank_mapping_file.write_text(
            json.dumps(
                {
                    "entity_set": "AccumulationRegister_ДенежныеСредстваБезналичные",
                    "method": "Balance",
                    "company_scope": {"field": "Организация_Key", "value_type": "string"},
                    "output_fields": {
                        "bank_account_ref": "БанковскийСчет_Key",
                        "currency_ref": "Валюта_Key",
                        "amount": "СуммаBalance",
                    },
                }
            ),
            encoding="utf-8",
        )
        await add_mapping(
            Namespace(
                profile_id=str(profile_id),
                concept="bank.balance",
                mapping_file=str(bank_mapping_file),
                evidence_file=None,
                actor="integration-operator",
            ),
            conn,
        )
        movement_mapping_file = tmp_path / "inventory-movement-mapping.json"
        movement_mapping_file.write_text(
            json.dumps(
                {
                    "entity_set": "AccumulationRegister_ТоварыНаСкладах",
                    "company_scope": {"field": "Организация_Key", "value_type": "string"},
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
                    "source_timezone": "Europe/Chisinau",
                    "order_by": "Period",
                }
            ),
            encoding="utf-8",
        )
        await add_mapping(
            Namespace(
                profile_id=str(profile_id),
                concept="inventory.movements",
                mapping_file=str(movement_mapping_file),
                evidence_file=None,
                actor="integration-operator",
            ),
            conn,
        )
        for concept, entity_set, mapping_file_name in (
            (
                "receivable.balance",
                "AccumulationRegister_РасчетыСКлиентами",
                "receivable-mapping.json",
            ),
            (
                "payable.balance",
                "AccumulationRegister_РасчетыСПоставщиками",
                "payable-mapping.json",
            ),
        ):
            settlement_mapping_file = tmp_path / mapping_file_name
            settlement_mapping_file.write_text(
                json.dumps(
                    {
                        "entity_set": entity_set,
                        "method": "Balance",
                        "company_scope": {
                            "field": "Организация_Key",
                            "value_type": "string",
                        },
                        "output_fields": {
                            "counterparty_ref": "CounterpartyRef",
                            "contract_ref": "ContractRef",
                            "amount": "AmountBalance",
                        },
                    }
                ),
                encoding="utf-8",
            )
            await add_mapping(
                Namespace(
                    profile_id=str(profile_id),
                    concept=concept,
                    mapping_file=str(settlement_mapping_file),
                    evidence_file=None,
                    actor="integration-operator",
                ),
                conn,
            )
        mapping_confirmation_file = tmp_path / "mapping-confirmation.json"
        mapping_confirmation_file.write_text(
            json.dumps(
                {
                    "evidence_refs": ["operator-review/account-scope"],
                    "notes": "Verified against the fixture metadata and mapping definition",
                }
            ),
            encoding="utf-8",
        )
        evidence_file = tmp_path / "native-evidence.json"
        evidence_file.write_text(
            json.dumps(
                {
                    "native_reconciliation_cases": [
                        {
                            "case_id": f"case-{i}",
                            "status": "PASS",
                            "native_report_ref": f"native-reports/{i}",
                        }
                        for i in range(10)
                    ]
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(SemanticProfileUnavailable):
            await Registry(ConnectionDatabase(conn), production=False).require_account_turnovers_mapping(
                source_id, company_id
            )
        with pytest.raises(ValueError, match="explicitly confirmed"):
            await validate_profile(
                Namespace(
                    profile_id=str(profile_id),
                    evidence_file=str(evidence_file),
                    actor="integration-operator",
                ),
                conn,
            )
        for concept in (
            "receivable",
            "account.balance_and_turnovers",
            "sales",
            "purchases",
            "inventory.balance",
            "inventory.movements",
            "bank.balance",
            "receivable.balance",
            "payable.balance",
        ):
            await confirm_mapping(
                Namespace(
                    profile_id=str(profile_id),
                    concept=concept,
                    evidence_file=str(mapping_confirmation_file),
                    actor="integration-operator",
                ),
                conn,
            )
        await validate_profile(
            Namespace(
                profile_id=str(profile_id),
                evidence_file=str(evidence_file),
                actor="integration-operator",
            ),
            conn,
        )
        assert await conn.fetchval(
            "SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        ) == "VALIDATED"
        loaded_account_mapping = await Registry(
            ConnectionDatabase(conn), production=False
        ).require_account_turnovers_mapping(source_id, company_id)
        assert loaded_account_mapping["mapping"]["entity_set"] == "AccountingRegister_Хозрасчетный"
        assert loaded_account_mapping["mapping"]["method"] == "balanceAndTurnovers"
        assert loaded_account_mapping["profile_fingerprint"]
        loaded_sales_mapping = await Registry(
            ConnectionDatabase(conn), production=False
        ).require_semantic_mapping(source_id, company_id, "sales")
        assert loaded_sales_mapping["mapping"]["entity_set"] == "Document_РеализацияТоваровУслуг"
        loaded_purchase_mapping = await Registry(
            ConnectionDatabase(conn), production=False
        ).require_semantic_mapping(source_id, company_id, "purchases")
        assert loaded_purchase_mapping["mapping"]["entity_set"] == (
            "Document_ПоступлениеТоваровУслуг"
        )
        loaded_inventory_mapping = await Registry(
            ConnectionDatabase(conn), production=False
        ).require_semantic_mapping(source_id, company_id, "inventory.balance")
        assert loaded_inventory_mapping["mapping"]["entity_set"] == (
            "AccumulationRegister_ТоварыНаСкладах"
        )
        loaded_inventory_movement_mapping = await Registry(
            ConnectionDatabase(conn), production=False
        ).require_semantic_mapping(source_id, company_id, "inventory.movements")
        assert loaded_inventory_movement_mapping["mapping"]["source_timezone"] == "Europe/Chisinau"
        loaded_bank_mapping = await Registry(
            ConnectionDatabase(conn), production=False
        ).require_semantic_mapping(source_id, company_id, "bank.balance")
        assert loaded_bank_mapping["mapping"]["entity_set"] == (
            "AccumulationRegister_ДенежныеСредстваБезналичные"
        )
        for concept, entity_set in (
            ("receivable.balance", "AccumulationRegister_РасчетыСКлиентами"),
            ("payable.balance", "AccumulationRegister_РасчетыСПоставщиками"),
        ):
            loaded_settlement_mapping = await Registry(
                ConnectionDatabase(conn), production=False
            ).require_semantic_mapping(source_id, company_id, concept)
            assert loaded_settlement_mapping["mapping"]["entity_set"] == entity_set
        with pytest.raises(SemanticProfileUnavailable):
            await Registry(ConnectionDatabase(conn), production=False).require_account_turnovers_mapping(
                source_id, uuid.uuid4()
            )
        await conn.execute(
            """
            UPDATE bag.semantic_mappings
            SET evidence_json=jsonb_set(evidence_json, '{notes}', '"post-validation-edit"')
            WHERE profile_id=$1 AND canonical_concept='account.balance_and_turnovers'
            """,
            profile_id,
        )
        assert await conn.fetchval(
            "SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        ) == "STALE"
        assert await conn.fetchval(
            "SELECT count(*) FROM bag.semantic_profile_events WHERE profile_id=$1", profile_id
        ) == 21

        await conn.execute("SET LOCAL ROLE business_ai_app")
        assert await conn.fetchval(
            "SELECT count(*) FROM bag.semantic_profile_events WHERE profile_id=$1", profile_id
        ) == 21
        assert not await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.semantic_profile_events', 'INSERT')"
        )
        await conn.execute("RESET ROLE")

        changed = replace(capability, metadata_fingerprint="semantic-metadata-" + "f" * 64)
        await Registry(ConnectionDatabase(conn), production=False).save_capabilities(changed)
        assert await conn.fetchval(
            "SELECT status FROM bag.semantic_profiles WHERE profile_id=$1", profile_id
        ) == "STALE"
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_postgres_runtime_role_is_read_only_except_append_only_audit():
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    source_id = f"role-test-{uuid.uuid4()}"
    request_id = uuid.uuid4()
    company_id = uuid.uuid4()
    try:
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'Role integration source',
                   'https://onec.example.test/odata')
            """,
            source_id,
        )
        await conn.execute(
            """
            INSERT INTO bag.companies(company_id, source_id, external_ref, display_name)
            VALUES($1, $2, 'audit-test', 'Audit integration company')
            """,
            company_id,
            source_id,
        )
        await conn.execute("SET LOCAL ROLE business_ai_app")

        assert await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.sources', 'SELECT')"
        )
        assert await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.audit_events', 'INSERT')"
        )
        assert not await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.sources', 'UPDATE')"
        )
        assert not await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.audit_events', 'UPDATE')"
        )
        assert await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM bag.sources WHERE source_id=$1)", source_id
        )
        principal = Principal(
            subject="role-test",
            client_id="role-test-client",
            scopes=frozenset({"onec:read"}),
            groups=frozenset(),
            claims={},
        )
        await Audit(ConnectionDatabase(conn), include_query=True).write(
            principal=principal,
            tool="onec_read",
            source_id=source_id,
            outcome="error",
            started_at=time.monotonic(),
            query={"entity_set": "Invoices", "top": 10},
            request_id=request_id,
            company_id=company_id,
            adapter_kind="ODATA_JSON_V3",
            adapter_version="test-1",
            upstream_sha="a" * 40,
            policy_version="acl-test-v1",
            metadata_fingerprint="b" * 64,
            profile_fingerprint="c" * 64,
            returned_items=0,
            response_bytes=0,
            truncated=False,
            detail_code="IntegrationTestError",
        )
        audit_row = await conn.fetchrow(
            "SELECT * FROM bag.audit_events WHERE request_id=$1", request_id
        )
        assert audit_row["company_id"] == company_id
        assert audit_row["source_id"] == source_id
        assert audit_row["request_id"] == request_id
        assert audit_row["query_fingerprint"] == query_fingerprint(
            {"entity_set": "Invoices", "top": 10}
        )
        assert audit_row["returned_items"] == 0
        assert audit_row["duration_ms"] >= 0
        assert audit_row["adapter_kind"] == "ODATA_JSON_V3"
        assert audit_row["adapter_version"] == "test-1"
        assert audit_row["upstream_sha"] == "a" * 40
        assert audit_row["policy_version"] == "acl-test-v1"
        assert audit_row["metadata_fingerprint"] == "b" * 64
        assert audit_row["profile_fingerprint"] == "c" * 64
        assert audit_row["response_bytes"] == 0
        assert audit_row["truncated"] is False
        assert audit_row["outcome"] == "error"
        assert audit_row["detail_code"] == "IntegrationTestError"

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE bag.audit_events SET detail_code='tampered' WHERE request_id=$1",
                    request_id,
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    "DELETE FROM bag.audit_events WHERE request_id=$1", request_id
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    "UPDATE bag.sources SET display_name='tampered' WHERE source_id=$1",
                    source_id,
                )
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_postgres_admin_role_can_manage_registry_but_not_audit_or_delete():
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    source_id = f"admin-role-test-{uuid.uuid4()}"
    company_id = uuid.uuid4()
    grant_id = uuid.uuid4()
    try:
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'Admin role integration source',
                   'https://onec.example.test/odata')
            """,
            source_id,
        )
        await conn.execute("SET LOCAL ROLE business_ai_admin")

        assert await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.sources', 'UPDATE')"
        )
        assert await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.access_grants', 'INSERT')"
        )
        assert await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.companies', 'INSERT')"
        )
        assert not await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.audit_events', 'INSERT')"
        )
        assert not await conn.fetchval(
            "SELECT has_table_privilege(current_user, 'bag.sources', 'DELETE')"
        )

        await conn.execute(
            "UPDATE bag.sources SET display_name='Admin-updated source' WHERE source_id=$1",
            source_id,
        )
        await conn.execute(
            """
            INSERT INTO bag.companies(company_id, source_id, external_ref, display_name)
            VALUES($1, $2, 'admin-company', 'Admin company')
            """,
            company_id,
            source_id,
        )
        await conn.execute(
            """
            INSERT INTO bag.access_grants(grant_id, principal_kind, principal_id, source_id)
            VALUES($1, 'subject', 'admin-test-subject', $2)
            """,
            grant_id,
            source_id,
        )
        await conn.execute(
            "UPDATE bag.access_grants SET revoked_at=now() WHERE grant_id=$1", grant_id
        )

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO bag.audit_events(
                      event_id, principal_subject, client_id, tool_name, outcome, duration_ms
                    ) VALUES($1, 'admin-test', 'admin-test', 'system_status', 'success', 0)
                    """,
                    uuid.uuid4(),
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with conn.transaction():
                await conn.execute("DELETE FROM bag.sources WHERE source_id=$1", source_id)
    finally:
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_postgres_capability_drift_is_sticky_until_admin_acknowledges():
    conn = await asyncpg.connect(DATABASE_URL)
    tx = conn.transaction()
    await tx.start()
    source_id = f"drift-test-{uuid.uuid4()}"
    try:
        await conn.execute(
            """
            INSERT INTO bag.sources(source_id, project, kind, display_name, base_url)
            VALUES($1, 'onec', 'onec_auto', 'Drift integration source',
                   'https://onec.example.test/odata')
            """,
            source_id,
        )
        registry = Registry(ConnectionDatabase(conn), production=True)

        def capability(fingerprint):
            return OneCCapabilities(
                source_id=source_id,
                platform_version="8.3.test",
                metadata_fingerprint=fingerprint,
                metadata_supported=True,
                json_supported=True,
                atom_supported=False,
                expand_supported=True,
                entity_set_count=3,
                adapter_profile=AdapterProfile.ODATA_JSON_V3,
                compatibility_status=CompatibilityStatus.SUPPORTED,
                evidence={"metadata": "ok"},
                register_capabilities={
                    "schema_version": 1,
                    "source_id": source_id,
                    "evidence_source": "live-metadata",
                    "metadata_fingerprint": fingerprint,
                    "registers": [{
                        "entity_set": "AccountingRegister_Хозрасчетный",
                        "methods": {
                            "drCrTurnovers": {
                                "available": True,
                                "evidence": {
                                    "kind": "metadata-get-function-import",
                                    "function_import": "DrCrTurnovers",
                                },
                            }
                        },
                    }],
                },
            )

        initial = await registry.save_capabilities(capability("a" * 64))
        assert initial["drift_status"] == "STABLE"
        assert initial["previous_metadata_fingerprint"] is None

        changed = await registry.save_capabilities(capability("b" * 64))
        assert changed["drift_status"] == "DRIFTED"
        assert changed["previous_metadata_fingerprint"] == "a" * 64
        assert changed["drift_detected_at"] is not None

        repeated = await registry.save_capabilities(capability("b" * 64))
        assert repeated["drift_status"] == "DRIFTED"
        with pytest.raises(ValueError, match="expected fingerprint"):
            await capability_ack_drift(
                Namespace(source_id=source_id, expected_fingerprint="c" * 64), conn
            )

        await conn.execute("SET LOCAL ROLE business_ai_admin")
        await capability_ack_drift(
            Namespace(source_id=source_id, expected_fingerprint="b" * 64), conn
        )
        acknowledged = await conn.fetchrow(
            "SELECT * FROM bag.source_capabilities WHERE source_id=$1", source_id
        )
        assert acknowledged["metadata_fingerprint"] == "b" * 64
        assert acknowledged["drift_acknowledged_at"] is not None
        register_profile = acknowledged["register_capabilities_json"]
        if isinstance(register_profile, str):
            register_profile = json.loads(register_profile)
        assert register_profile["evidence_source"] == "live-metadata"
        assert register_profile["metadata_fingerprint"] == "b" * 64
        assert register_profile["registers"][0]["methods"]["drCrTurnovers"]["available"] is True

        await conn.execute("RESET ROLE")
        stable = await registry.save_capabilities(capability("b" * 64))
        assert stable["drift_status"] == "STABLE"
        assert stable["previous_metadata_fingerprint"] == "a" * 64
        assert stable["drift_acknowledged_at"] is not None
    finally:
        await tx.rollback()
        await conn.close()
