"""Phase 2 (S7/E1) read-only Google Drive *port*: contract and value types, no transport.

The port is the only way S7 modules read Drive. It has four read methods and, by construction, no
write / permission / keepForever method (AST-checked in tests/phase2/test_drive_port_fake.py). The
port never decides completeness; the calling module does.

Conventions
- Every method is ``async`` (like ``ports.py`` and ``drive_http.py``) and takes the caller identity and
  the scope epoch first, so a revoked epoch fails closed (``SCOPE_EPOCH_STALE``).
- A failed call raises only ``DrivePortError`` carrying a fixed ``DriveErrorCode``; never provider text.
- Value types are frozen, slotted and validated with exact types (``type(x) is ...``): a ``str`` /
  ``int`` / ``tuple`` / ``datetime`` subclass is refused. A failed validation raises ``ValueError`` whose
  message is a fixed code and never contains the offending value.
- Drive file ids, page tokens, revision ids, drive ids, names and mime types are opaque: preserved
  byte-exact (no trim, case-fold or normalisation); text with leading/trailing/inner whitespace or any
  control/format character in an *id or token* is refused, not repaired. Only the GUID-shaped tenant
  and connection id of ``DrivePortIdentity`` are canonicalised (lower-case dashed), nothing else.
- Timestamps must be timezone-aware ``datetime`` and are flattened to UTC; naive is refused.
- Pure stdlib, in-memory, no Release 1 / PDCC / httpx / requests / socket import.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from ._identity import canonical_guid
from .drive_changes import DriveChange, DriveChangeKind, DrivePage

__all__ = [
    "MAX_CORPUS_ROOTS",
    "MAX_ID_CHARS",
    "MAX_LIST_ITEMS",
    "MAX_NAME_CHARS",
    "ChangesPage",
    "DriveErrorCode",
    "DrivePort",
    "DrivePortError",
    "DrivePortIdentity",
    "FileMeta",
    "RevisionMeta",
    "StartToken",
    "canonical_identity",
    "is_sound_file_meta",
    "is_sound_identity",
    "is_valid_opaque_id",
    "is_valid_scope_epoch",
]

MAX_ID_CHARS = 1024
MAX_NAME_CHARS = 1024
MAX_LIST_ITEMS = 10_000
# one root-count limit for every corpus type (drive_scope / drive_membership / drive_cursor): 1..1000
MAX_CORPUS_ROOTS = 1_000
_MAX_EPOCH = 2**63 - 1
_NAMESPACE_PREFIXES = ("account:", "drive:")


class DriveErrorCode(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    INVALID_GRANT = "INVALID_GRANT"
    FORBIDDEN_HISTORY = "FORBIDDEN_HISTORY"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT = "TRANSIENT"
    SCOPE_EPOCH_STALE = "SCOPE_EPOCH_STALE"


_ERROR_CODE_VALUES = frozenset(member.value for member in DriveErrorCode)


class DrivePortError(Exception):
    """Rejected port call. Carries only ``code``; ``str()`` is the code, never provider text.

    A ``code`` that is exactly a ``DriveErrorCode`` is kept; an exact plain ``str`` equal to a member
    value (e.g. ``"NOT_FOUND"``) is converted to that member; anything else (unknown text, subclass,
    non-str) is replaced by ``TRANSIENT`` so the constructor itself can never raise or leak a caller value.
    """

    def __init__(self, code: DriveErrorCode) -> None:
        if type(code) is DriveErrorCode:
            safe = code
        elif type(code) is str and code in _ERROR_CODE_VALUES:
            safe = DriveErrorCode(code)
        else:
            safe = DriveErrorCode.TRANSIENT
        super().__init__(safe.value)
        self.code: DriveErrorCode = safe

    def __reduce__(self):
        return (DrivePortError, (self.code,))


# --- validation helpers -------------------------------------------------------------------------

_BAD_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp", "Zs"})


def _clean_chars(text: str) -> bool:
    return all(unicodedata.category(ch) not in _BAD_CATEGORIES for ch in text)


def is_valid_opaque_id(value: object) -> bool:
    """True for an exact ``str`` of 1..MAX_ID_CHARS characters with no whitespace/control/format chars.

    Pure predicate: never raises and never changes the value.
    """
    return (
        type(value) is str
        and 0 < len(value) <= MAX_ID_CHARS
        and _clean_chars(value)
    )


def is_valid_scope_epoch(value: object) -> bool:
    """True for an exact (non-bool) ``int`` in 0..2**63-1."""
    return type(value) is int and 0 <= value <= _MAX_EPOCH


def is_sound_identity(value: object) -> bool:
    """True for a real, fully initialised ``DrivePortIdentity`` (an ``object.__new__`` shell is not):
    exact types and the same id / namespace shape the constructor enforces."""
    try:
        if not (
            type(value) is DrivePortIdentity
            and type(value.namespace) is str  # type: ignore[attr-defined]
            and type(value.tenant) is str  # type: ignore[attr-defined]
            and type(value.connection_id) is str  # type: ignore[attr-defined]
        ):
            return False
        ns = value.namespace  # type: ignore[attr-defined]
        return (
            is_valid_opaque_id(ns)
            and any(ns.startswith(p) and len(ns) > len(p) for p in _NAMESPACE_PREFIXES)
            and is_valid_opaque_id(value.tenant)  # type: ignore[attr-defined]
            and is_valid_opaque_id(value.connection_id)  # type: ignore[attr-defined]
        )
    except Exception:  # noqa: BLE001 - unset slot / hostile object: not sound
        return False


def canonical_identity(value: object) -> DrivePortIdentity | None:
    """A freshly built ``DrivePortIdentity`` made of plain-str copies of a sound identity's fields, or
    None when ``value`` is not sound. Pure: never raises, never returns the caller's object."""
    try:
        if not is_sound_identity(value):
            return None
        return DrivePortIdentity(
            str.__str__(value.namespace),  # type: ignore[attr-defined]
            str.__str__(value.tenant),  # type: ignore[attr-defined]
            str.__str__(value.connection_id),  # type: ignore[attr-defined]
        )
    except Exception:  # noqa: BLE001
        return None


