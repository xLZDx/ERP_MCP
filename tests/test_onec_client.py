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
