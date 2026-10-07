import socket
from unittest.mock import AsyncMock

import httpcore
import httpx
import pytest

from business_ai_gateway.network_policy import PinnedEgressBackend, pinned_egress_transport


@pytest.mark.asyncio
async def test_backend_dials_only_verified_numeric_ip(monkeypatch):
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.8", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs: answers)
    backend = AsyncMock()
    guarded = PinnedEgressBackend(("192.0.2.0/24",), backend)
    stream = await guarded.connect_tcp("registered.test", 443, timeout=1)
    assert stream is backend.connect_tcp.return_value
    assert backend.connect_tcp.await_args.args == ("192.0.2.8", 443)


@pytest.mark.asyncio
async def test_rebinding_at_connect_is_denied_without_socket_request(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    backend = AsyncMock()
    guarded = PinnedEgressBackend(("192.0.2.0/24",), backend)
    with pytest.raises(httpcore.ConnectError, match="EGRESS_DESTINATION_DENIED"):
        await guarded.connect_tcp("registered.test", 443, timeout=1)
    backend.connect_tcp.assert_not_awaited()


def test_guarded_transport_keeps_verified_tls_and_disables_proxy_environment():
    transport = pinned_egress_transport(("192.0.2.0/24",))
    assert isinstance(transport._pool._network_backend, PinnedEgressBackend)
    assert transport._pool._ssl_context.check_hostname is True
    assert transport._pool._ssl_context.verify_mode.name == "CERT_REQUIRED"


@pytest.mark.asyncio
async def test_httpcore_preserves_registered_hostname_for_tls_after_ip_pinning(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_args, **_kwargs:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.8", 443))])

    class Stream(httpcore.AsyncNetworkStream):
        def __init__(self):
            self.server_hostname = None
            self.request = b""

        async def read(self, max_bytes, timeout=None):
            return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"

        async def write(self, buffer, timeout=None):
            self.request += buffer

        async def aclose(self):
            pass

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            self.server_hostname = server_hostname
            assert ssl_context.check_hostname
            return self

        def get_extra_info(self, info):
            return None

    stream = Stream()
    backend = AsyncMock()
    backend.connect_tcp.return_value = stream
    transport = pinned_egress_transport(("192.0.2.0/24",))
    transport._pool._network_backend = PinnedEgressBackend(("192.0.2.0/24",), backend)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
        result = await client.get("https://registered.test/health")
    assert result.text == "ok"
    assert stream.server_hostname == "registered.test"
    assert b"Host: registered.test" in stream.request
    assert backend.connect_tcp.await_args.args == ("192.0.2.8", 443)
