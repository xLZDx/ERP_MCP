import asyncio

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


def build_client(callback, *, authorized=True, token="test-token", audit_calls=None,
                 audit_error=None, timeout=30.0):
    async def acl(identity):
        return authorized

    async def secret(identity):
        return token

    async def audit(event, details):
        if audit_error is not None:
            raise audit_error
        if audit_calls is not None:
            audit_calls.append((event, dict(details)))

    http = httpx.AsyncClient(transport=httpx.MockTransport(callback))
    return http, GoogleDriveChangesReader(
        http, resolve_access_token=secret, authorize_connection=acl, audit=audit,
        request_timeout_seconds=timeout,
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
        result = await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="cursor:1")
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
        a = await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
        b = await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert a.changes[0].change_id == b.changes[0].change_id
    assert a.changes[0].change_id != (
        await _other_page_id("different-page")
    )


async def _other_page_id(cursor):
    http, connector = build_client(lambda req: httpx.Response(200, json=changes_payload()))
    async with http:
        return (await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor=cursor)).changes[0].change_id


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
    async def audit(event, details):
        calls.append("audit")

    connector = GoogleDriveChangesReader(
        http, resolve_access_token=secret, authorize_connection=acl, audit=audit
    )
    async with http:
        with pytest.raises(PermissionError, match="DRIVE_ACCESS_DENIED"):
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert calls == ["acl", "audit"]  # denied attempt is audited, no token/network


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
        result = await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert [c.kind for c in result.changes] == [
        DriveChangeKind.REMOVED, DriveChangeKind.UNKNOWN
    ]
    projected = DriveChangeProjector(
        connection_id=IDENTITY.connection_id, drive_id=IDENTITY.drive_id,
        file_scope_allowed=lambda f: True,
    ).prepare(result, stored_cursor="c1")
    assert projected.candidates == ()
    assert [(t.file_id, t.reason) for t in projected.tombstones] == [("f1", "REMOVED")]
    assert projected.unknown_changes == 1
    assert projected.denied_changes == 0
    assert projected.requires_gap_or_pause is True


@pytest.mark.asyncio
async def test_file_with_unknown_membership_remains_unattested_and_unindexed():
    http, connector = build_client(lambda req: httpx.Response(200,json=changes_payload()))
    async with http:
        result = await connector.fetch_page(actor="svc-actor", identity=IDENTITY,saved_cursor="c1")
    projector = DriveChangeProjector(
        connection_id="conn-1", drive_id="shared-1", file_scope_allowed=lambda f: None
    )
    with pytest.raises(ValueError, match="FOLDER_MEMBERSHIP_UNVERIFIED"):
        projector.prepare(result, stored_cursor="c1")


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
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY,saved_cursor="c1")


@pytest.mark.asyncio
async def test_small_response_is_accepted():
    http, connector = build_client(
        lambda req: httpx.Response(200, json=changes_payload(items=[]))
    )
    async with http:
        page = await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert page.changes == ()
    assert page.new_start_page_token == "next-token"


@pytest.mark.asyncio
async def test_large_response_rejected():
    http, connector = build_client(
        lambda req: httpx.Response(200, content=b" " * 2_100_000,
                                   headers={"content-type": "application/json"})
    )
    async with http:
        with pytest.raises(DriveTransportError, match="RESPONSE_TOO_LARGE") as info:
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert info.value.code == "RESPONSE_TOO_LARGE"
    assert info.value.retryable is False


@pytest.mark.asyncio
async def test_next_page_is_not_checkpoint():
    http, connector = build_client(lambda req: httpx.Response(
        200, json=changes_payload(next_page="c2")
    ))
    async with http:
        p=await connector.fetch_page(actor="svc-actor", identity=IDENTITY,saved_cursor="c1")
    assert p.next_page_token == "c2"
    assert p.new_start_page_token is None


@pytest.mark.asyncio
async def test_missing_page_token_is_denied():
    http, connector = build_client(lambda req: pytest.fail("NO_NETWORK"))
    async with http:
        with pytest.raises(DriveTransportError,match="INVALID_CURSOR"):
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY,saved_cursor="")


@pytest.mark.asyncio
async def test_missing_continuation_is_denied():
    http, connector = build_client(lambda req: httpx.Response(
        200,json=changes_payload(next_page=None,end=None)
    ))
    async with http:
        with pytest.raises(DriveTransportError,match="DRIVE_INVALID_CONTINUATION"):
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY,saved_cursor="c1")


