import httpx
import pytest

from business_ai_gateway.phase2.drive_changes import (
    DriveChangeKind,
    DriveChangeProjector,
)
from business_ai_gateway.phase2.drive_http import (
    DriveIdentity,
    DriveTransportError,
    GoogleDriveChangesReader,
)

IDENTITY = DriveIdentity("conn-1", "user-1", "shared-1", 2)


def changes_payload(*, next_page=None, end="next-token", items=None):
    payload = {
        "changes": items if items is not None else [
            {"changeType": "file", "fileId": "f1", "time": "2026-10-08T08:00:00Z",
             "driveId": "shared-1", "file": {"id": "f1", "version": "3", "trashed": False}}
        ]
    }
    if next_page is not None:
        payload["nextPageToken"] = next_page
    elif end is not None:
        payload["newStartPageToken"] = end
    return payload


def build_client(callback, *, authorized=True, token="test-token"):
    async def acl(identity):
        return authorized

    async def secret(identity):
        return token

    http = httpx.AsyncClient(transport=httpx.MockTransport(callback))
    return http, GoogleDriveChangesReader(
        http, resolve_access_token=secret, authorize_connection=acl
    )


@pytest.mark.asyncio
async def test_real_v3_fields_no_change_id_required():
    seen = []

    def handler(req):
        seen.append(req)
        assert req.method == "GET"
        assert req.url.host == "www.googleapis.com"
        assert req.url.path == "/drive/v3/changes"
        assert req.url.params["pageToken"] == "cursor:1"
        assert req.url.params["driveId"] == "shared-1"
        assert "changeId" not in req.url.params["fields"]
        return httpx.Response(200, json=changes_payload())

    http, connector = build_client(handler)
    async with http:
        result = await connector.fetch_page(identity=IDENTITY, saved_cursor="cursor:1")
    assert len(seen) == 1
    assert result.new_start_page_token == "next-token"
    assert result.changes[0].file_id == "f1"
    assert result.changes[0].revision_id == "3"
    assert result.changes[0].kind == DriveChangeKind.UPSERT
    assert len(result.changes[0].change_id) == 64


@pytest.mark.asyncio
async def test_same_page_replay_has_same_local_dedup_id():
    http, connector = build_client(lambda req: httpx.Response(200, json=changes_payload()))
    async with http:
        a = await connector.fetch_page(identity=IDENTITY, saved_cursor="c1")
        b = await connector.fetch_page(identity=IDENTITY, saved_cursor="c1")
    assert a.changes[0].change_id == b.changes[0].change_id
    assert a.changes[0].change_id != (
        await _other_page_id("different-page")
    )


async def _other_page_id(cursor):
    http, connector = build_client(lambda req: httpx.Response(200, json=changes_payload()))
    async with http:
        return (await connector.fetch_page(identity=IDENTITY, saved_cursor=cursor)).changes[0].change_id


@pytest.mark.asyncio
async def test_scope_denied_before_token_and_network():
    calls = []

    async def acl(identity):
        calls.append("acl")
        return False

    async def secret(identity):
        calls.append("token")
        return "secret"

    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: pytest.fail("NETWORK_CALLED_WITHOUT_PERMISSION")
    ))
    connector = GoogleDriveChangesReader(http, resolve_access_token=secret, authorize_connection=acl)
    async with http:
        with pytest.raises(PermissionError, match="DRIVE_ACCESS_DENIED"):
            await connector.fetch_page(identity=IDENTITY, saved_cursor="c1")
    assert calls == ["acl"]


@pytest.mark.asyncio
async def test_removed_or_shared_drive_event_not_a_document_candidate():
    items = [
        {"changeType": "file", "fileId": "f1", "removed": True, "driveId": "shared-1"},
        {"changeType": "drive", "driveId": "shared-1"},
    ]
    http, connector = build_client(lambda req: httpx.Response(
        200, json=changes_payload(items=items)
    ))
    async with http:
        result = await connector.fetch_page(identity=IDENTITY, saved_cursor="c1")
    assert [c.kind for c in result.changes] == [
        DriveChangeKind.REMOVED, DriveChangeKind.UNKNOWN
    ]
    projected = DriveChangeProjector(
        connection_id=IDENTITY.connection_id, drive_id=IDENTITY.drive_id,
        file_scope_allowed=lambda f: True,
    ).prepare(result, stored_cursor="c1")
    assert projected.candidates == ()
    assert projected.denied_changes == 2


@pytest.mark.asyncio
async def test_file_with_unknown_membership_remains_unattested_and_unindexed():
    http, connector = build_client(lambda req: httpx.Response(200,json=changes_payload()))
    async with http:
        result = await connector.fetch_page(identity=IDENTITY,saved_cursor="c1")
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="shared-1", file_scope_allowed=lambda f: None
    ).prepare(result, stored_cursor="c1")
    assert batch.candidates == ()
    assert batch.denied_changes == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [
    (401, "AUTH_REQUIRED_OR_DENIED"), (403, "AUTH_REQUIRED_OR_DENIED"),
    (410, "CURSOR_INVALID"), (429, "RATE_LIMITED"),
    (503, "DRIVE_UPSTREAM_ERROR"), (302, "DRIVE_UPSTREAM_ERROR")
])
async def test_drive_http_failures_are_sanitized(status,code):
    http, connector = build_client(lambda req: httpx.Response(status))
    async with http:
        with pytest.raises(DriveTransportError,match=code):
            await connector.fetch_page(identity=IDENTITY,saved_cursor="c1")


@pytest.mark.asyncio
async def test_large_response_rejected():
    http, connector = build_client(
        lambda req: httpx.Response(200, json=changes_payload(items=[]), content=None)
    )
    async with http:
        await connector.fetch_page(identity=IDENTITY,saved_cursor="c1")
    http, connector = build_client(
        lambda req: httpx.Response(200, content=b" " * 2_100_000,
                                   headers={"content-type":"application/json"})
    )
    async with http:
        with pytest.raises(DriveTransportError,match="RESPONSE_TOO_LARGE"):
            await connector.fetch_page(identity=IDENTITY,saved_cursor="c1")


@pytest.mark.asyncio
async def test_next_page_is_not_checkpoint():
    http, connector = build_client(lambda req: httpx.Response(
        200, json=changes_payload(next_page="c2")
    ))
    async with http:
        p=await connector.fetch_page(identity=IDENTITY,saved_cursor="c1")
    assert p.next_page_token == "c2"
    assert p.new_start_page_token is None


@pytest.mark.asyncio
async def test_missing_page_token_is_denied():
    http, connector = build_client(lambda req: pytest.fail("NO_NETWORK"))
    async with http:
        with pytest.raises(DriveTransportError,match="INVALID_CURSOR"):
            await connector.fetch_page(identity=IDENTITY,saved_cursor="")


@pytest.mark.asyncio
async def test_missing_continuation_is_denied():
    http, connector = build_client(lambda req: httpx.Response(
        200,json=changes_payload(next_page=None,end=None)
    ))
    async with http:
        with pytest.raises(DriveTransportError,match="DRIVE_INVALID_CONTINUATION"):
            await connector.fetch_page(identity=IDENTITY,saved_cursor="c1")
