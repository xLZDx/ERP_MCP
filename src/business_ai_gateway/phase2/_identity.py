"""Strict identity/text helpers shared by the taxonomy and alias modules (pure, stdlib only).

``promotion.normalize_identity`` only does NFKC + casefold + strip, so zero-width / format /
separator / blank-glyph characters survive and let ``al\\u200bice`` pose as an independent person.
Here any string containing such a character is treated as INVALID (returned as ''), never repaired.
"""
from __future__ import annotations

import json
import unicodedata

__all__ = [
    "MAX_TEXT_CHARS", "clean_identity", "exact_text", "same_person", "scope_key", "skeleton",
    "stable_key",
]

_BAD_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp", "Zs"})
# default-ignorable combining marks (variation selectors etc.) are invisible but are category Mn
_IGNORABLE_RANGES = (
    (0x034F, 0x034F), (0x17B4, 0x17B5), (0x180B, 0x180F), (0xFE00, 0xFE0F),
    (0xE0100, 0xE01EF),
)
# scripts whose letters are routinely confused with each other; mixing them in one identifier is refused
_CONFUSABLE_SCRIPTS = (
    "LATIN", "CYRILLIC", "GREEK", "ARMENIAN", "CHEROKEE", "COPTIC", "LISU", "CANADIAN",
)
# Longest identity/operation/right text accepted at all (checked before any per-character work).
MAX_TEXT_CHARS = 256
# PARTIAL confusable table (NOT full UTS#39): common single-script lookalikes -> Latin.
_SKELETON_MAP = str.maketrans({
    # Cyrillic
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y",
    "х": "x", "і": "i", "ј": "j", "ӏ": "l", "ѕ": "s", "һ": "h",
    "ԁ": "d", "ԛ": "q", "ԝ": "w", "к": "k", "м": "m", "т": "t",
    "в": "b", "н": "h",
    # Greek
    "ο": "o", "α": "a", "ν": "v", "ρ": "p", "ι": "i", "κ": "k",
    "τ": "t", "υ": "u", "χ": "x",
    # Armenian
    "օ": "o", "ս": "u", "ո": "n", "ց": "g", "հ": "h", "զ": "q",
})
# visually blank code points that are not in the categories above
_BLANK_GLYPHS = frozenset("\u2800\u3164\u115f\u1160\uffa0")


def _has_forbidden(text: str) -> bool:
    scripts: set[str] = set()
    for ch in text:
        if ch in _BLANK_GLYPHS:
            return True
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _IGNORABLE_RANGES):
            return True
        category = unicodedata.category(ch)
        if ch != " " and category in _BAD_CATEGORIES:
            return True
        if category[0] == "L":
            head = unicodedata.name(ch, "").split(" ", 1)[0]
            if head in _CONFUSABLE_SCRIPTS:
                scripts.add(head)
    return len(scripts) > 1


def _visible(text: str) -> bool:
    return any(unicodedata.category(ch)[0] in "LNP" for ch in text)


def exact_text(value: object) -> str:
    """Trimmed, case-preserved text; '' when not a str, forbidden chars, or nothing visible."""
    if not isinstance(value, str) or len(value) > MAX_TEXT_CHARS or _has_forbidden(value):
        return ""
    out = value.strip(" ")
    return out if _visible(out) else ""


def clean_identity(value: object) -> str:
    """NFKC + casefold + strip; '' when not a str, forbidden chars (raw or normalised) or blank."""
    if not isinstance(value, str) or len(value) > MAX_TEXT_CHARS or _has_forbidden(value):
        return ""
    norm = unicodedata.normalize("NFKC", value)
    if len(norm) > MAX_TEXT_CHARS or _has_forbidden(norm):
        return ""
    out = norm.strip(" ").casefold()
    return out if _visible(out) else ""


def skeleton(value: object) -> str:
    """clean_identity then fold common Cyrillic/Greek/Armenian lookalikes to Latin ('' if invalid).

    PARTIAL confusable table, not full UTS#39: it narrows spoofing, it does not prove two
    different strings are different people.
    """
    return clean_identity(value).translate(_SKELETON_MAP)


def same_person(a: object, b: object) -> bool:
    """True when both identities are valid and their skeletons are equal."""
    first = skeleton(a)
    return bool(first) and first == skeleton(b)


def scope_key(tenant: object, company: object) -> tuple[str, str] | None:
    """The single scope normalisation for every phase-2 module; None when either part is unusable."""
    t, c = clean_identity(tenant), clean_identity(company)
    return (t, c) if t and c else None


def stable_key(*parts: str) -> str:
    """Unambiguous (JSON) encoding of ordered string parts, safe to hash."""
    return json.dumps(list(parts), ensure_ascii=True, separators=(",", ":"))
