"""Parity harness for the hybrid OData + COM analytics balance route (ADR-0008 section 8).

Pure offline logic: no network, no COM. The caller supplies two fetch callables. The harness proves, BEFORE either
fetcher is called, that the OData publication and the COM clone are the same physical database and that neither is
the reference clone. Only counts and sha256 digests are ever reported, never values.

Labels: ``parity_proof`` only when a separate publication descriptor proof passed; otherwise ``cross_copy_comparison``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as SafeET

INFOBASE_FILE = "1Cv8.1CD"
LABEL_PROOF = "parity_proof"
LABEL_CROSS_COPY = "cross_copy_comparison"
# A real descriptor writes ib="File=D:\path;" (unquoted); the quoted form File="path"; is accepted too.
_FILE_RE = re.compile(r'File\s*=\s*(?:"([^"]+)"|([^";]+))', re.IGNORECASE)


class ParityRefused(Exception):
    """The pair of sides is not provably the same database; nothing was read."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def publication_infobase_path(descriptor_path: str | Path) -> Path:
    """The infobase directory named by ``point``/``ib`` (``ib="File=\\"<path>\\";"``) of a publication descriptor."""
    try:
        root = SafeET.parse(str(descriptor_path)).getroot()
    except (OSError, ParseError, ValueError):
        raise ParityRefused("publication descriptor is unreadable") from None
    found: list[str] = []
    for element in root.iter():
        ib = element.attrib.get("ib")
        if ib is not None and _local(element.tag) in {"point", "ib"}:
            found.append(ib)
    if len(found) != 1:
        raise ParityRefused("publication descriptor must name exactly one infobase")
    match = _FILE_RE.search(found[0])
    if match is None:
        raise ParityRefused("publication descriptor does not address a file infobase")
    return Path(match.group(1) or match.group(2))


def _db_file(base: Path) -> Path:
    candidate = base / INFOBASE_FILE
    if not candidate.is_file():
        raise ParityRefused("an infobase file is missing")
    return candidate


def _same_file(a: Path, b: Path) -> bool:
    return os.path.samefile(a, b)


def _is_reference(base: Path, reference_path: Path) -> bool:
    if base.resolve() == reference_path.resolve():
        return True
    ref_db = reference_path / INFOBASE_FILE
    db = base / INFOBASE_FILE
    return ref_db.is_file() and db.is_file() and _same_file(db, ref_db)


def assert_not_reference(base: str | Path, reference_path: str | Path) -> None:
    if _is_reference(Path(base), Path(reference_path)):
        raise ParityRefused("a side resolves to the reference clone")


@dataclass(frozen=True)
class SameDatabaseProof:
    publication_infobase_sha256: str
    com_base_sha256: str


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def same_database_proof(
    publication_descriptor_path: str | Path, com_base_path: str | Path, *, reference_path: str | Path
) -> SameDatabaseProof:
    publication_base = publication_infobase_path(publication_descriptor_path)
    com_base = Path(com_base_path)
    reference = Path(reference_path)
    assert_not_reference(publication_base, reference)
    assert_not_reference(com_base, reference)
    if not _same_file(_db_file(publication_base), _db_file(com_base)):
        raise ParityRefused("the publication and the COM clone are not the same database")
    return SameDatabaseProof(
        publication_infobase_sha256=_sha(str(publication_base.resolve()).lower()),
        com_base_sha256=_sha(str(com_base.resolve()).lower()),
    )


# --- canonical comparison ------------------------------------------------------------------------------------------
def _amount(row: Mapping[str, Any], short: str, long: str) -> Decimal:
    value = row[short] if short in row else row[long]
    return Decimal(str(value))


def _canonical(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[Any, ...], tuple[Decimal, Decimal]]:
    out: dict[tuple[Any, ...], list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for row in rows:
        key = (row["account_key"], *(slot.get("ref") for slot in row["analytics"]))
        out[key][0] += _amount(row, "debit", "balance_debit")
        out[key][1] += _amount(row, "credit", "balance_credit")
    return {k: (v[0], v[1]) for k, v in out.items()}


def _digest(side: Mapping[tuple[Any, ...], tuple[Decimal, Decimal]]) -> str:
    lines = sorted(
        json.dumps([list(k), format(v[0].normalize(), "f"), format(v[1].normalize(), "f")], ensure_ascii=False)
        for k, v in side.items()
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CompareResult:
    odata_rows: int
    com_rows: int
    matched_keys: int
    only_in_odata: int
    only_in_com: int
    amount_mismatches: int
    odata_sha256: str
    com_sha256: str

    @property
    def equal(self) -> bool:
        return self.only_in_odata == 0 and self.only_in_com == 0 and self.amount_mismatches == 0


def compare_canonical(
    odata_rows: Iterable[Mapping[str, Any]], com_rows: Iterable[Mapping[str, Any]]
) -> CompareResult:
    odata_list, com_list = list(odata_rows), list(com_rows)
    odata, com = _canonical(odata_list), _canonical(com_list)
    shared = odata.keys() & com.keys()
    return CompareResult(
        odata_rows=len(odata_list),
        com_rows=len(com_list),
        matched_keys=len(shared),
        only_in_odata=len(odata.keys() - com.keys()),
        only_in_com=len(com.keys() - odata.keys()),
        amount_mismatches=sum(1 for k in shared if odata[k] != com[k]),
        odata_sha256=_digest(odata),
        com_sha256=_digest(com),
    )


# --- run ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ParityContext:
    run_id: str  # immutable run identity chosen by the caller
    clone_identity: str
    publication_identity: str | None
    odata_metadata_fingerprint: str
    com_metadata_fingerprint: str
    pre_fingerprint: str
    post_fingerprint: str


def run_parity(
    *,
    context: ParityContext,
    com_base_path: str | Path,
    reference_path: str | Path,
    odata_fetch: Callable[[], Iterable[Mapping[str, Any]]],
    com_fetch: Callable[[], Iterable[Mapping[str, Any]]],
    publication_descriptor_path: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    if not context.run_id:
        raise ParityRefused("a run identity is required")
    if publication_descriptor_path is not None:
        proof: SameDatabaseProof | None = same_database_proof(
            publication_descriptor_path, com_base_path, reference_path=reference_path
        )
    else:
        assert_not_reference(com_base_path, reference_path)
        proof = None
    result = compare_canonical(odata_fetch(), com_fetch())
    stable = (
        context.pre_fingerprint == context.post_fingerprint
        and context.odata_metadata_fingerprint == context.com_metadata_fingerprint
    )
    manifest: dict[str, Any] = {
        "run_id": context.run_id,
        "label": LABEL_PROOF if proof is not None else LABEL_CROSS_COPY,
        "same_database_proof": asdict(proof) if proof is not None else None,
        "clone_identity": context.clone_identity,
        "publication_identity": context.publication_identity,
        "odata_metadata_fingerprint": context.odata_metadata_fingerprint,
        "com_metadata_fingerprint": context.com_metadata_fingerprint,
        "pre_fingerprint": context.pre_fingerprint,
        "post_fingerprint": context.post_fingerprint,
        "fingerprints_stable": stable,
        "result": {**asdict(result), "equal": result.equal and stable},
    }
    if manifest_path is not None:
        with open(manifest_path, "x", encoding="utf-8") as handle:  # a run manifest is never overwritten
            json.dump(manifest, handle, indent=2, sort_keys=True)
    return manifest
