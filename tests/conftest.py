from __future__ import annotations

import pytest

from tests.sc_stack import ServerThread


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
