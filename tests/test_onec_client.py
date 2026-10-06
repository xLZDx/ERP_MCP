import httpx
import pytest

from business_ai_gateway.adapters.onec.client import OneCReadClient, OneCTransportError
from business_ai_gateway.models import Source


def source():
    return Source(
        id="s1",
        project="onec",
        kind="onec_odata",
        display_name="Company",
        base_url="https://1c.example.com/base/odata/standard.odata",
        username_secret_ref=None,
        password_secret_ref=None,
        read_only=True,
        enabled=True,
        tags=(),
        entity_allow_patterns=(),
        entity_deny_patterns=(),
    )


def test_write_methods_do_not_exist():
    public = {
        name for name in dir(OneCReadClient)
        if not name.startswith("_")
    }
    for verb in ("post", "put", "patch", "delete"):
        assert verb not in public


@pytest.mark.asyncio
async def test_upstream_http_error_does_not_expose_url_or_query_values():
    async def handler(request):
        return httpx.Response(500, request=request, text="private backend detail")

    client = OneCReadClient(
        timeout_seconds=1,
        max_response_bytes=1000,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OneCTransportError, match="1C_UPSTREAM_HTTP_500") as raised:
            await client.get_bytes(
                source(),
                "Catalog_Organizations",
                username=None,
                password=None,
                params={"$filter": "SECRET-ACCOUNT-7741"},
            )
        assert "SECRET-ACCOUNT-7741" not in str(raised.value)
        assert "private backend detail" not in str(raised.value)
        assert raised.value.__cause__ is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_upstream_network_error_is_mapped_without_chaining_request_url():
    async def handler(request):
        raise httpx.ConnectError("SECRET-CONNECTION-DETAIL", request=request)

    client = OneCReadClient(
        timeout_seconds=1,
        max_response_bytes=1000,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OneCTransportError, match="SOURCE_NETWORK_ERROR") as raised:
            await client.get_bytes(
                source(), "Catalog_Organizations", username=None, password=None
            )
        assert "SECRET-CONNECTION-DETAIL" not in str(raised.value)
        assert raised.value.__cause__ is None
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_native_transport_rejects_encoding_before_unbounded_decompression():
    async def upstream(request):
        assert request.headers["accept-encoding"] == "identity"
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=httpx.ByteStream(b"unread encoded data"),
        )

    client = OneCReadClient(
        timeout_seconds=5,
        max_response_bytes=10000,
        transport=httpx.MockTransport(upstream),
    )
    try:
        with pytest.raises(OneCTransportError, match="encoded response"):
            await client.get_bytes(source(), "$metadata", username=None, password=None)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_url_is_pinned_to_registered_host():
    client = OneCReadClient(
        timeout_seconds=5,
        max_response_bytes=100000,
    )
    try:
        assert (
            client._url(source(), "$metadata")
            == "https://1c.example.com/base/odata/standard.odata/$metadata"
        )
        with pytest.raises(OneCTransportError):
            client._url(source(), "https://evil.example/x")
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (httpx.ReadTimeout("PRIVATE-TIMEOUT-DETAIL"), "SOURCE_TIMEOUT"),
        (httpx.ConnectError("PRIVATE-CONNECTION-DETAIL"), "SOURCE_NETWORK_ERROR"),
    ],
)
async def test_metadata_probe_outage_is_sanitized_and_fails_closed(error, expected):
    async def handler(request):
        raise error

    client = OneCReadClient(
        timeout_seconds=0.1,
        max_response_bytes=1000,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OneCTransportError, match=expected) as raised:
            await client.head_metadata(source(), username=None, password=None)
        assert "PRIVATE-" not in str(raised.value)
        assert raised.value.__cause__ is None
    finally:
        await client.close()
