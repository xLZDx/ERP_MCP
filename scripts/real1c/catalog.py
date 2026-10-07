"""Frozen story catalogue loader/verifier for the real 1C 818HA lane.

The catalogue file is a frozen input. Nothing here rewrites or repairs it:
any deviation raises ``CatalogFrozenError``.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

FROZEN_SHA256 = "dad5bddccc3c24acc8df876f60188a2094c22bddd284ffc7063b273620437e13"
FROZEN_COUNTS = {"ST": 90, "AX": 40, "REQ_GAP": 27}
FROZEN_CLASS_COUNTS = {"RR": 16, "NP": 53, "UG": 26, "EV": 29, "WD": 6}
FROZEN_PRIORITY_COUNTS = {"P0": 37, "P1": 76, "P2": 17}
CLASSES = tuple(FROZEN_CLASS_COUNTS)

_ST_RE = re.compile(r"^- (ST-(\d{3})) \| ")
_AX_RE = re.compile(r"^- (AX-(\d{3})) (.*)$")
_GAP_RE = re.compile(r"^- (REQ-GAP-(\d{2})) (.*)$")
_HEAD_RE = re.compile(r"^## (A\d+|B|C|D)\.\s*(.*)$")
_PRIORITY_RE = re.compile(r"^P[0-2]$")


class CatalogFrozenError(Exception):
    """The catalogue differs from the frozen contract."""


@dataclass(frozen=True)
class Story:
    id: str
    kind: str
    title: str
    persona: str
    tools: tuple[str, ...]
    catalogue_class: str
    oracle: str
    priority: str
    raw_line: str
    section: str = ""


@dataclass(frozen=True)
class Section:
    code: str
    title: str
    story_ids: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    stories: tuple[Story, ...]
    req_gaps: tuple[tuple[str, str], ...]
    sha256: str
    sections: tuple[Section, ...] = ()

    def story_ids(self) -> tuple[str, ...]:
        return tuple(s.id for s in self.stories)


def frozen_sha256(data: bytes) -> str:
    """SHA-256 over LF-normalised bytes (autocrlf-safe)."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _class_of(token: str, story_id: str) -> str:
    cls = token.strip().split(" ")[0] if token.strip() else ""
    if cls not in CLASSES:
        raise CatalogFrozenError(f"{story_id}: unknown disposition class {token!r}")
    return cls


def _parse_st(line: str, story_id: str, section: str) -> Story:
    parts = [p.strip() for p in line[2:].split(" | ")]
    if len(parts) != 10:
        raise CatalogFrozenError(f"{story_id}: expected 10 fields, got {len(parts)}")
    return Story(
        id=story_id,
        kind="ST",
        title=parts[1],
        persona=parts[2],
        tools=tuple(t.strip() for t in parts[5].split(",") if t.strip()),
        catalogue_class=_class_of(parts[6], story_id),
        oracle=parts[7],
        priority=parts[9],
        raw_line=line,
        section=section,
    )


def _parse_ax(line: str, story_id: str, rest: str, section: str) -> Story:
    parts = [p.strip() for p in line[2:].split(" | ")]
    # id+title | persona | tools | disp | oracle | [neg |] pri
    if len(parts) not in (6, 7):
        raise CatalogFrozenError(f"{story_id}: expected 6-7 fields, got {len(parts)}")
    title = parts[0][len(story_id) :].strip()
    return Story(
        id=story_id,
        kind="AX",
        title=title,
        persona=parts[1],
        tools=tuple(t.strip() for t in parts[2].split(",") if t.strip()),
        catalogue_class=_class_of(parts[3], story_id),
        oracle=parts[4],
        priority=parts[-1],
        raw_line=line,
        section=section,
    )


def load_catalog(path: str | Path) -> Catalog:
    data = Path(path).read_bytes()
    digest = frozen_sha256(data)
    text = data.replace(b"\r\n", b"\n").decode("utf-8")
    stories: list[Story] = []
    gaps: list[tuple[str, str]] = []
    sections: list[tuple[str, str, list[str]]] = []
    current = ""
    for line in text.split("\n"):
        head = _HEAD_RE.match(line)
        if head:
            current = head.group(1)
            if current in {"B"} or current.startswith("A"):
                sections.append((current, head.group(2).strip(), []))
            continue
        m = _ST_RE.match(line)
        if m:
            story = _parse_st(line, m.group(1), current)
        else:
            m = _AX_RE.match(line)
            if m:
                story = _parse_ax(line, m.group(1), m.group(3), current)
            else:
                g = _GAP_RE.match(line)
                if g:
                    gaps.append((g.group(1), g.group(3).strip()))
                continue
        stories.append(story)
        if not sections:
            raise CatalogFrozenError(f"{story.id}: story outside any section")
        sections[-1][2].append(story.id)
    return Catalog(
        stories=tuple(stories),
        req_gaps=tuple(gaps),
        sha256=digest,
        sections=tuple(Section(c, t, tuple(ids)) for c, t, ids in sections),
    )


def _check_contiguous(ids: list[str], prefix: str, width: int, expected: int) -> None:
    if len(set(ids)) != len(ids):
        dups = sorted(i for i, n in Counter(ids).items() if n > 1)
        raise CatalogFrozenError(f"duplicate {prefix} ids: {dups}")
    want = [f"{prefix}-{n:0{width}d}" for n in range(1, expected + 1)]
    if ids != want:
        raise CatalogFrozenError(f"{prefix} ids are not contiguous 1..{expected} in order")


def verify_frozen(path: str | Path) -> Catalog:
    data = Path(path).read_bytes()
    actual = frozen_sha256(data)
    if actual != FROZEN_SHA256:
        raise CatalogFrozenError(f"catalogue sha256 mismatch: {actual} != {FROZEN_SHA256}")
    catalog = load_catalog(path)
    st = [s.id for s in catalog.stories if s.kind == "ST"]
    ax = [s.id for s in catalog.stories if s.kind == "AX"]
    gaps = [g[0] for g in catalog.req_gaps]
    counts = {"ST": len(st), "AX": len(ax), "REQ_GAP": len(gaps)}
    if counts != FROZEN_COUNTS:
        raise CatalogFrozenError(f"count mismatch: {counts} != {FROZEN_COUNTS}")
    _check_contiguous(st, "ST", 3, FROZEN_COUNTS["ST"])
    _check_contiguous(ax, "AX", 3, FROZEN_COUNTS["AX"])
    _check_contiguous(gaps, "REQ-GAP", 2, FROZEN_COUNTS["REQ_GAP"])
    classes = dict.fromkeys(CLASSES, 0)
    classes.update(Counter(s.catalogue_class for s in catalog.stories))
    if classes != FROZEN_CLASS_COUNTS:
        raise CatalogFrozenError(f"class count mismatch: {classes} != {FROZEN_CLASS_COUNTS}")
    bad = [s.id for s in catalog.stories if not _PRIORITY_RE.match(s.priority)]
    if bad:
        raise CatalogFrozenError(f"invalid priority on: {bad}")
    prios = dict.fromkeys(FROZEN_PRIORITY_COUNTS, 0)
    prios.update(Counter(s.priority for s in catalog.stories))
    if prios != FROZEN_PRIORITY_COUNTS:
        raise CatalogFrozenError(f"priority count mismatch: {prios} != {FROZEN_PRIORITY_COUNTS}")
    return catalog
