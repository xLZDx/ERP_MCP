"""Row-count fingerprints of a 1C infobase over an already-open COM connection (read-only ВЫБРАТЬ counts).

Shared by the oracle (comparison queries) and the native engine-report generator so there is one mechanism.
The functions never open a connection and never choose an identity: the caller owns the connection.
"""

from __future__ import annotations

import hashlib
from typing import Any

KINDS = ("Catalogs", "Documents", "AccumulationRegisters", "AccountingRegisters", "InformationRegisters",
         "ChartsOfAccounts")
QUERY_KIND = {
    "Catalogs": "Справочник", "Documents": "Документ", "AccumulationRegisters": "РегистрНакопления",
    "AccountingRegisters": "РегистрБухгалтерии", "InformationRegisters": "РегистрСведений",
    "ChartsOfAccounts": "ПланСчетов",
}


def _sha(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def metadata_names(conn: Any) -> list[str]:
    return sorted(f"{kind}.{obj.Name}" for kind in KINDS for obj in getattr(conn.Metadata, kind))


def _count(conn: Any, kind: str, name: str) -> int:
    text = f"ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК К ИЗ {QUERY_KIND[kind]}.{name} КАК Т"
    table = conn.NewObject("Запрос", text).Выполнить().Выгрузить()
    return int(table.Get(0).К) if table.Count() else 0


def table_counts(conn: Any) -> dict[str, int]:
    return {f"{kind}.{obj.Name}": _count(conn, kind, obj.Name) for kind in KINDS for obj in getattr(conn.Metadata, kind)}


def fingerprint_of(conn: Any) -> dict:
    names = metadata_names(conn)
    counts = table_counts(conn)
    return {
        "metadata_fingerprint": _sha(names),
        "metadata_object_count": len(names),
        "content_fingerprint_sha256": _sha([f"{key}={counts[key]}" for key in sorted(counts)]),
        "table_count": len(counts),
        "total_rows": sum(counts.values()),
        "nonempty_tables": sum(1 for value in counts.values() if value),
        "per_table": counts,
    }


def readable_fingerprint(conn: Any) -> dict:
    """Fingerprint over the tables THIS identity may read (a low-privilege reader cannot read every table).

    A table that raises on read (insufficient rights) is listed as unreadable and excluded from the content hash, so the
    caller can still prove pre/post equality on everything the identity can see and must report the coverage honestly.
    """
    names = metadata_names(conn)
    counts: dict[str, int] = {}
    unreadable: list[str] = []
    for kind in KINDS:
        for obj in getattr(conn.Metadata, kind):
            key = f"{kind}.{obj.Name}"
            try:
                counts[key] = _count(conn, kind, obj.Name)
            except Exception:  # noqa: BLE001 - insufficient rights for this table
                unreadable.append(key)
    return {
        "metadata_fingerprint": _sha(names),
        "metadata_object_count": len(names),
        "content_fingerprint_sha256": _sha([f"{key}={counts[key]}" for key in sorted(counts)]),
        "readable_tables": len(counts),
        "unreadable_tables": len(unreadable),
        "unreadable_fingerprint": _sha(sorted(unreadable)),
        "total_rows_readable": sum(counts.values()),
        "per_table": counts,
    }
