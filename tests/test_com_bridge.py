from __future__ import annotations

import ast
import hashlib
import json
import threading
from pathlib import Path

import httpx
import pytest

from onec_com_bridge import query as bridge_query
from onec_com_bridge.app import create_app
from onec_com_bridge.config import BridgeConfig, ConfigError, load_config, read_token
from tests.com_bridge_fakes import (
    ACCOUNT_A,
    ACCOUNT_B,
    COMPANY,
    CONTRACT_REF,
    CP_REF,
    FINGERPRINT,
    OTHER_COMPANY,
    TOKEN,
    FakeRuntime,
    binding_dict,
    config_dict,
    good_request,
    make_config,
    make_row,
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "onec_com_bridge"
SECRET_PASSWORD = "pw-secret-123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def client(runtime: FakeRuntime, **config_over) -> httpx.AsyncClient:
    app = create_app(
        make_config(**config_over), token=TOKEN, runtime=runtime, secret_loader=lambda _p: SECRET_PASSWORD
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")


async def post(c: httpx.AsyncClient, body, headers=AUTH):
    return await c.post("/v1/balance_by_analytics", content=json.dumps(body), headers=headers)


# --- config ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com", "::"])
def test_config_rejects_non_loopback(host):
    with pytest.raises(ValueError):
        BridgeConfig.model_validate(config_dict(listen_host=host))


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_config_accepts_loopback(host):
    assert make_config(listen_host=host).listen_host == host


def test_config_strict_schema():
    with pytest.raises(ValueError):
        BridgeConfig.model_validate(config_dict(extra_key=1))
    with pytest.raises(ValueError):
        BridgeConfig.model_validate(config_dict(bindings=[binding_dict(unknown=1)]))
    with pytest.raises(ValueError):
        BridgeConfig.model_validate(config_dict(bindings=[binding_dict(), binding_dict()]))
    with pytest.raises(ValueError):
        BridgeConfig.model_validate(config_dict(bindings=[binding_dict(base_path='C:\\x";Usr="admin')]))
    with pytest.raises(ValueError):
        BridgeConfig.model_validate(config_dict(bindings=[binding_dict(allowed_company_refs=["NOT-A-GUID"])]))
    with pytest.raises(ValueError):
        BridgeConfig.model_validate(config_dict(bindings=[binding_dict(metadata_fingerprint="abc")]))


def test_load_config_and_token_errors_leak_nothing(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(config_dict(listen_host="10.0.0.9")), encoding="utf-8")
    with pytest.raises(ConfigError) as err:
        load_config(path)
    assert "10.0.0.9" not in str(err.value)
    path.write_text(json.dumps(config_dict()), encoding="utf-8")
    assert load_config(path).listen_port == 8765
    token = tmp_path / "t.txt"
    token.write_text("short", encoding="utf-8")
    with pytest.raises(ConfigError):
        read_token(token)
    token.write_text(TOKEN + "\n", encoding="utf-8")
    assert read_token(token) == TOKEN


# --- auth and validation -------------------------------------------------------------------------------------------
async def test_auth_required_without_body_detail():
    runtime = FakeRuntime()
    async with client(runtime) as c:
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic " + TOKEN}):
            response = await post(c, good_request(), headers)
            assert response.status_code == 401
            assert response.json() == {"error": {"code": "COM_UNAUTHORIZED"}}
        assert (await c.get("/v1/identity", params={"binding_id": "bind-1"})).status_code == 401
        assert (await c.get("/healthz")).json() == {"status": "ok"}
    assert runtime.connects == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"extra": 1},
        {"base_path": "C:\\other"},
        {"query": "SELECT 1"},
        {"reader_user": "admin"},
        {"account_keys": []},
        {"account_keys": [f"aaaaaaaa-0000-0000-0000-{i:012d}" for i in range(17)]},
        {"account_keys": [ACCOUNT_A, ACCOUNT_A]},
        {"account_keys": [ACCOUNT_A.upper()]},
        {"account_keys": ["not-a-guid"]},
        {"as_of": "2026-08-31T23:59:59"},
        {"as_of": "yesterday"},
        {"max_rows": 0},
        {"max_rows": 5001},
        {"max_rows": True},
        {"binding_version": "3"},
        {"company_external_ref": "x"},
    ],
)
async def test_bad_requests_rejected_before_com(mutation):
    runtime = FakeRuntime()
    async with client(runtime) as c:
        response = await post(c, good_request(**mutation))
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "COM_BAD_REQUEST"}}
    assert runtime.connects == []


async def test_non_json_and_oversized_rejected():
    runtime = FakeRuntime()
    async with client(runtime) as c:
        r1 = await c.post("/v1/balance_by_analytics", content=b"not json", headers=AUTH)
        r2 = await c.post("/v1/balance_by_analytics", content=b"{" + b" " * 70000 + b"}", headers=AUTH)
    assert r1.status_code == r2.status_code == 400
    assert runtime.connects == []


