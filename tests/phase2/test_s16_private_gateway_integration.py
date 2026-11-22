"""S16 private MCP gateway contract, exercised with TEST identities and in-memory ports."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from starlette.testclient import TestClient

from erp_mcp_s16.ingress import ExactPrivateListenerRouteProbe, PrivateNetworkConfig
from erp_mcp_s16.private_gateway import create_private_s16_gateway_app, serve_private_s16_gateway
from erp_mcp_s16.com_apply_port import S14ComDraftApplyPort
from erp_mcp_s16.contracts import ApplyReceipt, ClaimToken, Result, TargetScope
from erp_mcp_s16.fakes import FakeProposalPort
from erp_mcp_s16.registries import InMemoryTargetRegistry
from erp_mcp_s16.tools import S16_TOOL_MANIFEST
from erp_mcp_private_writer.com_draft_executor import DraftDestinationSet, ExecutorResult
from erp_mcp_private_writer.com_manifest import PayloadPropertyBinding
from erp_mcp_private_writer.com_sta_lane import ComStaLane
from erp_mcp_private_writer.windows_com_lane import (
    WindowsComStaLane,
    _WINDOWS_LANE_FACTORY_TOKEN,
)
from s16_helpers import NOW, ORIGIN, build_env, propose

TEST_FINGERPRINT = "a" * 64
HEADER_PATHS = (
    "organization_ref", "counterparty_ref", "contract_ref", "supplier_document_number",
    "supplier_document_date", "currency", "comment",
)
LINE_PATHS = (
    "lines[0].item_ref", "lines[0].quantity", "lines[0].price", "lines[0].vat_rate_code",
    "lines[0].amount", "lines[0].vat_amount",
)
COM_BINDINGS = tuple(
    PayloadPropertyBinding(path, path.replace(".", "_").replace("[0]", ""), "SetValue", "String")
    for path in HEADER_PATHS + LINE_PATHS
)
COM_DESTINATIONS = DraftDestinationSet(
    "Receipt",
    tuple((path, f"Header{index}") for index, path in enumerate(HEADER_PATHS)),
    "Lines",
    tuple((path, f"Line{index}") for index, path in enumerate(LINE_PATHS)),
    (),
    "ChangeId",
    "ManifestHash",
    constants=(("IncludesVat", True),),
    dates=("supplier_document_date",),
    numbers=("lines[0].quantity", "lines[0].price", "lines[0].amount", "lines[0].vat_amount"),
)


def _retarget_env(env, fingerprint=TEST_FINGERPRINT):
    old_scope = env.requester.scope
    scope = TargetScope(old_scope.tenant, old_scope.company, old_scope.organization,
                        fingerprint, "TEST")
    env.requester = replace(env.requester, scope=scope)
    env.approver = replace(env.approver, scope=scope)
    env.session = env.idp.issue(env.approver, NOW, credential=env.test_credential)
    assert env.session is not None
    env.approver = env.session.principal
    target = env.targets.current(old_scope)
    targets = InMemoryTargetRegistry((replace(target, scope=scope),))
    env.targets = targets
    env.core.targets = targets
    env.change_service.proposal_port = FakeProposalPort(targets, env.principals)
    return env


def _approve_with_reauthentication(env):
    snapshot = propose(env)
    page = env.approval_service.open_preview(env.approver, env.session,
                                             snapshot.change_id, now=NOW)
    assert page.error is None, page.error
    reauthenticated = env.idp.reauthenticate(
        env.session, page.value.decision_ref, NOW + timedelta(seconds=1),
        credential=env.test_credential,
    )
    assert reauthenticated is not None
    env.session = reauthenticated
    approved = env.approval_service.submit_decision(
        env.approver, env.session, page.value.decision_ref, "APPROVE",
        confirmation_text="", csrf_token=page.value.csrf_token,
        origin=ORIGIN, referer=ORIGIN + "/approval/", now=NOW + timedelta(seconds=2),
    )
    assert approved.error is None, approved.error
    return snapshot


def _lane(*, fingerprint=TEST_FINGERPRINT, events=None):
    observed = events if events is not None else []

    def connect():
        observed.append("connected")
        return SimpleNamespace(connection=object())

    def disconnect(_session):
        observed.append("disconnected")

    lane = ComStaLane(
        connect=connect, disconnect=disconnect,
        initialize_sta=lambda: observed.append("initialized"),
        uninitialize_sta=lambda: observed.append("uninitialized"),
    )
    # This is an explicit adapter fixture. Production qualification is only issued by
    # windows_com_sta_lane after local-file and connected-base fingerprint checks.
    return WindowsComStaLane(
        lane, fingerprint, _factory_token=_WINDOWS_LANE_FACTORY_TOKEN,
    )


def _s14_port(lane=None):
    return S14ComDraftApplyPort(
        lane=lane or _lane(), expected_base_fingerprint=TEST_FINGERPRINT,
        bindings=COM_BINDINGS, destinations=COM_DESTINATIONS,
        includes_vat_property="IncludesVat",
        document_date=lambda: datetime(2026, 10, 29, 12, 0),
    )


class _Authenticator:
    def __init__(self, env):
        self.env = env
        self.calls = []

    def authenticate(self, _scope, headers):
        self.calls.append(headers.get("authorization"))
        now = datetime.now(UTC)
        if headers.get("authorization") == "Bearer requester-one":
            return replace(self.env.requester, expires_at=now + timedelta(hours=1))
        if headers.get("authorization") == "Bearer requester-two":
            return replace(self.env.requester, principal_id="requester-two",
                           person_id="person-two", expires_at=now + timedelta(hours=1))
        if headers.get("authorization") == "Bearer invalid":
            return replace(self.env.requester, principal_id="",
                           expires_at=now + timedelta(hours=1))
        return None


class _ObservedChangeService:
    def __init__(self, inner):
        self.inner = inner
        self.status_principals = []

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def status(self, requester, change_id):
        self.status_principals.append(requester)
        return self.inner.status(requester, change_id)


def _gateway(env, *, authenticator=None, service=None, config=None, s14_apply_port=None):
    class UnusedApprovalAuthenticator:
        def authenticate(self, _scope, _headers):
            return None

        def reauthenticate(self, _scope, _headers, _session, **_kwargs):
            return None

    return create_private_s16_gateway_app(
        change_service=service or env.change_service,
        approval_service=env.approval_service,
        request_authenticator=authenticator or _Authenticator(env),
        approver_session_authenticator=UnusedApprovalAuthenticator(),
        config=config or PrivateNetworkConfig(origin=ORIGIN),
        clock=env.clock,
        s14_apply_port=s14_apply_port,
    )


def _headers(token="Bearer requester-one"):
    return {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Host": "127.0.0.1:8443",
        "Authorization": token,
    }


def _json_value(value):
    if hasattr(value, "items"):
        return {key: _json_value(child) for key, child in value.items()}
    if type(value) in (tuple, list):
        return [_json_value(child) for child in value]
    return value


def _rpc(client, headers, method, params=None, *, request_id=1, session=None):
    request_headers = dict(headers)
    if session:
        request_headers["mcp-session-id"] = session
    body = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", headers=request_headers, json=body)


@contextmanager
def _initialized_client(app):
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 49000)) as client:
        response = _rpc(client, _headers(), "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "s16-contract-test", "version": "1"},
        })
        assert response.status_code == 200, response.text
        yield client, response.headers["mcp-session-id"]


def test_private_gateway_publishes_exact_five_manifest_schemas_and_names():
    env = build_env()
    app = _gateway(env)
    with _initialized_client(app) as (client, session):
        response = _rpc(client, _headers(), "tools/list", session=session)

        assert response.status_code == 200, response.text
        tools = response.json()["result"]["tools"]
        expected = {spec.name: _json_value(spec.input_schema) for spec in S16_TOOL_MANIFEST}
        observed = {tool["name"]: tool["inputSchema"] for tool in tools}
        assert len(tools) == 5
        assert observed == expected


@pytest.mark.parametrize("token,expected_principal,expected_person", [
    ("Bearer requester-one", "requester", "person-requester"),
    ("Bearer requester-two", "requester-two", "person-two"),
])
def test_authenticated_identity_is_request_scoped_through_mcp_dispatch(
        token, expected_principal, expected_person):
    env = build_env()
    service = _ObservedChangeService(env.change_service)
    app = _gateway(env, service=service)
    with _initialized_client(app) as (client, session):
        response = _rpc(client, _headers(token), "tools/call", {
            "name": "status", "arguments": {"change_id": str(UUID(int=0))},
        }, request_id=2, session=session)

        assert response.status_code == 200, response.text
        assert len(service.status_principals) == 1
        principal = service.status_principals[0]
        assert (principal.principal_id, principal.person_id) == (expected_principal, expected_person)
        assert principal.lane == "TEST"
        assert response.json()["result"]["isError"] is True  # unknown synthetic change ID


@pytest.mark.parametrize("token,extra_headers,expected_status", [
    ("Bearer invalid", {}, 403),
    ("Bearer requester-one", {"X-Forwarded-For": "198.51.100.8"}, 400),
    ("Bearer requester-one", {"Host": "127.0.0.1:8444"}, 400),
])
def test_gateway_refuses_invalid_identity_or_routing_before_tool_dispatch(
        token, extra_headers, expected_status):
    env = build_env()
    service = _ObservedChangeService(env.change_service)
    auth = _Authenticator(env)
    app = _gateway(env, authenticator=auth, service=service)
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 49000)) as client:
        headers = {**_headers(token), **extra_headers}

        response = _rpc(client, headers, "tools/call", {
            "name": "status", "arguments": {"change_id": str(UUID(int=0))},
        })

        assert response.status_code == expected_status
        assert service.status_principals == []


def test_private_s16_surface_is_separate_from_public_read_only_r1_tool_server():
    from business_ai_gateway.server import build_mcp
    from business_ai_gateway.settings import Settings

    env = build_env()
    private_app = _gateway(env)
    public_server = build_mcp(Settings(environment="test", public_mcp_url="https://public.invalid/mcp"),
                              runtime=object())
    public_names = {tool.name for tool in asyncio.run(public_server.list_tools())}
    with _initialized_client(private_app) as (private_client, private_session):
        private_list = _rpc(private_client, _headers(), "tools/list", session=private_session)
        private_names = {tool["name"] for tool in private_list.json()["result"]["tools"]}

    assert len(private_names) == 5
    assert private_names.isdisjoint(public_names)
    assert not any("s16" in name.casefold() for name in public_names)


def test_private_gateway_serves_mcp_over_ephemeral_loopback_https(tmp_path, monkeypatch):
    """Exercise composed MCP + ingress + TLS listener only on an ephemeral loopback port."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import uvicorn

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    certificate = (x509.CertificateBuilder()
                   .subject_name(subject).issuer_name(subject).public_key(key.public_key())
                   .serial_number(x509.random_serial_number())
                   .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
                   .not_valid_after(datetime.now(UTC) + timedelta(minutes=5))
                   .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
                                  critical=False)
                   .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "private-test-cert.pem", tmp_path / "private-test-key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    origin = f"https://127.0.0.1:{port}"
    config = PrivateNetworkConfig(origin=origin)
    env = _retarget_env(build_env())
    lane_events = []
    apply_port = _s14_port(_lane(events=lane_events))
    app = _gateway(env, config=config, s14_apply_port=apply_port)
    captured = []
    original_server = uvicorn.Server

    class CapturedServer(original_server):
        def __init__(self, server_config):
            super().__init__(server_config)
            captured.append(self)

    monkeypatch.setattr(uvicorn, "Server", CapturedServer)

    async def exercise():
        serving = asyncio.create_task(serve_private_s16_gateway(
            app, config=config, certificate_file=str(cert_path), private_key_file=str(key_path),
        ))
        try:
            for _ in range(100):
                if captured and captured[0].started:
                    break
                await asyncio.sleep(0.05)
            assert captured and captured[0].started, "private loopback HTTPS listener did not start"
            headers = {
                "Accept": "application/json, text/event-stream", "Content-Type": "application/json",
                "Host": f"127.0.0.1:{port}", "Authorization": "Bearer requester-one",
            }
            async with httpx.AsyncClient(verify=False, timeout=3.0) as client:
                initialized = await client.post(origin + "/mcp", headers=headers, json={
                    "jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "s16-loopback-test", "version": "1"}},
                })
                assert initialized.status_code == 200, initialized.text
                session_headers = {**headers, "mcp-session-id": initialized.headers["mcp-session-id"]}
                listed = await client.post(origin + "/mcp", headers=session_headers, json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/list",
                })
                assert listed.status_code == 200, listed.text
                actual = {item["name"] for item in listed.json()["result"]["tools"]}
                assert actual == {spec.name for spec in S16_TOOL_MANIFEST}
        finally:
            if captured:
                captured[0].should_exit = True
            await asyncio.wait_for(serving, timeout=5.0)

    asyncio.run(exercise())
    assert lane_events == ["initialized", "connected", "disconnected", "uninitialized"]


