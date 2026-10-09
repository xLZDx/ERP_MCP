"""Behavioural tests of the shared strict identity helper (spoofing resistance)."""
import pytest

from business_ai_gateway.phase2._identity import clean_identity, exact_text, scope_key


@pytest.mark.parametrize("value", [
    "alice️",            # variation selector: invisible, category Mn
    "alice\U000e0100",        # variation selector supplement
    "ali͏ce",            # combining grapheme joiner
    "al᠋ice",            # Mongolian free variation selector
    "al\u200bice",            # zero width space (Cf)
    "аlice",             # Cyrillic a inside a Latin word (mixed script)
    "aliceο",            # Greek omicron inside a Latin word
    "alice",            # private use (Co)
    "al͸ice",            # unassigned (Cn)
    "⠀", "ㅤ",       # blank glyphs
])
def test_spoofing_variants_are_invalid_not_repaired(value):
    assert clean_identity(value) == ""
    assert exact_text(value) == ""


@pytest.mark.parametrize("value, expected", [
    ("Alice", "alice"),
    ("  ACME-1  ", "acme-1"),
    ("Иван", "иван"),   # a purely Cyrillic name is fine
    ("café", "café"),
])
def test_legitimate_identities_still_normalise(value, expected):
    assert clean_identity(value) == expected


def test_scope_key_needs_both_parts_and_rejects_spoofed_parts():
    assert scope_key("A", "s1") == ("a", "s1")
    assert scope_key("A", "s️1") is None
    assert scope_key("", "s1") is None
    assert scope_key("A", None) is None
