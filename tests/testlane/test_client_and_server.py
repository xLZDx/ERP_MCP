"""Gateway client against a local fake HTTP gateway, bearer guard, tool registration, no token leaks."""
from __future__ import annotations

import asyncio
import json
import threading
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from testlane.phase2_mcp.config import GatewayConfig, load_config
from testlane.phase2_mcp.gateway_client import Gateway, GatewayError
from testlane.phase2_mcp.reconcile import Reconciler
from testlane.phase2_mcp.server import BearerGuard, build_server

TOKEN = "tok-SECRET-VALUE-123"


def _serve(handler_cls):
    srv = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class _Ok(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert self.headers["Authorization"] == "Bearer " + TOKEN
        if "id" not in body:
            self.send_response(202)
            self.end_headers()
            return
        if body["method"] == "initialize":
            result = {"protocolVersion": "2025-03-26"}
        else:
            result = {"structuredContent": {"value": [{"amount": 1.10}]}, "isError": False}
        data = "event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": 1, "result": result}) + "\n\n"
        self.send_response(200)
        self.send_header("Mcp-Session-Id", "s1")
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(data.encode())


class _Deny(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.send_response(401)
        self.end_headers()


def test_client_parses_sse_and_floats_as_decimal():
    srv = _serve(_Ok)
    try:
        gw = Gateway(GatewayConfig("A", f"http://127.0.0.1:{srv.server_port}/mcp", lambda: TOKEN), 5)
        out = gw.call("t", {})
        assert out["value"][0]["amount"] == Decimal("1.10")
        assert isinstance(out["value"][0]["amount"], Decimal)
    finally:
        srv.shutdown()


def test_auth_rejection_and_unreachable_are_safe_codes():
    srv = _serve(_Deny)
    try:
        gw = Gateway(GatewayConfig("A", f"http://127.0.0.1:{srv.server_port}/mcp", lambda: TOKEN), 5)
        with pytest.raises(GatewayError) as exc:
            gw.call("t", {})
        assert exc.value.code == "GATEWAY_AUTH_REJECTED" and TOKEN not in str(exc.value)
    finally:
        srv.shutdown()
    gw = Gateway(GatewayConfig("A", "http://127.0.0.1:9/mcp", lambda: TOKEN), 2)
    with pytest.raises(GatewayError) as exc:
        gw.call("t", {})
    assert exc.value.code == "GATEWAY_UNREACHABLE" and TOKEN not in repr(exc.value)


def test_missing_token_code_and_config_repr_hides_token():
    gw = Gateway(GatewayConfig("A", "http://127.0.0.1:9/mcp", None), 2)
    with pytest.raises(GatewayError) as exc:
        gw.call("t", {})
    assert exc.value.code == "GATEWAY_TOKEN_UNAVAILABLE"
    cfg = load_config({"TESTLANE_A_TOKEN": TOKEN, "TESTLANE_INBOUND_TOKEN": TOKEN})
    assert TOKEN not in repr(cfg) and cfg.side_a.configured and not cfg.side_b.configured
    assert (cfg.host, cfg.port) == ("127.0.0.1", 21200)


def test_tools_registered_and_capabilities_honest(make_reconciler):
    rec, _, _ = make_reconciler({}, {})
    mcp = build_server(rec, {"side_a_configured": True, "side_b_configured": False})
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert names == {"phase2_capabilities", "phase2_reconcile_two_bases",
                     "phase2_reconcile_negative_control"}
    from testlane.phase2_mcp.reconcile import capabilities
    cap = capabilities({"a": True})
    assert cap["phase2_status_ceiling"] == "IMPLEMENTED_UNVERIFIED" and cap["gates_passed"] == []
    assert any(m["module"] == "reconciliation" and m["exposed_in_testlane"] for m in cap["phase2_modules"])
    assert any("ENQUEUE_JOB" in x for x in cap["not_covered"])


def test_bearer_guard_rejects_without_token():
    sent = []

    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    async def send(msg):
        sent.append(msg)

    guard = BearerGuard(inner, TOKEN)

    def call(headers):
        sent.clear()
        asyncio.run(guard({"type": "http", "headers": headers}, None, send))
        return sent[0]["status"]

    assert call([]) == 401
    assert call([(b"authorization", b"Bearer wrong")]) == 401
    assert call([(b"authorization", b"Bearer " + TOKEN.encode())]) == 200


def test_reconciler_output_never_contains_token(make_reconciler):
    from _testlane_helpers import AS_OF, COMPANY, END, START, standard_responses
    rec, _, _ = make_reconciler(standard_responses(), standard_responses())
    assert isinstance(rec, Reconciler)
    assert TOKEN not in json.dumps(rec.reconcile_two_bases(COMPANY, AS_OF, START, END))