def is_sound_file_meta(value: object) -> bool:
    """True for a real, fully initialised ``FileMeta`` with exact-typed fields (a forged shell is not)."""
    try:
        return (
            type(value) is FileMeta
            and is_valid_opaque_id(value.file_id)  # type: ignore[attr-defined]
            and type(value.parents) is tuple  # type: ignore[attr-defined]
            and all(is_valid_opaque_id(p) for p in value.parents)  # type: ignore[attr-defined]
            and type(value.trashed) is bool  # type: ignore[attr-defined]
            and (value.drive_id is None or is_valid_opaque_id(value.drive_id))  # type: ignore[attr-defined]
            and (value.shortcut_target is None or is_valid_opaque_id(value.shortcut_target))  # type: ignore[attr-defined]
        )
    except Exception:  # noqa: BLE001 - unset slot / hostile object: not sound
        return False


def _opaque(value: object, code: str) -> str:
    if not is_valid_opaque_id(value):
        raise ValueError(code)
    return value  # type: ignore[return-value]


def _opt_opaque(value: object, code: str) -> str | None:
    return None if value is None else _opaque(value, code)


def _text(value: object, code: str) -> str:
    """Display text (name / mime type): exact str, preserved byte-exact, spaces allowed, no control chars."""
    if (
        type(value) is not str
        or not 0 < len(value) <= MAX_NAME_CHARS
        or not all(unicodedata.category(ch) not in _BAD_CATEGORIES or ch == " " for ch in value)
    ):
        raise ValueError(code)
    return value


# --- value types --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DrivePortIdentity:
    """Who a call is made for: ``namespace`` is ``account:<id>`` or ``drive:<id>``.

    ``tenant`` and ``connection_id`` are opaque ids except that a GUID-shaped value is canonicalised
    to lower-case dashed form (documented exception). The ``<id>`` part of the namespace is opaque.
    Independent of ``drive_http.DriveIdentity`` (no httpx import).
    """

    namespace: str
    tenant: str
    connection_id: str

    def __post_init__(self) -> None:
        ns = self.namespace
        if (
            type(ns) is not str
            or not is_valid_opaque_id(ns)
            or not any(ns.startswith(p) and len(ns) > len(p) for p in _NAMESPACE_PREFIXES)
        ):
            raise ValueError("DRIVE_NAMESPACE_INVALID")
        for field_name in ("tenant", "connection_id"):
            raw = getattr(self, field_name)
            if not is_valid_opaque_id(raw):
                raise ValueError("DRIVE_IDENTITY_INVALID")
            guid = canonical_guid(raw)
            if guid is not None and guid != raw:
                object.__setattr__(self, field_name, guid)

    @property
    def kind(self) -> str:
        return self.namespace.split(":", 1)[0]

    @property
    def namespace_id(self) -> str:
        return self.namespace.split(":", 1)[1]


@dataclass(frozen=True, slots=True)
class StartToken:
    token: str

    def __post_init__(self) -> None:
        _opaque(self.token, "DRIVE_PAGE_TOKEN_INVALID")


