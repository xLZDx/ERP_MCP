"""Phase 2 Google Drive change-feed *contract*, not a live OAuth connector.

It does not fetch documents or grant access. Changes become UNATTESTED
evidence candidates, with the checkpoint advanced only by the durable caller.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum


class DriveChangeKind(StrEnum):
    UPSERT = "UPSERT"
    REMOVED = "REMOVED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DriveChange:
    change_id: str
    file_id: str
    revision_id: str | None
    kind: DriveChangeKind
    drive_id: str | None = None


@dataclass(frozen=True, slots=True)
class DrivePage:
    requested_page_token: str
    changes: tuple[DriveChange, ...]
    next_page_token: str | None = None
    new_start_page_token: str | None = None

    def __post_init__(self):
        if not self.requested_page_token:
            raise ValueError("PAGE_TOKEN_REQUIRED")
        if bool(self.next_page_token) == bool(self.new_start_page_token):
            raise ValueError("PAGE_CONTINUATION_XOR_NEW_START_REQUIRED")
        if any(not c.file_id or not c.change_id or not isinstance(c.kind, DriveChangeKind)
               for c in self.changes):
            raise ValueError("INVALID_DRIVE_CHANGE")


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    connection_id: str
    file_id: str
    revision_id: str | None
    change_id: str
    status: str = "UNATTESTED"


@dataclass(frozen=True, slots=True)
class PreparedDriveBatch:
    source_connection_id: str
    prior_cursor: str
    next_cursor: str
    is_checkpoint: bool
    candidates: tuple[EvidenceCandidate, ...]
    denied_changes: int
    # A caller must persist candidates and cursor together transactionally.
    durable_commit_required: bool = True


class DriveChangeProjector:
    """Prepare one page for atomic persistence, no network or DB writes."""

    def __init__(
        self,
        *,
        connection_id: str,
        drive_id: str | None,
        file_scope_allowed: Callable[[str], bool | None],
    ):
        if not connection_id or not callable(file_scope_allowed):
            raise ValueError("DRIVE_SCOPE_REQUIRED")
        self.connection_id, self.drive_id = connection_id, drive_id
        self._scope_allowed = file_scope_allowed

    def prepare(self, page: DrivePage, *, stored_cursor: str) -> PreparedDriveBatch:
        if page.requested_page_token != stored_cursor:
            raise ValueError("CURSOR_COMPARE_AND_SWAP_FAILED")
        candidates: list[EvidenceCandidate] = []
        denied = 0
        seen: set[str] = set()
        for item in page.changes:
            if item.change_id in seen:
                raise ValueError("DUPLICATE_CHANGE_ID_IN_PAGE")
            seen.add(item.change_id)
            if self.drive_id is not None and item.drive_id != self.drive_id:
                denied += 1
                continue
            authorized = self._scope_allowed(item.file_id)
            # None means membership unknown; cannot infer it from the folder name.
            if authorized is not True:
                denied += 1
                continue
            # Removed/revoked access is not a new valid native report.
            if item.kind != DriveChangeKind.UPSERT:
                denied += 1
                continue
            candidates.append(
                EvidenceCandidate(self.connection_id, item.file_id, item.revision_id, item.change_id)
            )
        return PreparedDriveBatch(
            source_connection_id=self.connection_id,
            prior_cursor=stored_cursor,
            next_cursor=page.next_page_token or page.new_start_page_token or "",
            is_checkpoint=page.next_page_token is None,
            candidates=tuple(candidates),
            denied_changes=denied,
        )
