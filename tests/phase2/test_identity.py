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


# --- 1C empty reference and GUID canonicalisation (S6b GPT-PM M04/M05) ------------------------

from business_ai_gateway.phase2._identity import canonical_guid, is_empty_1c_ref


@pytest.mark.parametrize("value", [
    "00000000-0000-0000-0000-000000000000",
    "{00000000-0000-0000-0000-000000000000}",
    "(00000000-0000-0000-0000-000000000000)",
    "00000000000000000000000000000000",
    " 00000000-0000-0000-0000-000000000000 ",
])
def test_all_zero_guid_forms_are_the_empty_1c_reference(value):
    assert is_empty_1c_ref(value) is True


@pytest.mark.parametrize("value", [
    "00000000-0000-0000-0000-000000000001", "", "0000", None, 0, b"0" * 32, "doc-1",
    "0000000-00000-0000-0000-000000000000",
])
def test_other_values_are_not_the_empty_reference(value):
    assert is_empty_1c_ref(value) is False


def test_guid_canonicalisation_folds_case_only_for_real_guids():
    upper = "A1234567-89AB-4CDE-8F01-1234567890AB"
    assert canonical_guid(upper) == canonical_guid(upper.lower()) == upper.lower()
    assert canonical_guid("{" + upper + "}") == upper.lower()
    assert canonical_guid("Doc-A") is None and canonical_guid("doc-a") is None
    assert canonical_guid(None) is None


def test_canonical_guid_refuses_a_str_subclass():
    class Lying(str):
        pass
    assert canonical_guid(Lying("a1234567-89ab-4cde-8f01-1234567890ab")) is None


def test_fullwidth_spellings_fold_to_the_same_guid_and_the_empty_reference():
    zero = "０" * 8 + "-" + "０" * 4 + "-" + "０" * 4 + "-" + "０" * 4 + "-" + "０" * 12
    assert is_empty_1c_ref(zero) is True
    ascii_guid = "a1234567-89ab-4cde-8f01-1234567890ab"
    wide = "".join(chr(ord(c) + 0xFEE0) if c.isalnum() and ord(c) < 128 else c for c in ascii_guid)
    assert wide != ascii_guid and canonical_guid(wide) == ascii_guid


def test_over_long_value_is_not_a_guid():
    assert canonical_guid("0" * 100000) is None


# ---- exact-type checks: a str subclass must not smuggle zero-width characters -------------------
class _LyingStr(str):
    """Hides the real content from iteration/len/strip so a naive check sees clean text."""
    def __iter__(self):
        return iter("alice")

    def __len__(self):
        return 5

    def strip(self, chars=None):
        return "alice"


def test_str_subclass_with_zero_width_is_refused_by_exact_text_and_clean_identity():
    hostile = _LyingStr("al\u200bice")
    assert exact_text(hostile) == ""
    assert clean_identity(hostile) == ""
    assert scope_key(hostile, "co") is None
