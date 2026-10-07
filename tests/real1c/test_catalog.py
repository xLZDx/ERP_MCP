from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from scripts.real1c.catalog import (
    FROZEN_CLASS_COUNTS,
    FROZEN_COUNTS,
    FROZEN_PRIORITY_COUNTS,
    FROZEN_SHA256,
    CatalogFrozenError,
    load_catalog,
    verify_frozen,
)

CATALOG = Path(__file__).resolve().parents[2] / "docs" / "REAL_1C_STORY_CATALOG_818HA.md"


def test_real_catalog_verifies_and_counts_match():
    cat = verify_frozen(CATALOG)
    assert cat.sha256 == FROZEN_SHA256
    kinds = Counter(s.kind for s in cat.stories)
    assert (kinds["ST"], kinds["AX"], len(cat.req_gaps)) == (90, 40, 27)
    assert {"ST": kinds["ST"], "AX": kinds["AX"], "REQ_GAP": len(cat.req_gaps)} == FROZEN_COUNTS
    assert dict(Counter(s.catalogue_class for s in cat.stories)) == FROZEN_CLASS_COUNTS
    assert dict(Counter(s.priority for s in cat.stories)) == FROZEN_PRIORITY_COUNTS
    assert FROZEN_CLASS_COUNTS == {"RR": 16, "NP": 53, "UG": 26, "EV": 29, "WD": 6}


def test_sections_cover_every_story_once():
    cat = load_catalog(CATALOG)
    grouped = [i for sec in cat.sections for i in sec.story_ids]
    assert sorted(grouped) == sorted(cat.story_ids())
    assert [s.code for s in cat.sections] == [f"A{n}" for n in range(1, 11)] + ["B"]


def test_ax_parsing_handles_detail_and_optional_negative():
    cat = {s.id: s for s in load_catalog(CATALOG).stories}
    assert cat["AX-008"].catalogue_class == "UG"
    assert cat["AX-029"].catalogue_class == "UG"
    assert cat["AX-023"].catalogue_class == "NP"
    assert cat["AX-001"].priority == "P1"
    assert cat["ST-014"].catalogue_class == "NP"
    assert cat["ST-001"].tools == ("ABT", "APR", "EVM")


def test_tampered_copy_raises(tmp_path):
    data = CATALOG.read_bytes()
    bad = tmp_path / "cat.md"
    bad.write_bytes(data.replace(b"Month-closed", b"Month-Closed", 1))
    with pytest.raises(CatalogFrozenError, match="sha256"):
        verify_frozen(bad)


def test_crlf_copy_still_verifies(tmp_path):
    data = CATALOG.read_bytes().replace(b"\r\n", b"\n")
    crlf = tmp_path / "cat.md"
    crlf.write_bytes(data.replace(b"\n", b"\r\n"))
    assert verify_frozen(crlf).sha256 == FROZEN_SHA256


def test_unknown_class_in_loader_raises(tmp_path):
    text = CATALOG.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    bad = tmp_path / "cat.md"
    bad.write_text(text.replace("| EV | OEXT | X12 | P1", "| ZZ | OEXT | X12 | P1", 1), "utf-8")
    with pytest.raises(CatalogFrozenError, match="unknown disposition class"):
        load_catalog(bad)
