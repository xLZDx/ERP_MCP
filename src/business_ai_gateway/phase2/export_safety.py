"""Phase 2 sprint S9 (R2-US-046, TC137): deny-by-default, tenant-bounded, formula-safe export building.

Offline, unwired, in-memory, no I/O, no clock, no randomness, no Release 1 import. ``build_export`` turns the
caller's rows into an immutable, digest-bound ``ExportResult`` of TEXT cells; nothing is written anywhere and
nothing is ever evaluated. Public names:

* ``ExportColumnPolicy`` (``PUBLIC`` / ``MASKED`` / ``HASHED`` / ``DENIED``), ``ExportPolicy``, ``ExportRequest``.
* ``neutralize_cell`` - the formula-injection guard (also used for header cells).
* ``build_export(scope, request, rows, policy, ownership, entitlement, ids, concurrency=None)``
  -> ``ExportResult | OpsRefusal``.
* ``ExportResult`` (frozen, derived ``findings``, redacted ``repr``, ``EVALUATION_ONLY``).

Fixed order: structure -> entitlement -> ownership of the export id (kind ``report_id``) -> per-tenant
concurrency slot (optional ``TenantSlotCounter``) -> only then the policy and rows are read, once.
Foreign and unknown export ids give the identical ``NOT_FOUND`` refusal and the identical port-call pattern.

Row model: each row is an exact ``dict`` whose reserved keys ``tenant_id`` and ``company_id`` (exact ``str``)
are scoping metadata: they are consumed by the filter and are never exported or classified. Only rows whose
``(tenant_id, company_id)`` equals the scope are admitted; every other row is DROPPED without being inspected
(its other columns and cell types cannot influence anything) and only the opaque ``hidden_by_scope`` flag
(``HIDDEN_BY_SCOPE``) is raised: no count, no id, no name. Columns are classified from the ADMITTED rows only.

Column rules: a column must be declared in the ``ExportPolicy``; an undeclared column is not exported and is
reported as ``COLUMN_UNCLASSIFIED`` (a count, never its name); ``DENIED`` columns are absent; ``MASKED`` cells
become the fixed token ``[MASKED]`` (length-preserving masking is not used because length leaks); ``HASHED``
cells become ``h:`` plus the first 16 hex digits of ``sha256(tenant, column, value)`` (keyless, deterministic,
domain-separated per tenant and column, fixed length); ``PUBLIC`` cells pass the credential detector (a
credential-shaped value becomes ``[DENIED]``, ``VALUE_DENIED``) and the formula guard.

Formula guard: after NFKC and skipping leading whitespace/control/format/zero-width/blank characters, a cell
whose first character is ``=``, ``+``, ``-``, ``@`` (full-width and look-alike forms included: NFKC folds the
compatibility forms, U+2212 and the Unicode dashes are listed explicitly) is prefixed with an apostrophe; a
tab or carriage return anywhere in that leading run also triggers it. It is applied to values AND headers,
counted, idempotent, and typed ``int``/``Decimal`` cells are exempt (they are numbers, not text).

Limits: ``ExportPolicy.max_rows`` (admitted rows), ``max_cell_chars`` and ``max_bytes`` (UTF-8 size of the whole
result) give ``EXPORT_LIMIT_EXCEEDED``; the caller's raw input is bounded by ``MAX_INPUT_ROWS`` and
``MAX_COLUMNS``. Limits are per call of one tenant, and the optional per-tenant slot counter bounds concurrent
exports per tenant; one tenant at its limit never affects another.

Honest limits: the credential detector is a fixed heuristic (it denies, with false positives, every long
letters-and-digits run that is not a bare 64-hex digest); HASHED values of low-entropy data can be guessed
by brute force because the hash is keyless by design; this module builds text cells only (CSV/ZIP encoding and
delivery are out of scope). Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Final
from uuid import UUID

from .comparison_snapshot import canonical_digest
from .ops_types import (
    AUTHORITY,
    OpsReason,
    OpsRefusal,
    TenantSlotCounter,
    check_scope_order,
    is_digest,
    is_exact_decimal,
    is_identity_text,
    is_valid_scope,
    ops_refusal,
)

__all__ = [
    "DENIED_TOKEN", "MASK_TOKEN", "MAX_COLUMNS", "MAX_INPUT_ROWS", "ExportColumnPolicy", "ExportPolicy",
    "ExportRequest", "ExportResult", "build_export", "looks_like_credential", "neutralize_cell",
]

MAX_INPUT_ROWS: Final = 100_000
MAX_COLUMNS: Final = 64
MAX_NAME_CHARS: Final = 128
MASK_TOKEN: Final = "[MASKED]"
DENIED_TOKEN: Final = "[DENIED]"
_HASH_HEX: Final = 16
_META: Final = frozenset({"tenant_id", "company_id"})
_MAX_ROWS_LIMIT: Final = 100_000
_MAX_CELL_LIMIT: Final = 65_536
_MAX_BYTES_LIMIT: Final = 16 * 1024 * 1024


class ExportColumnPolicy(StrEnum):
    PUBLIC = "PUBLIC"
    MASKED = "MASKED"
    HASHED = "HASHED"
    DENIED = "DENIED"


class _Bad(Exception):
    """Internal only: unusable input. Never escapes a public function."""


class _Limit(Exception):
    """Internal only: a size bound was exceeded."""


def _name_ok(value: object) -> bool:
    return (type(value) is str and 1 <= len(value) <= MAX_NAME_CHARS and "\x00" not in value
            and value not in _META)


# --------------------------------------------------------------------------------------------------
# policy and request

@dataclass(frozen=True, slots=True)
class ExportPolicy:
    """``columns``: ``((name, ExportColumnPolicy), ...)`` sorted by name, unique, at most ``MAX_COLUMNS``."""

    columns: tuple[tuple[str, ExportColumnPolicy], ...]
    max_rows: int = 10_000
    max_cell_chars: int = 4_096
    max_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        if _policy_view(self) is None:
            raise ValueError("EXPORT_POLICY_INVALID")

    def __repr__(self) -> str:
        return "ExportPolicy(<redacted>)"

    @classmethod
    def from_mapping(cls, mapping: object, **limits: object) -> ExportPolicy:
        """Build from ``{column: ExportColumnPolicy}`` (exact ``dict``); malformed input -> fixed ``ValueError``."""
        if type(mapping) is not dict:
            raise ValueError("EXPORT_POLICY_INVALID")
        try:
            items = tuple(mapping.items())
            cols = tuple(sorted(items, key=lambda kv: kv[0]))
        except Exception:  # noqa: BLE001 - hostile keys: only the fixed code escapes
            raise ValueError("EXPORT_POLICY_INVALID") from None
        return cls(cols, **limits)  # type: ignore[arg-type]

    @property
    def policy_digest(self) -> str:
        view = _policy_view(self)
        if view is None:
            raise ValueError("EXPORT_POLICY_INVALID")
        return view[4]


def _policy_view(policy: object) -> tuple[dict[str, ExportColumnPolicy], int, int, int, str] | None:
    """Validate once; return ``(columns, max_rows, max_cell_chars, max_bytes, digest)`` or ``None``."""
    if type(policy) is not ExportPolicy:
        return None
    try:
        columns, max_rows, max_cell, max_bytes = (policy.columns, policy.max_rows, policy.max_cell_chars,
                                                  policy.max_bytes)
        if (type(columns) is not tuple or len(columns) > MAX_COLUMNS or type(max_rows) is not int
                or type(max_cell) is not int or type(max_bytes) is not int
                or not 1 <= max_rows <= _MAX_ROWS_LIMIT or not 1 <= max_cell <= _MAX_CELL_LIMIT
                or not 1 <= max_bytes <= _MAX_BYTES_LIMIT):
            return None
        table: dict[str, ExportColumnPolicy] = {}
        for pair in columns:
            if type(pair) is not tuple or len(pair) != 2:
                return None
            name, kind = pair
            if not _name_ok(name) or type(kind) is not ExportColumnPolicy or name in table:
                return None
            table[name] = kind
        if list(table) != sorted(table):
            return None
        digest = canonical_digest({"v": 1, "c": [[n, k.value] for n, k in table.items()], "r": max_rows,
                                   "m": max_cell, "b": max_bytes})
        return table, max_rows, max_cell, max_bytes, digest
    except Exception:  # noqa: BLE001 - forged object.__new__ instance: simply invalid
        return None


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """What is exported: the id of the export (ownership kind ``report_id``). Nothing free-form."""

    export_id: str

    def __post_init__(self) -> None:
        if not is_identity_text(self.export_id):
            raise ValueError("EXPORT_REQUEST_INVALID")

    def __repr__(self) -> str:
        return "ExportRequest(<redacted>)"


# --------------------------------------------------------------------------------------------------
# formula guard

_TRIGGERS: Final = frozenset("=+-@−‐‑‒–—―")
_BLANK: Final = frozenset("⠀ㅤᅟᅠﾠ͏᠎")
_IGNORABLE_RANGES: Final = ((0x17B4, 0x17B5), (0x180B, 0x180F), (0xFE00, 0xFE0F), (0xE0100, 0xE01EF))
_SPACE_LIKE: Final = frozenset({"Cc", "Cf", "Zs", "Zl", "Zp"})


def _ignorable(ch: str) -> bool:
    if ch in _BLANK or ch.isspace() or unicodedata.category(ch) in _SPACE_LIKE:
        return True
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _IGNORABLE_RANGES)


def _dangerous(text: str) -> bool:
    for ch in text:
        if ch in "\t\r":
            return True
        for n in unicodedata.normalize("NFKC", ch):
            if n in "\t\r":
                return True
            if _ignorable(n):
                continue
            return n in _TRIGGERS
    return False


def neutralize_cell(value: object) -> tuple[str, bool]:
    """``(text, changed)``: a formula-capable text gets a leading apostrophe; anything else is unchanged.

    Never raises and never evaluates. Idempotent (an already neutralized cell starts with an apostrophe, which is
    not a trigger). A value that is not an exact ``str`` yields ``("", False)``.
    """
    if type(value) is not str:
        return "", False
    try:
        if _dangerous(value):
            return "'" + value, True
    except Exception:  # noqa: BLE001 - fail closed: treat an unanalysable cell as dangerous
        return "'" + value, True
    return value, False


# --------------------------------------------------------------------------------------------------
# credential detector

_SECRET_PATTERNS: Final = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"\bya29\.[A-Za-z0-9_-]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{4,}"),
    re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"\b(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|authorization|client[_-]?secret)\b"
               r"\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"://[^/\s:@]+:[^/\s@]+@"),
)
_LONG_RUN: Final = re.compile(r"[A-Za-z0-9+/_-]{32,}={0,2}")
_BARE_DIGEST: Final = re.compile(r"[0-9a-f]{64}")


def _fold(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", text) if unicodedata.category(ch) != "Cf")


def looks_like_credential(value: object) -> bool:
    """Fixed heuristic: key/token/password shapes and long mixed letter-digit runs (bare sha256 hex exempt)."""
    if type(value) is not str:
        return False
    try:
        text = _fold(value)
        if any(p.search(text) for p in _SECRET_PATTERNS):
            return True
        for match in _LONG_RUN.finditer(text):
            run = match.group(0)
            if (_BARE_DIGEST.fullmatch(run) is None and any(c.isdigit() for c in run)
                    and any(c.isalpha() for c in run)):
                return True
        return False
    except Exception:  # noqa: BLE001 - fail closed
        return True


# --------------------------------------------------------------------------------------------------
# result

def _is_text_matrix(rows: object, width: int) -> bool:
    return (type(rows) is tuple and all(type(r) is tuple and len(r) == width and all(type(c) is str for c in r)
                                        for r in rows))


def _export_digest(header: tuple[str, ...], rows: tuple[tuple[str, ...], ...], counts: tuple[int, int, int, int],
                   policy_digest: str) -> str:
    return canonical_digest({"v": 1, "h": list(header), "r": [list(r) for r in rows], "n": list(counts),
                             "p": policy_digest})


@dataclass(frozen=True, slots=True)
class ExportResult:
    """A built export. Everything derived; no caller-supplied verdict; ``repr`` shows nothing."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    neutralized_headers: int
    neutralized_cells: int
    denied_values: int
    unclassified_columns: int
    hidden_by_scope: bool
    policy_digest: str
    export_digest: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        ok = (type(self.header) is tuple and all(type(h) is str for h in self.header)
              and _is_text_matrix(self.rows, len(self.header))
              and all(type(n) is int and n >= 0 for n in (self.neutralized_headers, self.neutralized_cells,
                                                           self.denied_values, self.unclassified_columns))
              and type(self.hidden_by_scope) is bool and is_digest(self.policy_digest)
              and is_digest(self.export_digest) and type(self.authority) is str and self.authority == AUTHORITY)
        if ok:
            counts = (self.neutralized_headers, self.neutralized_cells, self.denied_values,
                      self.unclassified_columns)
            ok = self.export_digest == _export_digest(self.header, self.rows, counts, self.policy_digest)
        if not ok:
            raise ValueError("EXPORT_RESULT_INVALID")

    @property
    def findings(self) -> tuple[OpsReason, ...]:
        out: list[OpsReason] = []
        if self.unclassified_columns:
            out.append(OpsReason.COLUMN_UNCLASSIFIED)
        if self.neutralized_headers or self.neutralized_cells:
            out.append(OpsReason.CELL_NEUTRALIZED)
        if self.denied_values:
            out.append(OpsReason.VALUE_DENIED)
        if self.hidden_by_scope:
            out.append(OpsReason.HIDDEN_BY_SCOPE)
        return tuple(out)

    def __repr__(self) -> str:
        return "ExportResult(<redacted>)"