def _error_body(reason):
    return {"error": {"code": 403, "errors": [{"reason": reason}]}}


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded"])
async def test_403_rate_limit_reason_is_retryable(reason):
    http, connector = build_client(lambda req: httpx.Response(403, json=_error_body(reason)))
    async with http:
        with pytest.raises(DriveTransportError) as info:
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert info.value.code == "RATE_LIMITED"
    assert info.value.retryable is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body", [
    (403, None),
    (403, _error_body("forbidden")),
    (403, "not json"),
    (401, _error_body("rateLimitExceeded")),
])
async def test_plain_403_and_401_stay_permanent(status, body):
    if body is None:
        response = httpx.Response(status)
    elif isinstance(body, str):
        response = httpx.Response(status, content=body.encode(),
                                  headers={"content-type": "text/plain"})
    else:
        response = httpx.Response(status, json=body)
    http, connector = build_client(lambda req: response)
    async with http:
        with pytest.raises(DriveTransportError) as info:
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert info.value.code == "AUTH_REQUIRED_OR_DENIED"
    assert info.value.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code,retryable", [
    (429, "RATE_LIMITED", True), (503, "DRIVE_UPSTREAM_ERROR", True),
    (302, "DRIVE_UPSTREAM_ERROR", False), (410, "CURSOR_INVALID", False),
])
async def test_retryable_flag_per_status(status, code, retryable):
    http, connector = build_client(lambda req: httpx.Response(status))
    async with http:
        with pytest.raises(DriveTransportError) as info:
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert (info.value.code, info.value.retryable) == (code, retryable)


def test_transport_error_default_is_not_retryable():
    assert DriveTransportError("X").retryable is False
    assert DriveTransportError("X", retryable=True).retryable is True


@pytest.mark.asyncio
async def test_slow_upstream_hits_configurable_timeout():
    async def slow(req):
        await asyncio.sleep(5)
        return httpx.Response(200, json=changes_payload())

    http, connector = build_client(slow, timeout=0.05)
    async with http:
        with pytest.raises(DriveTransportError) as info:
            await asyncio.wait_for(
                connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1"), timeout=3
            )
    assert info.value.code == "DRIVE_TIMEOUT"
    assert info.value.retryable is True


@pytest.mark.parametrize("value", [0, -1, None, "5", float("nan")])
def test_invalid_timeout_configuration_rejected(value):
    with pytest.raises(ValueError, match="TIMEOUT"):
        build_client(lambda req: httpx.Response(200), timeout=value)


SECRET = "ya29.SECRET-token-value"


def _chain(exc):
    seen = []
    while exc is not None and exc not in seen:
        seen.append(exc)
        exc = exc.__cause__ or exc.__context__
    return seen


def _raise(exc):
    def handler(req):
        raise exc
    return handler


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [
    lambda req: httpx.Response(401), lambda req: httpx.Response(403),
    lambda req: httpx.Response(429), lambda req: httpx.Response(503),
    lambda req: httpx.Response(200, content=b"{" + SECRET.encode(),
                               headers={"content-type": "application/json"}),
    _raise(httpx.ConnectError("boom " + SECRET)),
    _raise(httpx.ReadTimeout("slow " + SECRET)),
])
async def test_token_never_appears_in_exception_text_or_chain(handler):
    http, connector = build_client(handler, token=SECRET)
    async with http:
        with pytest.raises(DriveTransportError) as info:
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    chain = _chain(info.value)
    assert chain[0] is info.value
    for exc in chain:
        assert SECRET not in str(exc)
        assert SECRET not in repr(exc)
        assert SECRET not in repr(exc.args)


