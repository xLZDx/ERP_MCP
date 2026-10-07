from __future__ import annotations

import copy
import json
from datetime import UTC, datetime

import httpx
import pytest

from business_ai_gateway.adapters.onec.com_bridge_client import ComBridgeClient
from business_ai_gateway.adapters.onec.com_contract import ComBalanceRequest, ComBridgeError
from onec_com_bridge.app import create_app
from tests.com_bridge_fakes import (
    ACCOUNT_A,
    ACCOUNT_B,
    COMPANY,
    CP_REF,
    FINGERPRINT,
    OTHER_COMPANY,
    TOKEN,
    FakeRuntime,
    make_config,
    make_row,
)

URL = "http://127.0.0.1:8765"


def request(**over) -> ComBalanceRequest:
    values = {
        "binding_id": "bind-1", "binding_version": 3, "source_id": "src-1",
        "as_of": datetime(2026, 8, 31, 23, 59, 59, tzinfo=UTC), "company_external_ref": COMPANY,
        "account_keys": (ACCOUNT_A, ACCOUNT_B), "max_rows": 100,
    }
    values.update(over)
    return ComBalanceRequest(**values)


def bridge_transport(runtime: FakeRuntime) -> httpx.AsyncBaseTransport:
    app = create_app(make_config(), token=TOKEN, runtime=runtime, secret_loader=lambda _p: "pw")
    return httpx.ASGITransport(app=app)


def mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def good_envelope() -> dict:
    return {
        "binding_id": "bind-1", "binding_version": 3, "source_id": "src-1",
        "base_identity": {"clone_identity": "clone-a", "metadata_fingerprint": FINGERPRINT},
        "rows": [{
            "account_key": ACCOUNT_A, "company_ref": COMPANY,
            "analytics": [{"ref": CP_REF, "type": "Catalog.Контрагенты"}, {"ref": None, "type": None},
                          {"ref": None, "type": None}],
            "debit": "1.5", "credit": "0", "currency_ref": None,
        }],
        "truncated": False,
    }


def client(handler, **kw) -> ComBridgeClient:
    return ComBridgeClient(URL, TOKEN, 5, kw.pop("max_bytes", 100_000), transport=mock(handler))


@pytest.mark.parametrize("url", ["http://example.com", "http://10.0.0.1:1", "http://0.0.0.0:80", "ftp://127.0.0.1"])
def test_non_loopback_url_rejected(url):
    with pytest.raises(ValueError):
        ComBridgeClient(url, TOKEN, 5, 1000)


@pytest.mark.parametrize("url", ["http://127.0.0.1:1", "http://[::1]:1", "http://localhost:1"])
def test_loopback_urls_accepted(url):
    ComBridgeClient(url, TOKEN, 5, 1000)


async def test_end_to_end_against_the_real_bridge_app_with_fake_com():
    runtime = FakeRuntime(rows=[make_row(), make_row(ACCOUNT_B, [None, None, None], debit=0, credit="9.99")])
    c = ComBridgeClient(URL, TOKEN, 5, 100_000, transport=bridge_transport(runtime))
    response = await c.balance_by_analytics(request())
    assert (response.binding_id, response.binding_version, response.source_id) == ("bind-1", 3, "src-1")
    assert response.clone_identity == "clone-a" and response.metadata_fingerprint == FINGERPRINT
    assert len(response.rows) == 2 and response.truncated is False
    assert response.rows[1]["credit"] == "9.99"
    await c.close()


async def test_bridge_error_codes_map_through():
    runtime = FakeRuntime()
    c = ComBridgeClient(URL, TOKEN, 5, 100_000, transport=bridge_transport(runtime))
    with pytest.raises(ComBridgeError) as denied:
        await c.balance_by_analytics(request(company_external_ref=OTHER_COMPANY))
    assert denied.value.code == "COM_COMPANY_DENIED"
    with pytest.raises(ComBridgeError) as mismatch:
        await c.balance_by_analytics(request(binding_version=9))
    assert mismatch.value.code == "COM_BINDING_MISMATCH"
    bad = ComBridgeClient(URL, "x" * 40, 5, 100_000, transport=bridge_transport(runtime))
    with pytest.raises(ComBridgeError) as unauth:
        await bad.balance_by_analytics(request())
    assert unauth.value.code == "COM_UNAUTHORIZED"
    assert runtime.connects == []


async def test_request_wire_and_bearer_header():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        seen["path"] = req.url.path
        return httpx.Response(200, json=good_envelope())

    await client(handler).balance_by_analytics(request())
    assert seen["auth"] == f"Bearer {TOKEN}" and seen["path"] == "/v1/balance_by_analytics"
    assert set(seen["body"]) == {"binding_id", "binding_version", "source_id", "as_of",
                                 "company_external_ref", "account_keys", "max_rows"}
    assert seen["body"]["as_of"].endswith("+00:00")


