from starlette.testclient import TestClient

from business_ai_gateway.testbed.fake1c import SEED, create_app


def test_fake1c_is_read_only_and_serves_metadata():
    client = TestClient(create_app("json"))
    response = client.get("/odata/standard.odata/$metadata")
    assert response.status_code == 200
    assert b"Catalog_Organizations" in response.content

    response = client.get(
        "/odata/standard.odata/Catalog_Organizations",
        headers={"Accept": "application/json"},
        params={"$top": 1},
    )
    assert response.status_code == 200
    assert len(response.json()["d"]["results"]) == 1

    assert client.post("/odata/standard.odata/Catalog_Organizations").status_code == 405


def test_fake1c_serves_the_versioned_seed_for_documents_and_semantic_balance_fixtures():
    client = TestClient(create_app("json"))
    metadata = client.get("/odata/standard.odata/$metadata").content
    assert b"Document_Purchases" in metadata
    assert b"AccumulationRegister_InventoryBalances" in metadata
    assert b"AccumulationRegister_BankBalances" in metadata

    expected = {
        "Document_Purchases": "purchases",
        "AccumulationRegister_InventoryBalances": "inventory_balances",
        "AccumulationRegister_BankBalances": "bank_balances",
        "AccumulationRegister_ReceivableBalances": "receivable_balances",
        "AccumulationRegister_PayableBalances": "payable_balances",
    }
    for entity_set, seed_key in expected.items():
        response = client.get(f"/odata/standard.odata/{entity_set}")
        assert response.status_code == 200
        assert response.json()["d"]["results"] == SEED[seed_key]
        assert client.post(f"/odata/standard.odata/{entity_set}").status_code == 405
