"""Injected read interface of the S15 verifier (read-only; no COM or gateway code here)."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

__all__ = ["ReadIncomplete", "ReceiptReader", "ReferenceLookup", "StoredDocument"]


class ReadIncomplete(Exception):
    """A read failed or returned partial data; the verifier maps it to INCONCLUSIVE."""


@dataclass(frozen=True, slots=True)
class ReferenceLookup:
    """Result of resolving a reference in its expected catalog (``deletion_mark`` None = unread)."""

    exists: bool
    deletion_mark: bool | None


@dataclass(frozen=True, slots=True)
class StoredDocument:
    """Raw read-back of a stored receipt.

    ``header`` and ``lines[i]`` map the oracle field paths to values as read: dates as XMLString
    text, enumerations as member name text (empty text when empty), references as canonical GUID
    text (None when empty), numbers as int / float / Decimal, identity text as str. A path absent
    from the mapping means the value was not read (incomplete), not that it is empty.
    """

    header: Mapping[str, object]
    lines: tuple[Mapping[str, object], ...]
    own_date_text: object
    change_id: object
    change_hash: object
    posted: object
    deletion_mark: object
    includes_vat: object
    total: object


class ReceiptReader(Protocol):
    def read_document(self, document_ref: str) -> StoredDocument:
        """Fetch the stored receipt afresh; raise ``ReadIncomplete`` on any failed read."""

    def lookup_reference(self, catalog: str, ref_text: str) -> ReferenceLookup:
        """Resolve ``ref_text`` in ``catalog``; raise ``ReadIncomplete`` on a failed read."""