# --------------------------------------------------------------------------------------------------
# building

def _cell_text(value: object) -> tuple[str, bool]:
    """``(text, is_typed_number)`` for an exact cell value; anything else is unusable."""
    if value is None:
        return "", False
    if type(value) is str:
        if "\x00" in value:
            raise _Bad
        return value, False
    if type(value) is bool:
        return ("true" if value else "false"), False
    if type(value) is int:
        return str(value), True
    if type(value) is Decimal:
        if not is_exact_decimal(value):
            raise _Bad
        return format(value, "f"), True
    if type(value) is UUID:
        return str(value), False
    if type(value) is datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise _Bad
        return value.astimezone(UTC).isoformat(), False
    raise _Bad


def _u8(text: str) -> int:
    return len(text.encode("utf-8", "surrogatepass"))


def _hash_cell(tenant: str, column: str, text: str) -> str:
    raw = f"{tenant}\x1f{column}\x1f{text}".encode("utf-8", "surrogatepass")
    return "h:" + hashlib.sha256(raw).hexdigest()[:_HASH_HEX]


def _admit(rows: tuple[object, ...], tenant: str, company: str) -> tuple[list[dict[str, object]], bool]:
    """Own rows as validated dict snapshots; foreign rows are dropped uninspected. Raises ``_Bad``."""
    own: list[dict[str, object]] = []
    hidden = False
    for row in rows:
        if type(row) is not dict:
            raise _Bad
        items = tuple(row.items())  # one read of the caller's row
        row_tenant = row_company = None
        for key, value in items:
            if type(key) is str:
                if key == "tenant_id":
                    row_tenant = value
                elif key == "company_id":
                    row_company = value
        if type(row_tenant) is not str or type(row_company) is not str:
            raise _Bad
        if row_tenant != tenant or row_company != company:
            hidden = True
            continue
        if len(items) > MAX_COLUMNS + len(_META):
            raise _Bad
        cells: dict[str, object] = {}
        for key, value in items:
            if type(key) is not str or key == "" or len(key) > MAX_NAME_CHARS or "\x00" in key:
                raise _Bad
            if key not in _META:
                cells[key] = value
        own.append(cells)
    return own, hidden


