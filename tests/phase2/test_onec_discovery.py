import pytest

from business_ai_gateway.phase2.onec_discovery import OneCMetadataDiscovery

XML = (b'<e:Edmx xmlns:e="urn:edmx" xmlns:m="urn:edm"><e:DataServices>'
       b'<m:Schema Namespace="Demo"><m:EntityType Name="Org"/>'
       b'<m:EntityContainer Name="Default"><m:EntitySet Name="Catalog_Orgs" '
       b'EntityType="Demo.Org"/></m:EntityContainer></m:Schema>'
       b'</e:DataServices></e:Edmx>')


@pytest.mark.asyncio
async def test_allowlisted_source_only_and_observed_only():
    calls = []

    async def allowed(subject, source):
        calls.append(("auth", subject, source))
        return subject == "auditor" and source == "onec-reference"

    async def fetch(source):
        calls.append(("read", source))
        return XML

    client = OneCMetadataDiscovery(allow_source_metadata=allowed, fetch_registered_metadata=fetch)
    result = await client.observe(authenticated_subject="auditor", source_id="onec-reference")
    assert result.trust == "OBSERVED_ONLY"
    assert result.fingerprint.structural_sha256
    assert calls == [("auth", "auditor", "onec-reference"), ("read", "onec-reference")]


@pytest.mark.asyncio
async def test_company_reader_without_source_grant_never_dispatches():
    calls = []

    async def denied(subject, source):
        return False

    async def fetch(source):
        calls.append(source)
        return XML

    client = OneCMetadataDiscovery(allow_source_metadata=denied, fetch_registered_metadata=fetch)
    with pytest.raises(PermissionError, match="SOURCE_METADATA_ACCESS_DENIED"):
        await client.observe(authenticated_subject="company_user", source_id="onec-reference")
    assert calls == []


@pytest.mark.asyncio
async def test_arbitrary_url_denied_before_authorization():
    calls = []

    async def allowed(subject, source):
        calls.append("auth")
        return True

    async def fetch(source):
        calls.append("read")
        return XML

    client = OneCMetadataDiscovery(allow_source_metadata=allowed, fetch_registered_metadata=fetch)
    with pytest.raises(PermissionError, match="INVALID_SCOPE"):
        await client.observe(authenticated_subject="auditor", source_id="http://evil.test/")
    assert calls == []


@pytest.mark.asyncio
async def test_invalid_metadata_not_observed_or_accepted():
    async def allowed(subject, source):
        return True

    async def fetch(source):
        return b"<html>gateway error</html>"

    client = OneCMetadataDiscovery(allow_source_metadata=allowed, fetch_registered_metadata=fetch)
    with pytest.raises(ValueError, match="NOT_EDMX"):
        await client.observe(authenticated_subject="auditor", source_id="onec-reference")


@pytest.mark.asyncio
async def test_oversized_metadata_fails_closed():
    async def allowed(subject, source):
        return True

    async def fetch(source):
        return XML

    client = OneCMetadataDiscovery(
        allow_source_metadata=allowed, fetch_registered_metadata=fetch, max_metadata_bytes=15
    )
    with pytest.raises(ValueError, match="EDMX_SIZE_INVALID"):
        await client.observe(authenticated_subject="auditor", source_id="onec-reference")