async def test_naive_as_of_refused_locally():
    with pytest.raises(ComBridgeError) as err:
        await client(lambda r: httpx.Response(200, json=good_envelope())).balance_by_analytics(
            request(as_of=datetime(2026, 1, 1))  # noqa: DTZ001
        )
    assert err.value.code == "COM_BAD_REQUEST"


def _mutated(path, value=None, delete=False):
    env = copy.deepcopy(good_envelope())
    target = env
    for key in path[:-1]:
        target = target[key]
    if delete:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return env


@pytest.mark.parametrize(
    "envelope",
    [
        _mutated(["binding_id"], "other"),
        _mutated(["binding_version"], 4),
        _mutated(["binding_version"], True),
        _mutated(["source_id"], "other"),
    ],
)
async def test_echo_mismatch_is_binding_mismatch(envelope):
    with pytest.raises(ComBridgeError) as err:
        await client(lambda r: httpx.Response(200, json=envelope)).balance_by_analytics(request())
    assert err.value.code == "COM_BINDING_MISMATCH"


@pytest.mark.parametrize(
    "envelope",
    [
        [],
        _mutated(["base_identity"], None),
        _mutated(["base_identity", "metadata_fingerprint"], "short"),
        _mutated(["base_identity", "clone_identity"], ""),
        _mutated(["rows"], "x"),
        _mutated(["truncated"], "no"),
        _mutated(["rows", 0, "analytics"], [{"ref": None, "type": None}] * 2),
        _mutated(["rows", 0, "analytics"], [{"ref": None, "type": None}] * 4),
        _mutated(["rows", 0, "analytics", 0, "ref"], "not-a-guid"),
        _mutated(["rows", 0, "analytics", 0, "type"], "Report.X"),
        _mutated(["rows", 0, "analytics", 1, "ref"], CP_REF),  # ref without a type
        _mutated(["rows", 0, "debit"], "1e5"),
        _mutated(["rows", 0, "credit"], 5),
        _mutated(["rows", 0, "account_key"], "bbbbbbbb-0000-0000-0000-000000000009"),
        _mutated(["rows", 0, "currency_ref"], "nope"),
        _mutated(["rows", 0, "extra"], 1),
        _mutated(["rows", 0, "currency_ref"], None, delete=True),
        _mutated(["rows", 0, "company_ref"], "22222222-2222-2222-2222-222222222222"),
        _mutated(["rows", 0, "company_ref"], None),
        _mutated(["rows", 0, "company_ref"], None, delete=True),
    ],
)
async def test_malformed_response_rejected(envelope):
    with pytest.raises(ComBridgeError) as err:
        await client(lambda r: httpx.Response(200, json=envelope)).balance_by_analytics(request())
    assert err.value.code == "COM_INTERNAL"


async def test_row_count_above_request_cap_rejected():
    env = good_envelope()
    env["rows"] = env["rows"] * 3
    with pytest.raises(ComBridgeError) as err:
        await client(lambda r: httpx.Response(200, json=env)).balance_by_analytics(request(max_rows=2))
    assert err.value.code == "COM_INTERNAL"


async def test_response_size_is_bounded():
    big = httpx.Response(200, content=b'{"x":"' + b"a" * 5000 + b'"}')
    with pytest.raises(ComBridgeError) as err:
        await client(lambda r: big, max_bytes=1000).balance_by_analytics(request())
    assert err.value.code == "COM_INTERNAL"


async def test_http_and_transport_problems_are_sanitized():
    def refuse(req):
        raise httpx.ConnectError("secret detail C:\\path")

    def slow(req):
        raise httpx.ReadTimeout("secret detail")

    with pytest.raises(ComBridgeError) as err:
        await client(refuse).balance_by_analytics(request())
    assert err.value.code == "COM_UNAVAILABLE" and "secret" not in str(err.value)
    with pytest.raises(ComBridgeError) as err:
        await client(slow).balance_by_analytics(request())
    assert err.value.code == "COM_TIMEOUT"
    for status, code in ((500, "COM_UNAVAILABLE"), (404, "COM_INTERNAL"), (401, "COM_UNAUTHORIZED")):
        with pytest.raises(ComBridgeError) as err:
            await client(lambda r, s=status: httpx.Response(s, text="<html>trace</html>")).balance_by_analytics(
                request()
            )
        assert err.value.code == code
    with pytest.raises(ComBridgeError) as err:
        await client(lambda r: httpx.Response(200, text="not json")).balance_by_analytics(request())
    assert err.value.code == "COM_INTERNAL"
    with pytest.raises(ComBridgeError) as err:
        await client(
            lambda r: httpx.Response(503, json={"error": {"code": "COM_TIMEOUT", "detail": "x"}})
        ).balance_by_analytics(request())
    assert err.value.code == "COM_TIMEOUT"


async def test_redirects_are_not_followed():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(307, headers={"location": "http://127.0.0.1:9/elsewhere"})

    with pytest.raises(ComBridgeError):
        await client(handler).balance_by_analytics(request())
    assert len(calls) == 1


def test_client_does_not_trust_environment_proxies(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    c = ComBridgeClient(URL, TOKEN, 5, 1000)
    assert c._client.trust_env is False