@pytest.mark.parametrize(
    "mutation", [{"binding_id": "bind-2"}, {"binding_version": 4}, {"source_id": "src-2"}]
)
async def test_binding_must_match_exactly(mutation):
    runtime = FakeRuntime()
    async with client(runtime) as c:
        response = await post(c, good_request(**mutation))
    assert response.status_code == 403
    assert response.json() == {"error": {"code": "COM_BINDING_MISMATCH"}}
    assert runtime.connects == []


async def test_company_denied_before_any_com_call():
    runtime = FakeRuntime()
    async with client(runtime) as c:
        response = await post(c, good_request(company_external_ref=OTHER_COMPANY))
    assert response.status_code == 403
    assert response.json() == {"error": {"code": "COM_COMPANY_DENIED"}}
    assert runtime.connects == []


async def test_missing_attested_fingerprint_is_refused():
    runtime = FakeRuntime()
    async with client(runtime, bindings=[binding_dict(metadata_fingerprint=None)]) as c:
        response = await post(c, good_request())
    assert response.status_code == 503
    assert runtime.connects == []


# --- execution -------------------------------------------------------------------------------------------------------
async def test_success_wire_shape_and_parameters_only():
    rows = [
        make_row(ACCOUNT_A, [CP_REF, CONTRACT_REF, None], debit="100.25", credit=0,
                 kinds=["Справочник.Контрагенты", "Документ.Договор", None]),
        make_row(ACCOUNT_B, [None, None, None], debit=0, credit="7"),
    ]
    runtime = FakeRuntime(rows=rows)
    request = good_request()
    async with client(runtime) as c:
        response = await post(c, request)
    assert response.status_code == 200
    body = response.json()
    assert body["base_identity"] == {"clone_identity": "clone-a", "metadata_fingerprint": FINGERPRINT}
    assert body["truncated"] is False
    assert body["rows"][0] == {
        "account_key": ACCOUNT_A,
        "analytics": [
            {"ref": CP_REF, "type": "Catalog.Контрагенты"},
            {"ref": CONTRACT_REF, "type": "Document.Договор"},
            {"ref": None, "type": None},
        ],
        "debit": "100.25", "credit": "0", "currency_ref": None,
    }
    assert body["rows"][1]["analytics"] == [{"ref": None, "type": None}] * 3
    # the connection was opened as the reader on the bound base, nothing came from the request
    assert runtime.connects == [{"base_path": "C:\\clones\\clone_a", "user": "reader_user"}]
    text, params = runtime.conns[0].executed[0]
    assert text == bridge_query.BALANCE_QUERY_TEMPLATE
    for value in (COMPANY, ACCOUNT_A, ACCOUNT_B, "2026", "100"):
        assert value not in text
    assert set(params) == {"Период", "Счета", "Организация"}
    assert params["Период"].year == 2026 and params["Период"].tzinfo is None
    assert [r.guid for r in params["Счета"]] == [ACCOUNT_A, ACCOUNT_B]
    assert params["Организация"].guid == COMPANY
    assert runtime.conns[0].new_objects == ["Array", "TypeDescription", "TypeDescription", "TypeDescription", "Query"]


async def test_row_cap_sets_truncated_and_connection_is_reused():
    runtime = FakeRuntime(rows=[make_row() for _ in range(5)])
    async with client(runtime) as c:
        first = await post(c, good_request(max_rows=3))
        second = await post(c, good_request(max_rows=10))
    assert len(first.json()["rows"]) == 3 and first.json()["truncated"] is True
    assert len(second.json()["rows"]) == 5 and second.json()["truncated"] is False
    assert len(runtime.connects) == 1


async def test_exact_cap_is_not_truncated():
    runtime = FakeRuntime(rows=[make_row() for _ in range(3)])
    async with client(runtime) as c:
        body = (await post(c, good_request(max_rows=3))).json()
    assert len(body["rows"]) == 3 and body["truncated"] is False


async def test_unknown_metadata_kind_fails_closed():
    runtime = FakeRuntime(rows=[make_row(kinds=["Отчет.Что-то", None, None])])
    async with client(runtime) as c:
        response = await post(c, good_request())
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "COM_INTERNAL"}}


async def test_row_outside_requested_accounts_fails_closed():
    runtime = FakeRuntime(rows=[make_row("bbbbbbbb-0000-0000-0000-000000000009")])
    async with client(runtime) as c:
        response = await post(c, good_request())
    assert response.status_code == 500


async def test_non_reference_analytics_value_fails_closed():
    row = make_row()
    row.Субконто2 = "plain string"
    runtime = FakeRuntime(rows=[row])
    async with client(runtime) as c:
        response = await post(c, good_request())
    assert response.status_code == 500