def test_private_gateway_binds_the_exact_s14_port_and_apply_runs_off_loop(monkeypatch):
    env = _retarget_env(build_env())
    lane = _lane()
    apply_port = _s14_port(lane)
    app = _gateway(env, s14_apply_port=apply_port)
    assert env.core.apply_port is apply_port
    assert app.com_lane is lane

    snapshot = propose(env)
    loop_observations = []

    def synchronous_apply(_requester, change_id, *, now=None):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_observations.append(False)
        else:
            loop_observations.append(True)
        return Result.success(
            ApplyReceipt(change_id, "APPLIED", "correlation-test", "document-test")
        )

    env.change_service.apply = synchronous_apply
    with _initialized_client(app) as (client, session):
        response = _rpc(client, _headers(), "tools/call", {
            "name": "apply", "arguments": {"change_id": str(snapshot.change_id)},
        }, request_id=3, session=session)

    assert response.status_code == 200, response.text
    assert response.json()["result"]["isError"] is False
    assert loop_observations == [False]


def test_s14_apply_port_calls_existing_executor_with_approved_test_claim(monkeypatch):
    import erp_mcp_s16.com_apply_port as s16_com
    env = _retarget_env(build_env())
    snapshot = _approve_with_reauthentication(env)
    receipt = env.store.get(snapshot.change_id)
    assert receipt.approval is not None
    claim = ClaimToken("test-claim-id", receipt.change_id, receipt.version,
                       receipt.approval.approval_digest)
    lane = _lane()
    port = _s14_port(lane)
    calls = []

    def execute(connection, values, destinations, **kwargs):
        calls.append((connection, values, destinations, kwargs, threading.get_ident()))
        return ExecutorResult("99999999-9999-4999-8999-99999999999a", "21.00", ())

    monkeypatch.setattr(s16_com, "execute_create_draft", execute)
    asyncio.run(lane.start())
    try:
        applied = port.apply(receipt, claim)
    finally:
        asyncio.run(lane.close_after_drain())

    assert applied.change_id == snapshot.change_id
    assert applied.status == "APPLIED"
    assert applied.document_ref == "99999999-9999-4999-8999-99999999999a"
    assert len(calls) == 1
    assert calls[0][2] is COM_DESTINATIONS
    assert calls[0][3]["change_id"] == str(snapshot.change_id)
    assert calls[0][3]["expected_total"] == "21"
    assert calls[0][3]["document_date"] == datetime(2026, 10, 29, 12, 0)
    assert calls[0][4] != threading.get_ident()


