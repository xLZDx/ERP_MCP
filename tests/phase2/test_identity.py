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


# --- length cap, extra confusable scripts, skeleton / same_person ---------------

from business_ai_gateway.phase2._identity import MAX_TEXT_CHARS, same_person, skeleton


def test_over_cap_text_is_invalid_and_cheap():
    assert clean_identity("a" * MAX_TEXT_CHARS) == "a" * MAX_TEXT_CHARS
    assert clean_identity("a" * (MAX_TEXT_CHARS + 1)) == ""
    assert exact_text("a" * (MAX_TEXT_CHARS + 1)) == ""
    assert clean_identity("a" * 5_000_000) == ""


@pytest.mark.parametrize("other", [
    "\u0561",   # ARMENIAN SMALL LETTER AYB
    "\u2c81",   # COPTIC SMALL LETTER ALFA
    "\u13a0",   # CHEROKEE LETTER A
    "\ua4d0",   # LISU LETTER BA
    "\u1401",   # CANADIAN SYLLABICS E
    "\u043e",   # Cyrillic
])
def test_mixing_tracked_scripts_is_invalid(other):
    assert clean_identity("alice" + other) == ""
    assert clean_identity(other + "alice") == ""


def test_two_non_latin_tracked_scripts_mixed_are_invalid():
    assert clean_identity("\u0561\u0441") == ""  # Armenian + Cyrillic


def test_same_person_detects_all_cyrillic_lookalike():
    lookalike = "\u0430\u04cf\u0456\u0441\u0435"
    assert clean_identity(lookalike) == lookalike  # valid single-script text on its own
    assert same_person("alice", lookalike)
    assert skeleton(lookalike) == "alice"


def test_distinct_names_and_invalid_input_are_not_same_person():
    assert not same_person("alice", "alicia")
    assert not same_person("alice", "bob")
    assert not same_person("", "")
    assert not same_person("al\u200bice", "alice")
    assert not same_person(None, None)
    assert skeleton("alice\u0430") == ""  # mixed script stays invalid
