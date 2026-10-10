"""Phase 2 Google Drive change-feed *contract*, not a live OAuth connector.

It does not fetch documents or grant access. Changes become UNATTESTED
evidence candidates, with the checkpoint advanced only by the durable caller.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


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
    mime_type: str | None = None
    parents: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DrivePage:
    requested_page_token: str
    changes: tuple[DriveChange, ...]
    next_page_token: str | None = None
    new_start_page_token: str | None = None

    def __post_init__(self):
        # Exact types only: a str / tuple / enum subclass (e.g. one with a lying __eq__) is refused.
        if type(self.requested_page_token) is not str or not self.requested_page_token:
            raise ValueError("PAGE_TOKEN_REQUIRED")
        for token in (self.next_page_token, self.new_start_page_token):
            if token is not None and type(token) is not str:
                raise ValueError("PAGE_CONTINUATION_XOR_NEW_START_REQUIRED")
        if bool(self.next_page_token) == bool(self.new_start_page_token):
            raise ValueError("PAGE_CONTINUATION_XOR_NEW_START_REQUIRED")
        if type(self.changes) is not tuple:
            raise ValueError("INVALID_DRIVE_CHANGE")
        try:
            bad = any(
                type(c) is not DriveChange
                or type(c.file_id) is not str or not c.file_id
                or type(c.change_id) is not str or not c.change_id
                or type(c.kind) is not DriveChangeKind
                for c in self.changes
            )
        except Exception:  # noqa: BLE001 - forged change (unset slot): fixed code only
            bad = True
        if bad:
            raise ValueError("INVALID_DRIVE_CHANGE")


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    connection_id: str
    file_id: str
    revision_id: str | None
    change_id: str
    status: str = "UNATTESTED"


@dataclass(frozen=True, slots=True)
class TombstoneCandidate:
    """Explicit loss signal: earlier evidence for this file must be re-examined.

    reason is REMOVED (deleted/trashed) or MEMBERSHIP_CHANGED (access/scope lost).
    """

    connection_id: str
    file_id: str
    revision_id: str | None
    change_id: str
    reason: str
    status: str = "UNATTESTED"


@dataclass(frozen=True, slots=True)
class PreparedDriveBatch:
    source_connection_id: str
    prior_cursor: str
    # Safe view: equals prior_cursor and is_checkpoint is False while unknown_changes > 0,
    # so neither can be used to skip unclassified changes. Use committable_cursor().
    next_cursor: str
    is_checkpoint: bool
    candidates: tuple[EvidenceCandidate, ...]
    # Changes of another drive; deliberately not turned into candidates (no leak).
    denied_changes: int
    tombstones: tuple[TombstoneCandidate, ...] = ()
    # Changes whose kind could not be determined; never folded into denied_changes.
    unknown_changes: int = 0
    # True when unknown changes exist: the caller must record a history GAP or
    # pause the job instead of silently advancing the checkpoint.
    requires_gap_or_pause: bool = False
    # Folders that were modified/moved/removed: all descendants need re-qualification.
    requalify_folder_ids: tuple[str, ...] = ()
    # A caller must persist candidates and cursor together transactionally.
    durable_commit_required: bool = True
    # The provider's real continuation/new-start token; commit it only through
    # committable_cursor() (never directly).
    proposed_cursor: str = ""

    def __post_init__(self) -> None:
        if self.unknown_changes > 0 and (
            self.next_cursor != self.prior_cursor or self.is_checkpoint
            or not self.requires_gap_or_pause
        ):
            raise ValueError("UNKNOWN_CHANGES_CURSOR_ADVANCE_FORBIDDEN")

    def committable_cursor(self, *, recorded_gap: str | None = None) -> str:
        """Cursor the durable caller may persist atomically with this batch.

        With unknown_changes > 0 it stays at prior_cursor unless the caller passes
        the id of a durably recorded history GAP acknowledging the skipped changes.
        """
        if self.unknown_changes > 0:
            # local import: drive_port imports this module
            from .drive_port import is_valid_opaque_id

            if not is_valid_opaque_id(recorded_gap):  # exact str, opaque id; blank/whitespace/subclass refused
                return self.prior_cursor
        return self.proposed_cursor or self.next_cursor


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
        token = page.requested_page_token
        # exact str on both sides: a str subclass with a lying __eq__/__ne__ never passes the CAS
        if type(token) is not str or type(stored_cursor) is not str or token != stored_cursor:
            raise ValueError("CURSOR_COMPARE_AND_SWAP_FAILED")
        candidates: list[EvidenceCandidate] = []
        tombstones: list[TombstoneCandidate] = []
        requalify: list[str] = []
        denied = 0
        unknown = 0
        seen: set[str] = set()
        requalify_seen: set[str] = set()
        for item in page.changes:
            if item.change_id in seen:
                raise ValueError("DUPLICATE_CHANGE_ID_IN_PAGE")
            seen.add(item.change_id)
            if self.drive_id is not None and item.drive_id != self.drive_id:
                if item.drive_id is None and item.kind == DriveChangeKind.UNKNOWN:
                    unknown += 1  # ambiguous origin, not provably another drive
                else:
                    denied += 1
                continue
            if item.kind == DriveChangeKind.UNKNOWN:
                # Neither evidence nor provably irrelevant: surface it, do not count as denied.
                unknown += 1
                continue
            is_folder = item.mime_type == FOLDER_MIME_TYPE
            # A tombstone often carries no file metadata: treat it as a possible folder.
            if ((is_folder or (item.kind == DriveChangeKind.REMOVED and item.mime_type is None))
                    and item.file_id not in requalify_seen):
                requalify_seen.add(item.file_id)
                requalify.append(item.file_id)
            if item.kind == DriveChangeKind.REMOVED:
                tombstones.append(TombstoneCandidate(
                    self.connection_id, item.file_id, item.revision_id, item.change_id, "REMOVED"))
                continue
            authorized = self._scope_allowed(item.file_id)
            # Unknown membership cannot be silently skipped and checkpointed;
            # the job must pause until ACL/ancestry is proven or resnapshotted.
            if authorized is None:
                raise ValueError("FOLDER_MEMBERSHIP_UNVERIFIED")
            if authorized is not True:
                tombstones.append(TombstoneCandidate(
                    self.connection_id, item.file_id, item.revision_id, item.change_id,
                    "MEMBERSHIP_CHANGED"))
                continue
            if is_folder:
                continue  # a folder is not a document; its change only triggers re-qualification
            candidates.append(
                EvidenceCandidate(self.connection_id, item.file_id, item.revision_id, item.change_id)
            )
        proposed = page.next_page_token or page.new_start_page_token or ""
        return PreparedDriveBatch(
            source_connection_id=self.connection_id,
            prior_cursor=stored_cursor,
            next_cursor=stored_cursor if unknown > 0 else proposed,
            is_checkpoint=page.next_page_token is None and unknown == 0,
            proposed_cursor=proposed,
            candidates=tuple(candidates),
            denied_changes=denied,
            tombstones=tuple(tombstones),
            unknown_changes=unknown,
            requires_gap_or_pause=unknown > 0,
            requalify_folder_ids=tuple(requalify),
        )