@pytest.mark.parametrize("invalid", ["wrong-scope", "wrong-claim", "wrong-kind"])
def test_s14_apply_port_rejects_wrong_scope_claim_or_kind_before_com(invalid, monkeypatch):
    import erp_mcp_s16.com_apply_port as s16_com
    from business_ai_gateway.phase2.change.types import ChangeKind
    env = _retarget_env(build_env())
    snapshot = _approve_with_reauthentication(env)
    receipt = env.store.get(snapshot.change_id)
    assert receipt.approval is not None
    claim = ClaimToken("test-claim-id", receipt.change_id, receipt.version,
                       receipt.approval.approval_digest)
    if invalid == "wrong-scope":
        receipt = replace(receipt, scope=replace(receipt.scope, base_fingerprint="b" * 64))
    elif invalid == "wrong-claim":
        claim = replace(claim, version=claim.version + 1)
    else:
        receipt = replace(receipt, proposal=SimpleNamespace(
            kind=ChangeKind.POST, payload=receipt.proposal.payload,
        ))

    port = _s14_port()
    calls = []
    monkeypatch.setattr(s16_com, "execute_create_draft", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="S16_COM_APPLY_SCOPE_OR_CLAIM_INVALID"):
        port.apply(receipt, claim)
    assert calls == []


