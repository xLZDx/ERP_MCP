from __future__ import annotations

import os

import pytest

from tests.sc_stack import ServerThread


@pytest.fixture
def require_pg_database():
    if not os.getenv("BAG_PRIVILEGE_TEST_DATABASE_URL"):
        pytest.fail("ERP_MCP_REQUIRE_DB_TESTS=1 but BAG_PRIVILEGE_TEST_DATABASE_URL is not set")


@pytest.fixture(scope="module")
def fake1c():
    from testbed.fake1c.app import create_app

    with ServerThread(create_app("json")) as server:
        yield f"http://127.0.0.1:{server.port}"


@pytest.fixture(scope="module")
def fake_sidecar():
    from business_ai_gateway.testbed.fake_sidecar import create_sidecar_app

    with ServerThread(create_sidecar_app("t" * 40)) as server:
        yield f"http://127.0.0.1:{server.port}"
