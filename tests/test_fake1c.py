from starlette.testclient import TestClient

from testbed.fake1c.app import create_app


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