def build_export(scope: object, request: object, rows: object, policy: object, ownership: object,
                 entitlement: object, ids: object, concurrency: object = None) -> ExportResult | OpsRefusal:
    """Build a tenant-bounded, deny-by-default, formula-safe export; never raises, never echoes input."""
    acquired = False
    tenant = ""
    try:
        if not is_valid_scope(scope) or type(request) is not ExportRequest:
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        if concurrency is not None and type(concurrency) is not TenantSlotCounter:
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        try:
            export_id = request.export_id
        except AttributeError:  # forged object.__new__ instance
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        tenant, company = scope.tenant_id, scope.company_id  # type: ignore[attr-defined]

        def quota() -> bool:
            nonlocal acquired
            if concurrency is None:
                return True
            acquired = concurrency.try_acquire(tenant, "export")  # type: ignore[attr-defined]
            return acquired

        refusal = check_scope_order(scope, (("report_id", export_id),), ownership, entitlement, ids, quota)
        if refusal is not None:
            return refusal
        view = _policy_view(policy)
        if view is None or type(rows) not in (list, tuple):
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        if len(rows) > MAX_INPUT_ROWS:  # type: ignore[arg-type]
            return ops_refusal(OpsReason.EXPORT_LIMIT_EXCEEDED, ids)
        return _build(tenant, company, tuple(rows), view)  # type: ignore[arg-type]
    except _Limit:
        return ops_refusal(OpsReason.EXPORT_LIMIT_EXCEEDED, ids)
    except _Bad:
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    except Exception:  # noqa: BLE001 - never raises, never echoes
        return ops_refusal(OpsReason.INTERNAL_REFUSED, ids)
    finally:
        if acquired:
            concurrency.release(tenant, "export")  # type: ignore[attr-defined]


