"""Phase 2: bounded read-only Google Drive v3 Changes API transport.

Drive v3 Change has no changeId. A page-scoped deterministic ID is derived
from the opaque page token, row ordinal, file ID, change time and kind; this is
NOT a provider-stable event ID or evidence of every intermediate revision.
OAuth and future-folder membership must be independently qualified.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from .drive_changes import DriveChange, DriveChangeKind, DrivePage

_API_BASE = "https://www.googleapis.com/drive/v3/changes"
_MAX_BYTES = 2_000_000
_MAX_ERROR_BODY_BYTES = 65_536
_RATE_LIMIT_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})


def _opaque_token(value: object) -> bool:
    return type(value) is str and 1 <= len(value) <= 2048 and all(32 <= ord(c) < 127 for c in value)


async def _is_rate_limit_body(response: httpx.Response) -> bool:
    """True only for a 403 whose Google error reason is a rate-limit reason."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > _MAX_ERROR_BODY_BYTES:
            return False
    try:
        value = json.loads(bytes(body))
    except (ValueError, UnicodeDecodeError):
        return False
    error = value.get("error") if isinstance(value, dict) else None
    errors = error.get("errors") if isinstance(error, dict) else None
    if not isinstance(errors, list):
        return False
    return any(isinstance(item, dict) and item.get("reason") in _RATE_LIMIT_REASONS
               for item in errors)


@dataclass(frozen=True, slots=True)
class DriveIdentity:
    connection_id: str
    user_or_drive_id: str
    drive_id: str | None
    scope_epoch: int

    def __post_init__(self) -> None:
        if (
            not self.connection_id
            or not self.user_or_drive_id
            or type(self.scope_epoch) is not int
            or self.scope_epoch < 0
            or (self.drive_id is not None and not self.drive_id)
        ):
            raise ValueError("DRIVE_IDENTITY_INVALID")