@dataclass(frozen=True, slots=True)
class ChangesPage:
    """One ``changes.list`` page: exactly one of the two tokens is present (as in ``DrivePage``)."""

    changes: tuple[DriveChange, ...]
    next_page_token: str | None = None
    new_start_page_token: str | None = None

    def __post_init__(self) -> None:
        try:
            if type(self.changes) is not tuple or len(self.changes) > MAX_LIST_ITEMS:
                raise ValueError("DRIVE_CHANGES_INVALID")
            for change in self.changes:
                if (
                    type(change) is not DriveChange
                    or type(change.kind) is not DriveChangeKind
                    or not is_valid_opaque_id(change.change_id)
                    or not is_valid_opaque_id(change.file_id)
                    or (change.drive_id is not None and type(change.drive_id) is not str)
                ):
                    raise ValueError("DRIVE_CHANGES_INVALID")
        except ValueError:
            raise
        except Exception:  # noqa: BLE001 - forged change (unset slot): fixed code only
            raise ValueError("DRIVE_CHANGES_INVALID") from None
        _opt_opaque(self.next_page_token, "DRIVE_PAGE_TOKEN_INVALID")
        _opt_opaque(self.new_start_page_token, "DRIVE_PAGE_TOKEN_INVALID")
        if (self.next_page_token is None) == (self.new_start_page_token is None):
            raise ValueError("PAGE_CONTINUATION_XOR_NEW_START_REQUIRED")

    def to_drive_page(self, requested_page_token: str) -> DrivePage:
        """Adapter for the existing ``DriveChangeProjector`` (reused, not copied)."""
        token = _opaque(requested_page_token, "DRIVE_PAGE_TOKEN_INVALID")
        try:
            return DrivePage(
                requested_page_token=token,
                changes=self.changes,
                next_page_token=self.next_page_token,
                new_start_page_token=self.new_start_page_token,
            )
        except ValueError:
            raise
        except Exception:  # noqa: BLE001 - forged page (unset slot): fixed code only
            raise ValueError("DRIVE_CHANGES_INVALID") from None


@dataclass(frozen=True, slots=True)
class FileMeta:
    file_id: str
    name: str
    mime_type: str
    parents: tuple[str, ...]
    trashed: bool
    drive_id: str | None
    shortcut_target: str | None = None
    head_revision_id: str | None = None

    def __post_init__(self) -> None:
        _opaque(self.file_id, "DRIVE_FILE_META_INVALID")
        _text(self.name, "DRIVE_FILE_META_INVALID")
        _text(self.mime_type, "DRIVE_FILE_META_INVALID")
        if type(self.parents) is not tuple or len(self.parents) > MAX_LIST_ITEMS:
            raise ValueError("DRIVE_FILE_META_INVALID")
        for parent in self.parents:
            _opaque(parent, "DRIVE_FILE_META_INVALID")
        if type(self.trashed) is not bool:
            raise ValueError("DRIVE_FILE_META_INVALID")
        _opt_opaque(self.drive_id, "DRIVE_FILE_META_INVALID")
        _opt_opaque(self.shortcut_target, "DRIVE_FILE_META_INVALID")
        _opt_opaque(self.head_revision_id, "DRIVE_FILE_META_INVALID")


@dataclass(frozen=True, slots=True)
class RevisionMeta:
    revision_id: str
    modified_time: datetime | None = None

    def __post_init__(self) -> None:
        _opaque(self.revision_id, "DRIVE_REVISION_INVALID")
        mt = self.modified_time
        if mt is not None:
            try:
                if type(mt) is not datetime or mt.tzinfo is None or mt.utcoffset() is None:
                    raise ValueError("DRIVE_REVISION_INVALID")
                flat = mt.astimezone(UTC)  # OverflowError near datetime.min/max, hostile tzinfo
            except Exception:  # noqa: BLE001 - nothing of the hostile value may escape
                raise ValueError("DRIVE_REVISION_INVALID") from None
            object.__setattr__(self, "modified_time", flat)


class DrivePort(Protocol):
    """Read-only Drive port. No write, permission or keepForever method exists on purpose."""

    async def get_start_page_token(
        self, identity: DrivePortIdentity, scope_epoch: int
    ) -> StartToken: ...

    async def list_changes(
        self, identity: DrivePortIdentity, scope_epoch: int, page_token: str
    ) -> ChangesPage: ...

    async def get_file_meta(
        self, identity: DrivePortIdentity, scope_epoch: int, file_id: str
    ) -> FileMeta: ...

    async def list_revisions(
        self, identity: DrivePortIdentity, scope_epoch: int, file_id: str
    ) -> tuple[RevisionMeta, ...]: ...
