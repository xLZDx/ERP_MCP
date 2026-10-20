"""Phase 2 sprint S9 (R2-US-046, TC136): restore verification as a comparison of two manifests.

Offline, unwired, in-memory, no I/O, no wall clock (an injected ``clock`` is read once), no Release 1 import.
Nothing is restored here: ``build_manifest`` turns ``living.*``-shaped rows into an immutable, digest-bound
``RestoreManifest`` and ``verify_restore`` compares a SOURCE manifest with a RESTORED one. Public names:

* ``LIVING_TABLES`` / ``REQUIRED_TABLES`` / ``TABLE_KEYS`` - the table vocabulary and the key columns.
* ``FkEdge`` / ``LIVING_FK_CATALOGUE`` - the foreign-key edges mirrored from the real ``REFERENCES`` clauses of
  ``db/phase2/001..003``; a text-parsing test proves the catalogue equals the SQL in both directions.
* ``build_manifest(scope, source_ids, rows, ownership, entitlement, ids, catalogue=...)``.
* ``verify_restore(scope, source_ids, source, restored, ownership, entitlement, ids, attestations, clock,
  catalogue=...)`` -> ``RestoreReport | OpsRefusal``.
* ``RestoreManifest`` / ``TableManifest`` / ``RowEntry`` / ``RestoreReport`` / ``RestoreCheck`` /
  ``CheckName`` / ``is_valid_manifest``.

Fixed order of both entry points: structure -> entitlement -> ownership of every declared source -> quota ->
only then the rows/manifests are read. Foreign and unknown sources give the identical ``NOT_FOUND`` refusal.

The report always holds the eight checks in a fixed order (``COMPLETE``, ``COUNT``, ``DIGEST``, ``FK``,
``HEAD``, ``SEQUENCE``, ``ATTESTATION``, ``SCOPE``); ``verified`` and ``codes`` are DERIVED (no caller-supplied
verdict), an empty, partial or truncated manifest never verifies (``RESTORE_INCOMPLETE``) and restored
attestations are re-checked as CURRENT through the injected ``check_current`` port, never trusted from the
backup. The report names only fixed table names and codes: no row value, id, tenant or count is echoed.

Input row model (an adaptation, documented): each table maps to a list of exact ``dict`` rows keyed by SQL column
name; values are exact ``str``/``int``/``bool``/``None``/``UUID``/aware ``datetime``/finite ``Decimal`` or
bounded nested ``dict``/``list`` (jsonb). The ``attestations`` rows carry two extra columns, ``policy_version`` and
``policy_digest``, which bind the restored row to the policy it was judged under (the SQL table has none).

``verify_restore`` refuses (``INPUT_INVALID``) a catalogue that is not a superset of ``LIVING_FK_CATALOGUE`` and the
``report_digest`` binds a digest of the catalogue used. Attestation currency is judged only for the attestations the
restored accepted heads rest on (``accepted_heads.revision_id``); older attestations are immutable history. The head
check also requires ``version == max(to_version)`` of the head's events and an ``OBSERVED`` observation; a manifest
with a duplicate primary key or duplicate ``(tenant, source, revision_id)`` is invalid.

Honest limits: the manifests are built from caller rows, so a manifest is only as truthful as those rows (the
real database restore proof stays ``tests/phase2/test_g1_restore.py``); the structural columns kept per row are
not re-derived from the row digest by ``verify_restore`` (a hand-forged, self-consistent manifest is possible
but must be built through ``build_manifest`` to be trusted); outbox sequence gaps are judged against the source
manifest because ``seq`` is a global identity. Authority is ``EVALUATION_ONLY``.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Protocol
from uuid import UUID

from .comparison_snapshot import canonical_digest
from .ops_types import (
    AUTHORITY,
    OpsReason,
    OpsRefusal,
    check_scope_order,
    is_aware_datetime,
    is_digest,
    is_exact_decimal,
    is_identity_text,
    is_valid_scope,
    ops_refusal,
)

__all__ = [
    "LIVING_FK_CATALOGUE", "LIVING_TABLES", "MAX_COLUMNS", "MAX_ROWS_PER_TABLE", "MAX_TOTAL_ROWS",
    "REQUIRED_TABLES", "TABLE_KEYS", "CheckName", "CurrentAttestationPort", "FkEdge", "RestoreCheck",
    "RestoreManifest", "RestoreReport", "RowEntry", "TableManifest", "build_manifest", "is_valid_manifest",
    "verify_restore",
]

MAX_ROWS_PER_TABLE: Final = 5_000
MAX_TOTAL_ROWS: Final = 20_000
MAX_COLUMNS: Final = 64
MAX_CATALOGUE_EDGES: Final = 64
MAX_SOURCES: Final = 64
# jsonb limits are aligned with the SQL ones (outbox.content <= 262144 bytes, provenance <= 65536 bytes): a legal
# payload must never make a whole table unverifiable. Keys starting with "$" stay refused: the shared canonical
# encoder reserves them as type tags ($dec/$ts), so such a row cannot be digested unambiguously.
_MAX_TEXT: Final = 262_144
_MAX_DEPTH: Final = 32
_MAX_NODES: Final = 50_000
_MAX_INT: Final = 2**63 - 1
_IDENT: Final = re.compile(r"[a-z_][a-z0-9_]{0,62}")

LIVING_TABLES: Final = (
    "tenants", "sources", "observations", "accepted_heads", "acceptance_events", "jobs", "cursors", "outbox",
    "role_scope", "trusted_reviewers", "attestations",
)
REQUIRED_TABLES: Final = frozenset({
    "tenants", "sources", "observations", "accepted_heads", "acceptance_events", "jobs", "cursors", "outbox",
    "attestations",
})
TABLE_KEYS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType({
    "tenants": ("tenant_id",),
    "sources": ("tenant_id", "source_id"),
    "observations": ("tenant_id", "source_id", "observation_id"),
    "accepted_heads": ("tenant_id", "source_id", "model_key"),
    "acceptance_events": ("tenant_id", "source_id", "acceptance_id"),
    "jobs": ("tenant_id", "source_id", "job_id"),
    "cursors": ("tenant_id", "source_id", "connection_id"),
    "outbox": ("tenant_id", "source_id", "connection_id", "event_id"),
    # role_scope has no primary key in SQL; its unique index is (role_name, tenant, source, coalesce(company,''))
    "role_scope": ("role_name", "tenant_id", "source_id", "company_id"),
    "trusted_reviewers": ("role_name", "tenant_id", "source_id"),
    "attestations": ("tenant_id", "source_id", "attestation_id"),
})
_NULLABLE_KEYS: Final = frozenset({("role_scope", "company_id")})
_EXTRA_COLUMNS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType({
    "observations": ("digest", "kind", "revision_id"),
    "accepted_heads": ("model_key", "revision_id", "version"),
    "acceptance_events": ("accepted_revision", "model_key", "to_version"),
    "outbox": ("connection_id", "seq"),
    "attestations": ("attestation_id", "expires_at", "policy_digest", "policy_version", "revision_id",
                     "revoked_at"),
})


class _Bad(Exception):
    """Internal only: a row/manifest could not be snapshotted. Never escapes a public function."""


class _Quota(Exception):
    """Internal only: a size bound was exceeded."""


# --------------------------------------------------------------------------------------------------
# foreign-key catalogue

@dataclass(frozen=True, slots=True)
class FkEdge:
    """``child_table(child_columns) REFERENCES parent_table(parent_columns)``."""

    child_table: str
    child_columns: tuple[str, ...]
    parent_table: str
    parent_columns: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _edge_ok(self.child_table, self.child_columns, self.parent_table, self.parent_columns):
            raise ValueError("FK_EDGE_INVALID")


def _ident_ok(value: object) -> bool:
    return type(value) is str and _IDENT.fullmatch(value) is not None


def _cols_ok(value: object) -> bool:
    return (type(value) is tuple and 1 <= len(value) <= 4 and all(_ident_ok(c) for c in value)
            and len(set(value)) == len(value))


def _edge_ok(child: object, ccols: object, parent: object, pcols: object) -> bool:
    return (_ident_ok(child) and _ident_ok(parent) and _cols_ok(ccols) and _cols_ok(pcols)
            and len(ccols) == len(pcols))  # type: ignore[arg-type]


_T, _S, _O = "tenant_id", "source_id", "observation_id"
LIVING_FK_CATALOGUE: Final[tuple[FkEdge, ...]] = (
    FkEdge("sources", (_T,), "tenants", (_T,)),
    FkEdge("observations", (_T, _S), "sources", (_T, _S)),
    FkEdge("observations", (_T, _S, "supersedes"), "observations", (_T, _S, _O)),
    FkEdge("accepted_heads", (_T, _S), "sources", (_T, _S)),
    FkEdge("accepted_heads", (_T, _S, "revision_id"), "observations", (_T, _S, "revision_id")),
    FkEdge("acceptance_events", (_T, _S, "model_key"), "accepted_heads", (_T, _S, "model_key")),
    FkEdge("acceptance_events", (_T, _S, "accepted_revision"), "observations", (_T, _S, "revision_id")),
    FkEdge("jobs", (_T, _S), "sources", (_T, _S)),
    FkEdge("cursors", (_T, _S), "sources", (_T, _S)),
    FkEdge("outbox", (_T, _S, "connection_id"), "cursors", (_T, _S, "connection_id")),
    FkEdge("role_scope", (_T, _S), "sources", (_T, _S)),
    FkEdge("trusted_reviewers", (_T, _S), "sources", (_T, _S)),
    FkEdge("attestations", (_T, _S, "revision_id"), "observations", (_T, _S, "revision_id")),
)


def _catalogue_snapshot(catalogue: object) -> tuple[FkEdge, ...] | None:
    if type(catalogue) not in (tuple, list):
        return None
    try:
        if len(catalogue) > MAX_CATALOGUE_EDGES:  # type: ignore[arg-type]
            return None
        snap = tuple(catalogue)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return None
    out: list[FkEdge] = []
    for edge in snap:
        if type(edge) is not FkEdge:
            return None
        try:
            child, ccols, parent, pcols = (edge.child_table, edge.child_columns, edge.parent_table,
                                           edge.parent_columns)
        except AttributeError:  # forged object.__new__ instance
            return None
        if (not _edge_ok(child, ccols, parent, pcols) or child not in TABLE_KEYS or parent not in TABLE_KEYS):
            return None
        out.append(edge)
    return tuple(out)


def _structural_columns(table: str, catalogue: tuple[FkEdge, ...]) -> tuple[str, ...]:
    cols = set(TABLE_KEYS[table]) | set(_EXTRA_COLUMNS.get(table, ()))
    for edge in catalogue:
        if edge.child_table == table:
            cols.update(edge.child_columns)
        if edge.parent_table == table:
            cols.update(edge.parent_columns)
    return tuple(sorted(cols))


# --------------------------------------------------------------------------------------------------
# manifest types

@dataclass(frozen=True, slots=True)
class RowEntry:
    """One row: key text, the full-row digest and the structural columns (never the whole row)."""

    key: tuple[str, ...]
    digest: str
    cols: tuple[tuple[str, str | int | None], ...]

    def __repr__(self) -> str:
        return "RowEntry(<redacted>)"


@dataclass(frozen=True, slots=True)
class TableManifest:
    name: str
    columns: tuple[str, ...]
    row_count: int
    entries: tuple[RowEntry, ...]
    table_digest: str

    def __repr__(self) -> str:
        return "TableManifest(<redacted>)"


@dataclass(frozen=True, slots=True)
class RestoreManifest:
    tenant_id: str
    source_ids: tuple[str, ...]
    tables: tuple[TableManifest, ...]
    manifest_digest: str

    def __post_init__(self) -> None:
        if _view(self) is None:
            raise ValueError("RESTORE_MANIFEST_INVALID")

    def __repr__(self) -> str:
        return "RestoreManifest(<redacted>)"


class _View:
    """Validated, immutable snapshot of a manifest: only these locals are used after validation."""

    __slots__ = ("digest", "sources", "tables", "tenant")

    def __init__(self, tenant: str, sources: tuple[str, ...],
                 tables: dict[str, tuple[tuple[str, ...], tuple[RowEntry, ...], str]], digest: str) -> None:
        self.tenant, self.sources, self.tables, self.digest = tenant, sources, tables, digest


def _entry_digest_payload(entry_digest: str, cols: tuple[tuple[str, str | int | None], ...]) -> list[object]:
    return [entry_digest, [[name, value] for name, value in cols]]


def _table_digest(name: str, columns: tuple[str, ...], entries: tuple[RowEntry, ...]) -> str:
    return canonical_digest({"t": name, "c": list(columns),
                             "e": [[list(e.key), *_entry_digest_payload(e.digest, e.cols)] for e in entries]})


def _manifest_digest(tenant: str, sources: tuple[str, ...], tables: list[tuple[str, str, int]]) -> str:
    return canonical_digest({"v": 1, "tenant": tenant, "sources": list(sources),
                             "tables": [[n, d, c] for n, d, c in tables]})


def _entry_ok(entry: object, table: str, columns: tuple[str, ...]) -> bool:
    if type(entry) is not RowEntry:
        return False
    try:
        key, digest, cols = entry.key, entry.digest, entry.cols
    except AttributeError:
        return False
    if (type(key) is not tuple or len(key) != len(TABLE_KEYS[table]) or any(type(k) is not str for k in key)
            or not is_digest(digest) or type(cols) is not tuple or len(cols) != len(columns)):
        return False
    for pair, want in zip(cols, columns, strict=True):
        if type(pair) is not tuple or len(pair) != 2:
            return False
        name, value = pair
        if name != want or not (value is None or type(value) is str or type(value) is int):
            return False
    return True


def _view(value: object) -> _View | None:
    """Validate a manifest once and return an immutable snapshot, or ``None`` (forged/garbled -> invalid)."""
    if type(value) is not RestoreManifest:
        return None
    try:
        tenant, sources, tables, digest = value.tenant_id, value.source_ids, value.tables, value.manifest_digest
        if (not is_identity_text(tenant) or type(sources) is not tuple or not 1 <= len(sources) <= MAX_SOURCES
                or any(not is_identity_text(s) for s in sources) or list(sources) != sorted(set(sources))
                or type(tables) is not tuple or not is_digest(digest)):
            return None
        seen: dict[str, tuple[tuple[str, ...], tuple[RowEntry, ...], str]] = {}
        summary: list[tuple[str, str, int]] = []
        last = -1
        for table in tables:
            if type(table) is not TableManifest:
                return None
            name, columns, count, entries, tdigest = (table.name, table.columns, table.row_count, table.entries,
                                                      table.table_digest)
            if type(name) is not str or name not in TABLE_KEYS:
                return None
            order = LIVING_TABLES.index(name)
            if order <= last:
                return None
            last = order
            if (type(columns) is not tuple or list(columns) != sorted(set(columns))
                    or not all(_ident_ok(c) for c in columns) or not set(TABLE_KEYS[name]) <= set(columns)
                    or type(count) is not int or type(entries) is not tuple or count != len(entries)
                    or count > MAX_ROWS_PER_TABLE or not is_digest(tdigest)):
                return None
            if not all(_entry_ok(e, name, columns) for e in entries):
                return None
            if list(entries) != sorted(entries, key=lambda e: (e.key, e.digest)):
                return None
            if len({e.key for e in entries}) != len(entries):  # a duplicate primary key is never a real table
                return None
            if name == "observations" and {"tenant_id", "source_id", "revision_id"} <= set(columns):
                at = {c: i for i, c in enumerate(columns)}  # UNIQUE(tenant_id, source_id, revision_id)
                triples = {tuple(e.cols[at[c]][1] for c in ("tenant_id", "source_id", "revision_id")) for e in entries}
                if len(triples) != len(entries):
                    return None
            if tdigest != _table_digest(name, columns, entries):
                return None
            seen[name] = (columns, entries, tdigest)
            summary.append((name, tdigest, count))
        if digest != _manifest_digest(tenant, sources, summary):
            return None
        return _View(tenant, sources, seen, digest)
    except Exception:  # noqa: BLE001 - forged object.__new__ instance or hostile state: simply invalid
        return None


def is_valid_manifest(value: object) -> bool:
    return _view(value) is not None


# --------------------------------------------------------------------------------------------------
# row snapshotting

def _snap(value: object, depth: int, budget: list[int]) -> object:
    budget[0] -= 1
    if budget[0] < 0 or depth > _MAX_DEPTH:
        raise _Bad
    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        if len(value) > _MAX_TEXT or "\x00" in value:
            raise _Bad
        return value
    if type(value) is int:
        if not -_MAX_INT <= value <= _MAX_INT:
            raise _Bad
        return value
    if type(value) is UUID:
        return str(value)
    if type(value) is datetime:
        if not is_aware_datetime(value):
            raise _Bad
        return value
    if type(value) is not dict and type(value) is not list and type(value) is not tuple:
        if is_exact_decimal(value):
            return value
        raise _Bad
    if type(value) is dict:
        items = tuple(value.items())
        out: dict[str, object] = {}
        for key, item in items:
            if type(key) is not str or key == "" or key.startswith("$") or len(key) > 256 or "\x00" in key:
                raise _Bad
            out[key] = _snap(item, depth + 1, budget)
        return out
    return [_snap(item, depth + 1, budget) for item in tuple(value)]


def _col_value(value: object) -> str | int | None:
    if value is None or type(value) is str:
        return value  # type: ignore[return-value]
    if type(value) is int:
        return value
    if type(value) is datetime:
        return value.astimezone(UTC).isoformat()
    raise _Bad


def _snap_row(table: str, row: object, structural: tuple[str, ...]) -> RowEntry:
    if type(row) is not dict or len(row) > MAX_COLUMNS:
        raise _Bad
    snap = _snap(row, 0, [_MAX_NODES])
    if type(snap) is not dict:
        raise _Bad
    try:
        digest = canonical_digest(snap)
    except Exception:  # noqa: BLE001
        raise _Bad from None
    cols: list[tuple[str, str | int | None]] = []
    for name in structural:
        if name not in snap:
            raise _Bad
        cols.append((name, _col_value(snap[name])))
    key: list[str] = []
    for name in TABLE_KEYS[table]:
        value = snap[name]
        if value is None:
            if (table, name) not in _NULLABLE_KEYS:
                raise _Bad
            key.append("")
        elif type(value) is str or type(value) is int:
            key.append(str(value))
        else:
            raise _Bad  # a key column must be text, an integer or (nullable ones only) NULL
    return RowEntry(tuple(key), digest, tuple(cols))


def _snapshot_sources(source_ids: object) -> tuple[str, ...] | None:
    if type(source_ids) not in (tuple, list):
        return None
    try:
        if not 1 <= len(source_ids) <= MAX_SOURCES:  # type: ignore[arg-type]
            return None
        snap = tuple(source_ids)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return None
    if any(not is_identity_text(s) for s in snap) or len(set(snap)) != len(snap):
        return None
    return tuple(sorted(snap))


def build_manifest(scope: object, source_ids: object, rows: object, ownership: object, entitlement: object,
                   ids: object, catalogue: object = LIVING_FK_CATALOGUE) -> RestoreManifest | OpsRefusal:
    """Digest-bound manifest of ``rows`` for the declared ``source_ids`` of ``scope``'s tenant.

    ``rows`` is ``{table_name: [row, ...]}``. Order: structure -> entitlement -> ownership of every declared
    source (kind ``source_id``) -> row bounds -> the rows are read exactly once. Rows of another tenant/source
    are NOT dropped or refused here: they are recorded so ``verify_restore`` reports ``RESTORE_SCOPE_FOREIGN``.
    Never raises.
    """
    try:
        sources = _snapshot_sources(source_ids)
        if sources is None or not is_valid_scope(scope):
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        refusal = check_scope_order(scope, tuple(("source_id", s) for s in sources), ownership, entitlement, ids)
        if refusal is not None:
            return refusal
        edges = _catalogue_snapshot(catalogue)
        if edges is None or type(rows) is not dict:
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        tenant = scope.tenant_id  # type: ignore[attr-defined]
        return _build(tenant, sources, tuple(rows.items()), edges)
    except ValueError:  # the manifest itself is not a valid table set (duplicate key / revision_id)
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    except _Quota:
        return ops_refusal(OpsReason.QUOTA_EXCEEDED, ids)
    except _Bad:
        return ops_refusal(OpsReason.INPUT_INVALID, ids)
    except Exception:  # noqa: BLE001 - never raises, never echoes
        return ops_refusal(OpsReason.INTERNAL_REFUSED, ids)


def _build(tenant: str, sources: tuple[str, ...], items: tuple[tuple[object, object], ...],
           edges: tuple[FkEdge, ...]) -> RestoreManifest:
    by_table: dict[str, tuple[object, ...]] = {}
    total = 0
    for name, table_rows in items:
        if type(name) is not str or name not in TABLE_KEYS or name in by_table:
            raise _Bad
        if type(table_rows) not in (list, tuple):
            raise _Bad
        snap = tuple(table_rows)  # type: ignore[arg-type]
        if len(snap) > MAX_ROWS_PER_TABLE:
            raise _Quota
        total += len(snap)
        if total > MAX_TOTAL_ROWS:
            raise _Quota
        by_table[name] = snap
    tables: list[TableManifest] = []
    summary: list[tuple[str, str, int]] = []
    for name in LIVING_TABLES:
        if name not in by_table:
            continue
        structural = _structural_columns(name, edges)
        entries = tuple(sorted((_snap_row(name, r, structural) for r in by_table[name]),
                               key=lambda e: (e.key, e.digest)))
        tdigest = _table_digest(name, structural, entries)
        tables.append(TableManifest(name, structural, len(entries), entries, tdigest))
        summary.append((name, tdigest, len(entries)))
    return RestoreManifest(tenant, sources, tuple(tables), _manifest_digest(tenant, sources, summary))


# --------------------------------------------------------------------------------------------------
# report

class CheckName(StrEnum):
    COMPLETE = "COMPLETE"
    COUNT = "COUNT"
    DIGEST = "DIGEST"
    FK = "FK"
    HEAD = "HEAD"
    SEQUENCE = "SEQUENCE"
    ATTESTATION = "ATTESTATION"
    SCOPE = "SCOPE"


_CHECK_ORDER: Final = tuple(CheckName)
CHECK_CODE: Final[Mapping[CheckName, OpsReason]] = MappingProxyType({
    CheckName.COMPLETE: OpsReason.RESTORE_INCOMPLETE,
    CheckName.COUNT: OpsReason.RESTORE_COUNT_MISMATCH,
    CheckName.DIGEST: OpsReason.RESTORE_DIGEST_MISMATCH,
    CheckName.FK: OpsReason.RESTORE_FK_ORPHAN,
    CheckName.HEAD: OpsReason.RESTORE_HEAD_MISMATCH,
    CheckName.SEQUENCE: OpsReason.RESTORE_SEQUENCE_GAP,
    CheckName.ATTESTATION: OpsReason.RESTORE_ATTESTATION_STALE,
    CheckName.SCOPE: OpsReason.RESTORE_SCOPE_FOREIGN,
})


@dataclass(frozen=True, slots=True)
class RestoreCheck:
    """One check. ``code`` is derived from the check name and set only for a ran-and-failed check."""

    name: CheckName
    ran: bool
    passed: bool
    code: OpsReason | None
    tables: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ok = (type(self.name) is CheckName and type(self.ran) is bool and type(self.passed) is bool
              and type(self.tables) is tuple and all(type(t) is str and t in TABLE_KEYS for t in self.tables)
              and list(self.tables) == sorted(set(self.tables), key=LIVING_TABLES.index))
        if ok:
            if not self.ran:
                ok = not self.passed and self.code is None and not self.tables
            elif self.passed:
                ok = self.code is None and not self.tables
            else:
                ok = self.code is CHECK_CODE[self.name]
        if not ok:
            raise ValueError("RESTORE_CHECK_INVALID")


@dataclass(frozen=True, slots=True)
class RestoreReport:
    checks: tuple[RestoreCheck, ...]
    source_digest: str
    restored_digest: str
    report_digest: str
    authority: str = AUTHORITY

    def __post_init__(self) -> None:
        ok = (type(self.checks) is tuple and len(self.checks) == len(_CHECK_ORDER)
              and all(type(c) is RestoreCheck and c.name is n for c, n in zip(self.checks, _CHECK_ORDER, strict=True))
              and is_digest(self.source_digest) and is_digest(self.restored_digest)
              and is_digest(self.report_digest) and type(self.authority) is str and self.authority == AUTHORITY)
        if not ok:
            raise ValueError("RESTORE_REPORT_INVALID")

    @property
    def verified(self) -> bool:
        """Derived: every one of the eight checks ran and passed."""
        return all(c.ran and c.passed for c in self.checks)

    @property
    def codes(self) -> tuple[OpsReason, ...]:
        return tuple(c.code for c in self.checks if c.code is not None)

    def __repr__(self) -> str:
        return "RestoreReport(<redacted>)"


# --------------------------------------------------------------------------------------------------
# verification

class CurrentAttestationPort(Protocol):
    """``AttestationStore.check_current``-shaped port: returns an object with ``valid`` and ``code``."""

    def check_current(self, attestation_id: str, tenant_id: str, revision_digest: str, policy_version: str,
                      policy_digest: str) -> object: ...


def _cols(entry: RowEntry) -> dict[str, str | int | None]:
    return dict(entry.cols)


def _sorted_tables(names: set[str]) -> tuple[str, ...]:
    return tuple(sorted(names, key=LIVING_TABLES.index))


def _check(name: CheckName, failed: set[str] | None) -> RestoreCheck:
    if failed:
        return RestoreCheck(name, True, False, CHECK_CODE[name], _sorted_tables(failed))
    return RestoreCheck(name, True, True, None)


def _not_ran(name: CheckName) -> RestoreCheck:
    return RestoreCheck(name, False, False, None)


def _complete(src: _View, res: _View, edges: tuple[FkEdge, ...]) -> set[str]:
    bad: set[str] = set()
    if (set(src.tables) != set(res.tables) or not REQUIRED_TABLES <= set(src.tables)
            or sum(len(t[1]) for t in src.tables.values()) == 0):
        bad |= (set(src.tables) ^ set(res.tables)) | (REQUIRED_TABLES - set(src.tables)) | (
            REQUIRED_TABLES - set(res.tables))
        if not bad:
            bad = {"tenants"}  # an all-empty manifest: name a fixed table, never a count
    for view in (src, res):
        for edge in edges:
            child, parent = view.tables.get(edge.child_table), view.tables.get(edge.parent_table)
            if child is None and parent is None:
                continue
            if (child is None or parent is None or not set(edge.child_columns) <= set(child[0])
                    or not set(edge.parent_columns) <= set(parent[0])):
                bad.add(edge.child_table)
    return bad


def _count(src: _View, res: _View) -> set[str]:
    return {n for n in src.tables if len(src.tables[n][1]) != len(res.tables[n][1])}


def _digest(src: _View, res: _View) -> set[str]:
    return {n for n in src.tables if len(src.tables[n][1]) == len(res.tables[n][1])
            and src.tables[n][2] != res.tables[n][2]}


def _fk(res: _View, edges: tuple[FkEdge, ...]) -> set[str]:
    bad: set[str] = set()
    for edge in edges:
        child, parent = res.tables.get(edge.child_table), res.tables.get(edge.parent_table)
        if child is None or parent is None:
            continue
        parent_values = set()
        for entry in parent[1]:
            cols = _cols(entry)
            parent_values.add(tuple(cols[c] for c in edge.parent_columns))
        for entry in child[1]:
            cols = _cols(entry)
            value = tuple(cols[c] for c in edge.child_columns)
            if any(v is None for v in value):  # SQL MATCH SIMPLE: a NULL column skips the constraint
                continue
            if value not in parent_values:
                bad.add(edge.child_table)
                break
    return bad


def _head(src: _View, res: _View) -> set[str]:
    bad: set[str] = set()
    heads = res.tables.get("accepted_heads")
    if heads is None:
        return bad
    obs = {(c["tenant_id"], c["source_id"], c["revision_id"]): c["kind"]
           for c in (_cols(e) for e in res.tables.get("observations", ((), (), ""))[1])}
    events = [_cols(e) for e in res.tables.get("acceptance_events", ((), (), ""))[1]]
    accepted = {(c["tenant_id"], c["source_id"], c["model_key"], c["to_version"]): c["accepted_revision"]
                for c in events}
    newest: dict[tuple[object, object, object], int] = {}
    for c in events:
        if type(c["to_version"]) is int:
            group = (c["tenant_id"], c["source_id"], c["model_key"])
            newest[group] = max(newest.get(group, 0), c["to_version"])  # type: ignore[arg-type]
    restored_heads = {}
    for entry in heads[1]:
        c = _cols(entry)
        restored_heads[(c["tenant_id"], c["source_id"], c["model_key"])] = (c["revision_id"], c["version"])
        revision, version = c["revision_id"], c["version"]
        if type(version) is not int or version < 0:
            bad.add("accepted_heads")
        elif version == 0:
            if revision is not None or newest.get((c["tenant_id"], c["source_id"], c["model_key"]), 0) != 0:
                bad.add("accepted_heads")
        elif (revision is None or obs.get((c["tenant_id"], c["source_id"], revision)) != "OBSERVED"
              or accepted.get((c["tenant_id"], c["source_id"], c["model_key"], version)) != revision
              or newest.get((c["tenant_id"], c["source_id"], c["model_key"]), 0) != version):
            bad.add("accepted_heads")
    source_heads = src.tables.get("accepted_heads")
    if source_heads is not None:
        for entry in source_heads[1]:
            c = _cols(entry)
            if restored_heads.get((c["tenant_id"], c["source_id"], c["model_key"])) != (c["revision_id"],
                                                                                         c["version"]):
                bad.add("accepted_heads")
    return bad


def _sequence(src: _View, res: _View) -> set[str]:
    bad: set[str] = set()
    events = res.tables.get("acceptance_events")
    if events is not None:
        versions: dict[tuple[object, object, object], list[object]] = {}
        for entry in events[1]:
            c = _cols(entry)
            versions.setdefault((c["tenant_id"], c["source_id"], c["model_key"]), []).append(c["to_version"])
        for values in versions.values():
            if (any(type(v) is not int for v in values)
                    or sorted(values) != list(range(1, len(values) + 1))):  # type: ignore[type-var]
                bad.add("acceptance_events")
    outbox = res.tables.get("outbox")
    if outbox is not None:
        restored: dict[tuple[object, object, object], list[object]] = {}
        for entry in outbox[1]:
            c = _cols(entry)
            restored.setdefault((c["tenant_id"], c["source_id"], c["connection_id"]), []).append(c["seq"])
        source: dict[tuple[object, object, object], set[object]] = {}
        for entry in src.tables.get("outbox", ((), (), ""))[1]:
            c = _cols(entry)
            source.setdefault((c["tenant_id"], c["source_id"], c["connection_id"]), set()).add(c["seq"])
        all_seqs = [s for seqs in restored.values() for s in seqs]
        if any(type(s) is not int for s in all_seqs) or len(set(all_seqs)) != len(all_seqs):
            bad.add("outbox")
        else:
            for conn, seqs in restored.items():
                missing = source.get(conn, set()) - set(seqs)
                if missing and any(m < max(seqs) for m in missing):  # type: ignore[type-var,operator]
                    bad.add("outbox")
    return bad


def _scope(view: _View) -> set[str]:
    bad: set[str] = set()
    sources = set(view.sources)
    for name, (columns, entries, _digest_unused) in view.tables.items():
        has_source = "source_id" in columns
        for entry in entries:
            c = _cols(entry)
            if c["tenant_id"] != view.tenant or (has_source and c["source_id"] not in sources):
                bad.add(name)
                break
    return bad


def _attestations(res: _View, port: object, now: datetime) -> set[str]:
    table = res.tables.get("attestations")
    needed: set[tuple[object, object, object]] = set()  # revisions the accepted heads currently rest on
    for entry in res.tables.get("accepted_heads", ((), (), ""))[1]:
        h = _cols(entry)
        if h["revision_id"] is not None:
            needed.add((h["tenant_id"], h["source_id"], h["revision_id"]))
    if table is None:
        return {"attestations"} if needed else set()  # an accepted head with no evidence table is not verified
    obs_digest: dict[tuple[object, object, object], object] = {}
    for entry in res.tables.get("observations", ((), (), ""))[1]:
        c = _cols(entry)
        obs_digest[(c["tenant_id"], c["source_id"], c["revision_id"])] = c["digest"]
    stale = False
    covered: set[tuple[object, object, object]] = set()
    for entry in table[1]:
        c = _cols(entry)
        if (c["tenant_id"], c["source_id"], c["revision_id"]) not in needed:
            continue  # history (immutable, accumulating): an old expired/revoked row does not fail a healthy restore
        covered.add((c["tenant_id"], c["source_id"], c["revision_id"]))
        digest = obs_digest.get((c["tenant_id"], c["source_id"], c["revision_id"]))
        locally_ok = (type(digest) is str and c["revoked_at"] is None and type(c["expires_at"]) is str
                      and type(c["policy_version"]) is str and type(c["policy_digest"]) is str
                      and type(c["attestation_id"]) is str)
        if locally_ok:
            try:
                expires = datetime.fromisoformat(c["expires_at"])  # type: ignore[arg-type]
                locally_ok = expires.tzinfo is not None and expires > now
            except ValueError:
                locally_ok = False
        if not locally_ok:
            stale = True
            continue
        result = port.check_current(  # type: ignore[attr-defined]
            c["attestation_id"], res.tenant, digest, c["policy_version"], c["policy_digest"])
        valid, code = result.valid, result.code  # type: ignore[attr-defined]
        if valid is not True or type(code) is not str or code != "VALID":
            stale = True
    if needed - covered:  # an accepted head whose revision has no attestation row at all is missing evidence
        stale = True
    return {"attestations"} if stale else set()


def verify_restore(scope: object, source_ids: object, source: object, restored: object, ownership: object,
                   entitlement: object, ids: object, attestations: object, clock: object,
                   catalogue: object = LIVING_FK_CATALOGUE) -> RestoreReport | OpsRefusal:
    """Compare a SOURCE manifest with a RESTORED one; never restores, never raises.

    Order: structure -> entitlement -> ownership of every declared source -> manifests are read (both must
    belong to the scope's tenant and the declared sources, else the identical ``NOT_FOUND``) -> the injected
    ``clock`` is read once -> the eight checks. A raising/garbled attestation port gives ``DEPENDENCY_FAILED``.
    """
    try:
        sources = _snapshot_sources(source_ids)
        if sources is None or not is_valid_scope(scope):
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        refusal = check_scope_order(scope, tuple(("source_id", s) for s in sources), ownership, entitlement, ids)
        if refusal is not None:
            return refusal
        edges = _catalogue_snapshot(catalogue)
        src, res = _view(source), _view(restored)
        if edges is None or src is None or res is None or not callable(clock):
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        if not set(LIVING_FK_CATALOGUE) <= set(edges):  # a caller may add edges, never drop the real ones
            return ops_refusal(OpsReason.INPUT_INVALID, ids)
        tenant = scope.tenant_id  # type: ignore[attr-defined]
        if src.tenant != tenant or res.tenant != tenant or src.sources != sources or res.sources != sources:
            return ops_refusal(OpsReason.NOT_FOUND, ids)
        try:
            now = clock()  # type: ignore[operator]
        except Exception:  # noqa: BLE001
            return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
        if not is_aware_datetime(now):
            return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
        incomplete = _complete(src, res, edges)
        if incomplete:
            checks = (_check(CheckName.COMPLETE, incomplete), *(_not_ran(n) for n in _CHECK_ORDER[1:]))
        else:
            try:
                att = _attestations(res, attestations, now)
            except Exception:  # noqa: BLE001 - a raising/garbled port is a dependency failure, not "stale"
                return ops_refusal(OpsReason.DEPENDENCY_FAILED, ids)
            checks = (
                _check(CheckName.COMPLETE, None),
                _check(CheckName.COUNT, _count(src, res)),
                _check(CheckName.DIGEST, _digest(src, res)),
                _check(CheckName.FK, _fk(res, edges)),
                _check(CheckName.HEAD, _head(src, res)),
                _check(CheckName.SEQUENCE, _sequence(src, res)),
                _check(CheckName.ATTESTATION, att),
                _check(CheckName.SCOPE, _scope(src) | _scope(res)),
            )
        cat = sorted([e.child_table, list(e.child_columns), e.parent_table, list(e.parent_columns)] for e in set(edges))
        payload = {"v": 2, "source": src.digest, "restored": res.digest, "catalogue": canonical_digest(cat),
                   "checks": [[c.name.value, c.ran, c.passed, [] if c.code is None else [c.code.value],
                               list(c.tables)] for c in checks]}
        return RestoreReport(checks, src.digest, res.digest, canonical_digest(payload))
    except Exception:  # noqa: BLE001 - never raises, never echoes
        return ops_refusal(OpsReason.INTERNAL_REFUSED, ids)