class DriveTransportError(RuntimeError):
    """Sanitized transport failure: only a code, never URLs, headers or tokens."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class GoogleDriveChangesReader:
    """Read only the hardcoded Drive API endpoint through an owned HTTP client."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        resolve_access_token: Callable[[DriveIdentity], Awaitable[str]],
        authorize_connection: Callable[[DriveIdentity], Awaitable[bool]],
        audit: Callable[[str, Mapping[str, str]], Awaitable[None]],
        request_timeout_seconds: float = 30.0,
        callback_timeout_seconds: float = 10.0,
    ):
        if not isinstance(client, httpx.AsyncClient) or not callable(resolve_access_token):
            raise TypeError("DRIVE_CLIENT_CONFIGURATION_REQUIRED")
        if not callable(authorize_connection):
            raise TypeError("DRIVE_AUTHORIZER_REQUIRED")
        if not callable(audit):
            raise TypeError("DRIVE_AUDIT_REQUIRED")
        for seconds in (request_timeout_seconds, callback_timeout_seconds):
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
                raise ValueError("DRIVE_TIMEOUT_INVALID")
        self._callback_timeout = float(callback_timeout_seconds)
        self._audit = audit
        self._timeout = float(request_timeout_seconds)
        self._client = client
        self._resolve_token = resolve_access_token
        self._authorize = authorize_connection

    async def _read_body(self, params: dict[str, str], token: str) -> bytearray:
        async with self._client.stream(
            "GET", _API_BASE, params=params,
            headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
            follow_redirects=False,
        ) as response:
            status = response.status_code
            if status == 403 and await _is_rate_limit_body(response):
                raise DriveTransportError("RATE_LIMITED", retryable=True)
            if status in (401, 403):
                raise DriveTransportError("AUTH_REQUIRED_OR_DENIED")
            if status == 410:
                raise DriveTransportError("CURSOR_INVALID")
            if status == 429:
                raise DriveTransportError("RATE_LIMITED", retryable=True)
            if status != 200:
                raise DriveTransportError("DRIVE_UPSTREAM_ERROR", retryable=status >= 500)
            if response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                raise DriveTransportError("INVALID_CONTENT_TYPE")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > _MAX_BYTES:
                    raise DriveTransportError("RESPONSE_TOO_LARGE")
            return content

    async def fetch_page(
        self, *, identity: DriveIdentity, saved_cursor: str
    ) -> DrivePage:
        if not _opaque_token(saved_cursor):
            raise DriveTransportError("INVALID_CURSOR")
        # Every trusted callback is bounded: a hung callback must not hang the job.
        timed_out = False
        granted: object = None
        try:
            async with asyncio.timeout(self._callback_timeout):
                granted = await self._authorize(identity)
        except TimeoutError:
            timed_out = True
        if timed_out:
            raise DriveTransportError("DRIVE_TIMEOUT", retryable=True)
        if granted is not True:
            raise PermissionError("DRIVE_ACCESS_DENIED")
        audit_failed = False
        try:
            async with asyncio.timeout(self._callback_timeout):
                await self._audit("drive.changes.fetch", {
                    "connection_id": identity.connection_id,
                    "scope_epoch": str(identity.scope_epoch),
                    "drive_id": identity.drive_id or "",
                })
        except TimeoutError:
            timed_out = True
        except Exception:  # noqa: BLE001 - any audit-sink failure must fail closed
            audit_failed = True
        if timed_out:
            raise DriveTransportError("DRIVE_TIMEOUT", retryable=True)
        if audit_failed:
            raise PermissionError("AUDIT_WRITE_FAILED")
        token: object = None
        try:
            async with asyncio.timeout(self._callback_timeout):
                token = await self._resolve_token(identity)
        except TimeoutError:
            timed_out = True
        if timed_out:
            raise DriveTransportError("DRIVE_TIMEOUT", retryable=True)
        if (
            type(token) is not str or not token or len(token) > 4096
            or any(ord(c) < 33 or ord(c) > 126 for c in token)
        ):
            raise DriveTransportError("AUTH_REQUIRED")
        params = {
            "pageToken": saved_cursor,
            "pageSize": "100",
            "fields": (
                "nextPageToken,newStartPageToken,"
                "changes(changeType,fileId,removed,time,file(id,headRevisionId,version,mimeType,trashed,parents),driveId)"
            ),
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if identity.drive_id is not None:
            params["driveId"] = identity.drive_id
        failure: str | None = None
        try:
            async with asyncio.timeout(self._timeout):
                content = await self._read_body(params, token)
        except (TimeoutError, httpx.TimeoutException):
            failure = "DRIVE_TIMEOUT"
        except httpx.RequestError:
            failure = "DRIVE_NETWORK_ERROR"
        if failure is not None:
            # Raised outside the except block so neither __cause__ nor __context__
            # keeps the httpx exception, whose message may echo request details.
            raise DriveTransportError(failure, retryable=True)
        try:
            value: Any = json.loads(content)
        except (ValueError, UnicodeDecodeError) as exc:
            raise DriveTransportError("DRIVE_MALFORMED_JSON") from exc
        if not isinstance(value, dict) or not isinstance(value.get("changes"), list):
            raise DriveTransportError("DRIVE_MALFORMED_RESPONSE")
        changes: list[DriveChange] = []
        for ordinal, row in enumerate(value["changes"]):
            if not isinstance(row, dict):
                raise DriveTransportError("DRIVE_MALFORMED_RESPONSE")
            file_id = row.get("fileId")
            file_metadata = row.get("file")
            change_type = row.get("changeType")
            if file_id is None and isinstance(file_metadata, dict):
                file_id = file_metadata.get("id")
            if change_type == "drive" and not file_id:
                # Drive membership change is not a candidate file/reconciliation artifact.
                file_id = "drive:" + str(row.get("driveId", "unknown"))
            if not isinstance(file_id, str) or not file_id or len(file_id) > 1024:
                raise DriveTransportError("DRIVE_MALFORMED_RESPONSE")
            change_time = row.get("time")
            if change_time is not None and (
                not isinstance(change_time, str) or len(change_time) > 80
            ):
                raise DriveTransportError("DRIVE_MALFORMED_RESPONSE")
            revision = None
            mime_type = None
            parents: tuple[str, ...] = ()
            if isinstance(file_metadata, dict):
                mime_type = file_metadata.get("mimeType")
                if mime_type is not None and (not isinstance(mime_type, str) or len(mime_type) > 255):
                    raise DriveTransportError("DRIVE_MALFORMED_RESPONSE")
                raw_parents = file_metadata.get("parents", [])
                if (not isinstance(raw_parents, list) or len(raw_parents) > 100
                        or any(not isinstance(x, str) or not x or len(x) > 1024 for x in raw_parents)):
                    raise DriveTransportError("DRIVE_MALFORMED_RESPONSE")
                parents = tuple(raw_parents)
                revision = file_metadata.get("headRevisionId")
                if revision is None and file_metadata.get("version") is not None:
                    revision = str(file_metadata["version"])
                if revision is not None and (
                    not isinstance(revision, str) or len(revision) > 512
                ):
                    raise DriveTransportError("DRIVE_MALFORMED_RESPONSE")
            removed = row.get("removed") is True or (
                isinstance(file_metadata, dict) and file_metadata.get("trashed") is True
            )
            # driveId is never defaulted from the identity: an absent value stays None.
            row_drive_id = row.get("driveId")
            if row_drive_id is not None and (
                not isinstance(row_drive_id, str) or not row_drive_id or len(row_drive_id) > 1024
            ):
                raise DriveTransportError("DRIVE_MALFORMED_RESPONSE")
            kind = (
                DriveChangeKind.UNKNOWN if change_type != "file"
                or (identity.drive_id is not None and row_drive_id is None)
                else DriveChangeKind.REMOVED if removed
                else DriveChangeKind.UPSERT if isinstance(file_metadata, dict)
                else DriveChangeKind.UNKNOWN
            )
            # This ID is deterministic on replay of the SAME provider page only.
            event_material = json.dumps(
                [identity.connection_id, identity.user_or_drive_id, identity.scope_epoch,
                 saved_cursor, ordinal, file_id, change_time, kind],
                ensure_ascii=True, separators=(",", ":"),
            ).encode()
            changes.append(DriveChange(
                change_id=hashlib.sha256(event_material).hexdigest(),
                file_id=file_id, revision_id=revision, kind=kind,
                drive_id=row_drive_id, mime_type=mime_type, parents=parents,
            ))
        next_page = value.get("nextPageToken")
        next_start = value.get("newStartPageToken")
        if next_page is not None and not _opaque_token(next_page):
            raise DriveTransportError("DRIVE_MALFORMED_RESPONSE")
        if next_start is not None and not _opaque_token(next_start):
            raise DriveTransportError("DRIVE_MALFORMED_RESPONSE")
        try:
            return DrivePage(
                requested_page_token=saved_cursor, changes=tuple(changes),
                next_page_token=next_page, new_start_page_token=next_start,
            )
        except ValueError as exc:
            raise DriveTransportError("DRIVE_INVALID_CONTINUATION") from exc
