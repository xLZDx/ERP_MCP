"""Adversarial matrix invokes production boundaries, never a parallel URL classifier."""
import httpx
import pytest

from business_ai_gateway.adapters.onec.client import OneCReadClient, OneCTransportError
from tests.test_onec_client import source

UNSAFE = (
    "https://evil.invalid/path", "//evil.invalid/path", "../admin", "./../admin",
    "%2e%2e/admin", "%252e%252e/admin", "%2e%2e%2fadmin",
    "%252e%252e%252fadmin", "Catalog/../../admin", "Catalog\\..\\admin",
    "Catalog%5c..%5cadmin", "Catalog?secret=example", "Catalog#fragment",
    "\x00Catalog", "\r\nCatalog", "file:///private", "/admin",
)


@pytest.mark.parametrize("relative", UNSAFE)
def test_unsafe_paths_fail_closed_at_production_boundary(relative):
    with pytest.raises(OneCTransportError):
        OneCReadClient._url(source(), relative)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_redirect_matrix_is_not_followed_or_accepted_as_data(status):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(status, headers={"Location": "http://127.0.0.1/private"},
                              text="private redirect body")

    client = OneCReadClient(timeout_seconds=1, max_response_bytes=1000,
                           transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(OneCTransportError, match=f"1C_UPSTREAM_HTTP_{status}") as failure:
            await client.get_bytes(source(), "Catalog", username="synthetic", password="synthetic")
        assert len(requests) == 1
        assert requests[0].url.host == "1c.example.com"
        assert "private" not in str(failure.value)
    finally:
        await client.close()