async def test_connect_failure_is_sanitized_and_retried_next_call(caplog):
    runtime = FakeRuntime(fail_connect=True)
    async with client(runtime) as c:
        response = await post(c, good_request())
        assert response.status_code == 503
        assert response.json() == {"error": {"code": "COM_UNAVAILABLE"}}
        runtime.fail_connect = False
        assert (await post(c, good_request())).status_code == 200
    blob = response.text + caplog.text
    assert SECRET_PASSWORD not in blob and "clone_a" not in blob and COMPANY not in caplog.text


async def test_wrong_connected_identity_is_refused():
    runtime = FakeRuntime(user="somebody_else")
    async with client(runtime) as c:
        response = await post(c, good_request())
    assert response.status_code == 503


async def test_timeout_marks_connection_unhealthy():
    gate = threading.Event()
    runtime = FakeRuntime(block=gate)
    try:
        async with client(runtime, call_timeout_seconds=0.3) as c:
            response = await post(c, good_request())
            assert response.status_code == 504
            assert response.json() == {"error": {"code": "COM_TIMEOUT"}}
            gate.set()
            runtime.block = None
            assert (await post(c, good_request())).status_code == 200
        assert len(runtime.connects) == 2  # a fresh connection after the timeout
    finally:
        gate.set()


async def test_identity_endpoint_has_no_business_data():
    runtime = FakeRuntime()
    async with client(runtime) as c:
        response = await c.get("/v1/identity", params={"binding_id": "bind-1"}, headers=AUTH)
        missing = await c.get("/v1/identity", params={"binding_id": "nope"}, headers=AUTH)
    assert response.json() == {
        "binding_id": "bind-1", "binding_version": 3, "source_id": "src-1",
        "clone_identity": "clone-a", "metadata_fingerprint": FINGERPRINT,
    }
    assert missing.status_code == 403
    assert runtime.connects == []


# --- static guarantees -------------------------------------------------------------------------------------------
def test_template_is_pinned_and_split_amount_fields():
    digest = hashlib.sha256(bridge_query.BALANCE_QUERY_TEMPLATE.encode("utf-8")).hexdigest()
    assert digest == "ee4d135cc74b590074d926e460237f19f1bb617340ff403cf18a634cd4d84603"
    assert "СуммаРазвернутыйОстатокДт" in bridge_query.BALANCE_QUERY_TEMPLATE
    assert "&Период" in bridge_query.BALANCE_QUERY_TEMPLATE


FORBIDDEN_ATTRS = {
    "Write", "Delete", "CreateItem", "SetDeletionMark", "Run", "Set", "Insert",
    "Update", "Create", "GetObject", "ПолучитьОбъект", "Записать", "Удалить", "Выполнить",
}
FORBIDDEN_NAMES = {"eval", "exec", "compile", "getattr", "setattr", "__import__"}
ALLOWED_NEW_OBJECTS = {"Query", "Array"}


def _modules():
    return sorted(PACKAGE.glob("*.py"))


def test_no_write_path_in_bridge_source():
    assert _modules()
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in FORBIDDEN_ATTRS, f"{path.name}: {node.attr}"
            if isinstance(node, ast.Name):
                assert node.id not in FORBIDDEN_NAMES, f"{path.name}: {node.id}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "Execute":
                    assert not node.args and not node.keywords, "Execute never takes an argument"
                if node.func.attr == "NewObject":
                    arg = node.args[0]
                    assert isinstance(arg, ast.Constant)
                    if arg.value == "TypeDescription":
                        # only the code-owned type-name constants reach it, through the single _ref helper
                        assert path.name == "query.py" and len(node.args) == 2
                        assert isinstance(node.args[1], ast.Name) and node.args[1].id == "type_name"
                    else:
                        assert len(node.args) == 1 and arg.value in ALLOWED_NEW_OBJECTS
                if node.func.attr == "SetParameter":
                    assert isinstance(node.args[0], ast.Constant)


def test_query_text_is_only_ever_the_constant():
    tree = ast.parse((PACKAGE / "query.py").read_text(encoding="utf-8"))
    assigns = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "Text" for t in n.targets)
    ]
    assert len(assigns) == 1
    assert isinstance(assigns[0].value, ast.Name) and assigns[0].value.id == "BALANCE_QUERY_TEMPLATE"
    template_node = next(
        n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "BALANCE_QUERY_TEMPLATE"
    )
    assert not any(isinstance(n, (ast.JoinedStr, ast.FormattedValue)) for n in ast.walk(template_node))


def test_gateway_never_imports_the_bridge():
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "onec_com_bridge" not in text, path
        assert "win32com" not in text and "pythoncom" not in text, path
    assert "pywin32" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()


def test_error_codes_match_gateway_client():
    from business_ai_gateway.adapters.onec import com_bridge_client as gateway
    from onec_com_bridge import errors

    assert set(errors.STATUS_BY_CODE) == set(gateway.COM_CODES)