def test_s14_apply_port_requires_same_lane_fingerprint_and_complete_readback():
    from erp_mcp_private_writer.com_draft_executor import DraftDestinationSet

    with pytest.raises(ValueError, match="S16_COM_APPLY_TARGET_MISMATCH"):
        _s14_port(_lane(fingerprint="b" * 64))
    incomplete = DraftDestinationSet(
        "Receipt", COM_DESTINATIONS.header_properties, "Lines", COM_DESTINATIONS.line_properties,
        (), "ChangeId", "ManifestHash", constants=(("IncludesVat", True),),
        dates=COM_DESTINATIONS.dates, numbers=COM_DESTINATIONS.numbers,
        unverified_paths=("comment",),
    )
    with pytest.raises(ValueError, match="S16_COM_APPLY_CONFIGURATION_INVALID"):
        S14ComDraftApplyPort(
            lane=_lane(), expected_base_fingerprint=TEST_FINGERPRINT,
            bindings=COM_BINDINGS, destinations=incomplete,
            includes_vat_property="IncludesVat",
            document_date=lambda: datetime(2026, 10, 29, 12, 0),
        )


@pytest.mark.parametrize("origin,networks", [
    ("https://0.0.0.0:8443", ("127.0.0.1/32",)),       # wildcard bind
    ("https://0.0.0.0:8443", ("0.0.0.0/0",)),          # permissive CIDR still cannot allow wildcard
    ("https://8.8.8.8:8443", ("0.0.0.0/0",)),          # public bind/network
    ("https://127.0.0.1:8443", ("10.0.0.0/8",)),       # host outside configured private network
    ("https://127.0.0.1:65536", ("127.0.0.1/32",)),    # invalid listener port
])
def test_listener_refuses_wildcard_public_mismatched_host_or_port_before_server_start(
        monkeypatch, tmp_path, origin, networks):
    import uvicorn

    started = []

    class UnexpectedServer:
        def __init__(self, _config):
            started.append("constructed")

        async def serve(self):
            started.append("served")

    monkeypatch.setattr(uvicorn, "Server", UnexpectedServer)
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("TEST certificate placeholder", encoding="utf-8")
    key.write_text("TEST key placeholder", encoding="utf-8")

    with pytest.raises(ValueError, match="PRIVATE_LISTENER_CONFIG_INVALID"):
        asyncio.run(serve_private_s16_gateway(
            lambda *_args: None,
            config=PrivateNetworkConfig(origin=origin, allowed_networks=networks),
            certificate_file=str(cert), private_key_file=str(key),
        ))

    assert started == []


@pytest.mark.parametrize("address,port", [("127.0.0.1", 8444), ("127.0.0.2", 8443)])
def test_route_probe_rejects_mismatched_listener_host_or_port(address, port):
    assessment = ExactPrivateListenerRouteProbe(ORIGIN).assess(address, port=port)

    assert assessment.resolved_addresses == ()
    assert assessment.unresolved is True
