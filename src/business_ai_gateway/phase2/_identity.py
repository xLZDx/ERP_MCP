"""Strict identity/text helpers shared by the taxonomy and alias modules (pure, stdlib only).

``promotion.normalize_identity`` only does NFKC + casefold + strip, so zero-width / format /
separator / blank-glyph characters survive and let ``al\\u200bice`` pose as an independent person.
Here any string containing such a character is treated as INVALID (returned as ''), never repaired.
"""
from __future__ import annotations

import json
import unicodedata

__all__ = ["clean_identity", "exact_text", "scope_key", "stable_key"]

_BAD_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp", "Zs"})
# visually blank code points that are not in the categories above
_BLANK_GLYPHS = frozenset("\u2800\u3164\u115f\u1160\uffa0")


def _has_forbidden(text: str) -> bool:
    for ch in text:
        if ch in _BLANK_GLYPHS:
            return True
        if ch != " " and unicodedata.category(ch) in _BAD_CATEGORIES:
            return True
    return False


def _visible(text: str) -> bool:
    return any(unicodedata.category(ch)[0] in "LNP" for ch in text)


def exact_text(value: object) -> str:
    """Trimmed, case-preserved text; '' when not a str, forbidden chars, or nothing visible."""
    if not isinstance(value, str) or _has_forbidden(value):
        return ""
    out = value.strip(" ")
    return out if _visible(out) else ""


def clean_identity(value: object) -> str:
    """NFKC + casefold + strip; '' when not a str, forbidden chars (raw or normalised) or blank."""
    if not isinstance(value, str) or _has_forbidden(value):
        return ""
    norm = unicodedata.normalize("NFKC", value)
    if _has_forbidden(norm):
        return ""
    out = norm.strip(" ").casefold()
    return out if _visible(out) else ""


def scope_key(tenant: object, company: object) -> tuple[str, str] | None:
    """The single scope normalisation for every phase-2 module; None when either part is unusable."""
    t, c = clean_identity(tenant), clean_identity(company)
    return (t, c) if t and c else None


def stable_key(*parts: str) -> str:
    """Unambiguous (JSON) encoding of ordered string parts, safe to hash."""
    return json.dumps(list(parts), ensure_ascii=True, separators=(",", ":"))