@pytest.mark.asyncio
async def test_malformed_token_is_rejected_without_echo():
    bad = "bad token with spaces " + SECRET
    http, connector = build_client(lambda req: pytest.fail("NO_NETWORK"), token=bad)
    async with http:
        with pytest.raises(DriveTransportError) as info:
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert info.value.code == "AUTH_REQUIRED"
    assert SECRET not in str(info.value) and SECRET not in repr(info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("acl_result", [1, "yes", object(), None, False])
async def test_acl_result_must_be_exactly_true(acl_result):
    http, connector = build_client(lambda req: pytest.fail("NO_NETWORK"), authorized=acl_result)
    async with http:
        with pytest.raises(PermissionError, match="DRIVE_ACCESS_DENIED"):
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")


@pytest.mark.asyncio
async def test_audit_is_written_before_network_call():
    order = []
    audit_calls = []

    def handler(req):
        order.append(("network", len(audit_calls)))
        return httpx.Response(200, json=changes_payload())

    http, connector = build_client(handler, audit_calls=audit_calls)
    async with http:
        await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert order == [("network", 1)]
    assert audit_calls[0][0] == "drive.changes.fetch"
    assert audit_calls[0][1]["connection_id"] == "conn-1"
    assert "test-token" not in repr(audit_calls)


@pytest.mark.asyncio
async def test_audit_failure_is_fail_closed_before_network_and_token():
    tokens = []

    async def acl(identity):
        return True

    async def secret(identity):
        tokens.append("token")
        return "tok"

    async def audit(event, details):
        raise OSError("audit sink down")

    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: pytest.fail("NETWORK_CALLED_WITHOUT_AUDIT")
    ))
    connector = GoogleDriveChangesReader(
        http, resolve_access_token=secret, authorize_connection=acl, audit=audit
    )
    async with http:
        with pytest.raises(PermissionError, match="AUDIT_WRITE_FAILED") as info:
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert info.value.__cause__ is None and info.value.__context__ is None
    assert tokens == []


def test_audit_callback_is_mandatory():
    http = httpx.AsyncClient()

    async def acl(identity):
        return True

    async def secret(identity):
        return "t"

    with pytest.raises(TypeError):
        GoogleDriveChangesReader(http, resolve_access_token=secret, authorize_connection=acl)
    with pytest.raises(TypeError, match="AUDIT"):
        GoogleDriveChangesReader(http, resolve_access_token=secret,
                                 authorize_connection=acl, audit=None)


@pytest.mark.asyncio
async def test_mime_type_and_parents_are_carried_and_requested():
    seen = []
    items = [{"changeType": "file", "fileId": "fo1", "driveId": "shared-1", "time": "t",
              "file": {"id": "fo1", "version": "1", "trashed": False,
                       "mimeType": "application/vnd.google-apps.folder",
                       "parents": ["root-1"]}}]

    def handler(req):
        seen.append(req.url.params["fields"])
        return httpx.Response(200, json=changes_payload(items=items))

    http, connector = build_client(handler)
    async with http:
        page = await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert "mimeType" in seen[0] and "parents" in seen[0]
    assert page.changes[0].mime_type == "application/vnd.google-apps.folder"
    assert page.changes[0].parents == ("root-1",)


@pytest.mark.asyncio
async def test_missing_drive_id_is_not_silently_taken_from_identity():
    items = [{"changeType": "file", "fileId": "f9", "time": "t",
              "file": {"id": "f9", "version": "1", "trashed": False}}]
    http, connector = build_client(lambda req: httpx.Response(200, json=changes_payload(items=items)))
    async with http:
        page = await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert page.changes[0].drive_id is None
    assert page.changes[0].kind == DriveChangeKind.UNKNOWN
    batch = DriveChangeProjector(
        connection_id="conn-1", drive_id="shared-1", file_scope_allowed=lambda f: True
    ).prepare(page, stored_cursor="c1")
    assert batch.candidates == () and batch.unknown_changes == 1
    assert batch.requires_gap_or_pause is True


@pytest.mark.asyncio
async def test_empty_drive_id_is_malformed():
    items = [{"changeType": "file", "fileId": "f9", "driveId": "", "time": "t",
              "file": {"id": "f9", "version": "1"}}]
    http, connector = build_client(lambda req: httpx.Response(200, json=changes_payload(items=items)))
    async with http:
        with pytest.raises(DriveTransportError, match="DRIVE_MALFORMED_RESPONSE"):
            await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")


@pytest.mark.asyncio
async def test_trashed_file_without_removed_flag_is_removed_tombstone_not_candidate():
    items = [{"changeType": "file", "fileId": "f1", "time": "2026-10-08T08:00:00Z",
              "driveId": "shared-1",
              "file": {"id": "f1", "version": "3", "trashed": True}}]
    http, connector = build_client(lambda req: httpx.Response(
        200, json=changes_payload(items=items)
    ))
    async with http:
        result = await connector.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="c1")
    assert [c.kind for c in result.changes] == [DriveChangeKind.REMOVED]
    projected = DriveChangeProjector(
        connection_id=IDENTITY.connection_id, drive_id=IDENTITY.drive_id,
        file_scope_allowed=lambda f: True,
    ).prepare(result, stored_cursor="c1")
    assert projected.candidates == ()
    assert [(t.file_id, t.reason) for t in projected.tombstones] == [("f1", "REMOVED")]