def _build(tenant: str, company: str, rows: tuple[object, ...],
           view: tuple[dict[str, ExportColumnPolicy], int, int, int, str]) -> ExportResult:
    table, max_rows, max_cell, max_bytes, policy_digest = view
    own, hidden = _admit(rows, tenant, company)
    if len(own) > max_rows:
        raise _Limit
    names: set[str] = set()
    for cells in own:
        names.update(cells)
    unclassified = sum(1 for n in names if n not in table)
    exported = sorted(n for n in names if n in table and table[n] is not ExportColumnPolicy.DENIED)
    neutralized_headers = 0
    header: list[str] = []
    for name in exported:
        text, changed = neutralize_cell(name)
        neutralized_headers += changed
        header.append(text)
    used = sum(_u8(h) for h in header)
    if used > max_bytes:
        raise _Limit
    neutralized_cells = denied = 0
    out_rows: list[tuple[str, ...]] = []
    for cells in own:
        out: list[str] = []
        for name in exported:
            text, is_number = _cell_text(cells.get(name))
            if len(text) > max_cell:
                raise _Limit
            kind = table[name]
            if kind is ExportColumnPolicy.MASKED:
                text = MASK_TOKEN
            elif kind is ExportColumnPolicy.HASHED:
                text = _hash_cell(tenant, name, text)
            elif not is_number and looks_like_credential(text):
                text, denied = DENIED_TOKEN, denied + 1
            elif not is_number:
                text, changed = neutralize_cell(text)
                neutralized_cells += changed
            used += _u8(text)
            if used > max_bytes:
                raise _Limit
            out.append(text)
        out_rows.append(tuple(out))
    counts = (neutralized_headers, neutralized_cells, denied, unclassified)
    header_t, rows_t = tuple(header), tuple(out_rows)
    return ExportResult(header_t, rows_t, neutralized_headers, neutralized_cells, denied, unclassified, hidden,
                        policy_digest, _export_digest(header_t, rows_t, counts, policy_digest))