@pytest.mark.asyncio
@pytest.mark.parametrize("hang", ["acl", "audit", "token"])
async def test_hanging_trusted_callback_times_out_without_network(hang):
    calls = []

    async def slow():
        await asyncio.sleep(5)

    async def acl(identity):
        if hang == "acl":
            await slow()
        return True

    async def secret(identity):
        if hang == "token":
            await slow()
        return "test-token"

    async def audit(event, details):
        if hang == "audit":
            await slow()

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json=changes_payload())

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    reader = GoogleDriveChangesReader(
        http, resolve_access_token=secret, authorize_connection=acl, audit=audit,
        callback_timeout_seconds=0.05,
    )
    with pytest.raises(DriveTransportError) as info:
        await reader.fetch_page(actor="svc-actor", identity=IDENTITY, saved_cursor="cur")
    assert info.value.code == "DRIVE_TIMEOUT" and info.value.retryable
    assert calls == []
    await http.aclose()


@pytest.mark.asyncio
async def test_allowed_denied_and_errored_attempts_are_audited_with_actor():
    records = []

    def ok(req):
        return httpx.Response(200, json=changes_payload())

    def boom(req):
        return httpx.Response(500)

    http, allowed = build_client(ok, audit_calls=records)
    async with http:
        await allowed.fetch_page(actor="alice", identity=IDENTITY, saved_cursor="c1")
    http, denied = build_client(ok, authorized=False, audit_calls=records)
    async with http:
        with pytest.raises(PermissionError, match="DRIVE_ACCESS_DENIED"):
            await denied.fetch_page(actor="mallory", identity=IDENTITY, saved_cursor="c1")
    http, errored = build_client(boom, audit_calls=records)
    async with http:
        with pytest.raises(DriveTransportError):
            await errored.fetch_page(actor="bob", identity=IDENTITY, saved_cursor="c1")
    got = [(d["actor"], d["outcome"], d["reason"]) for _, d in records]
    assert got == [
        ("alice", "allowed", "AUTHORIZED"),
        ("mallory", "denied", "DRIVE_ACCESS_DENIED"),
        ("bob", "allowed", "AUTHORIZED"),
        ("bob", "error", "DRIVE_UPSTREAM_ERROR"),
    ]
    assert all(e == "drive.changes.fetch" for e, _ in records)
    assert "test-token" not in repr(records)


@pytest.mark.asyncio
async def test_authorization_error_and_timeout_are_audited():
    records = []

    async def audit(event, details):
        records.append(dict(details))

    async def secret(identity):
        return "tok"

    async def bad_acl(identity):
        raise RuntimeError("acl down")

    async def hang_acl(identity):
        await asyncio.sleep(30)

    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail("NETWORK")))
    async with http:
        r1 = GoogleDriveChangesReader(http, resolve_access_token=secret,
                                      authorize_connection=bad_acl, audit=audit)
        with pytest.raises(RuntimeError):
            await r1.fetch_page(actor="a", identity=IDENTITY, saved_cursor="c1")
        r2 = GoogleDriveChangesReader(http, resolve_access_token=secret,
                                      authorize_connection=hang_acl, audit=audit,
                                      callback_timeout_seconds=0.05)
        with pytest.raises(DriveTransportError, match="DRIVE_TIMEOUT"):
            await r2.fetch_page(actor="a", identity=IDENTITY, saved_cursor="c1")
    assert [(r["outcome"], r["reason"]) for r in records] == [
        ("error", "AUTHORIZATION_ERROR"), ("error", "AUTHORIZATION_TIMEOUT")]


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", ["", "  ", None, 5])
async def test_actor_is_required(actor):
    http, connector = build_client(lambda r: pytest.fail("NETWORK"))
    async with http:
        with pytest.raises(PermissionError, match="DRIVE_ACTOR_REQUIRED"):
            await connector.fetch_page(actor=actor, identity=IDENTITY, saved_cursor="c1")
