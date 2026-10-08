"""Tests for Phase 2 per-object OBSERVED change classification, no I/O."""
from dataclasses import replace

import pytest

from business_ai_gateway.phase2.structural_diff import ChangeKind, diff_observed
from business_ai_gateway.phase2.structural_hash import fingerprint_edmx

PRE = b'<edmx:Edmx xmlns:edmx="urn:edmx" xmlns:e="urn:edm" Version="1"><edmx:DataServices><e:Schema Namespace="Sample">'
POST = b'</e:Schema></edmx:DataServices></edmx:Edmx>'


def edmx(fields=b'<e:Property Name="Code" Type="Edm.String" MaxLength="10"/>', extra=b''):
    return PRE + b'<e:EntityType Name="Person">' + fields + b'</e:EntityType>' + extra + (
        b'<e:EntityContainer Name="Default">'
        b'<e:EntitySet Name="People" EntityType="Sample.Person"/>'
        b'</e:EntityContainer>'
    ) + POST


def snapshot(fields=None, extra=b''):
    return fingerprint_edmx(edmx(fields if fields is not None else (
        b'<e:Property Name="Code" Type="Edm.String" MaxLength="10"/>'), extra))


def test_identical_observations_are_stable():
    a = snapshot()
    result = diff_observed(a, a)
    assert result.has_changes is False
    assert result.changes == ()
    assert result.trust_level == "OBSERVED_ONLY"


def test_xml_only_format_difference_is_not_structural_drift():
    before = fingerprint_edmx(edmx())
    after = fingerprint_edmx(edmx().replace(b'Name="Person"', b'Name="Person"  '))
    assert before.raw_sha256 != after.raw_sha256
    result = diff_observed(before, after)
    assert result.has_changes is False
    assert result.changes == ()


def test_add_entity_is_explicit_and_scoped():
    a = snapshot()
    b = snapshot(extra=b'<e:ComplexType Name="Note"><e:Property Name="Text" Type="Edm.String"/></e:ComplexType>')
    r = diff_observed(a, b)
    assert r.has_changes and not r.unattributed_structural_change
    assert [(x.qualified_name, x.kind) for x in r.changes] == [
        ("Sample::ComplexType::Note", ChangeKind.ADDED)
    ]


def test_remove_entity_is_distinct_from_modify():
    a = snapshot(extra=b'<e:ComplexType Name="Note"/>')
    b = snapshot()
    r = diff_observed(a, b)
    assert r.changes[0].kind == ChangeKind.REMOVED
    assert r.changes[0].observed_sha256 is None


def test_type_change_is_modified_and_keeps_both_hashes():
    a = snapshot()
    b = snapshot(fields=b'<e:Property Name="Code" Type="Edm.String" MaxLength="11"/>')
    r = diff_observed(a, b)
    assert len(r.changes) == 1
    x = r.changes[0]
    assert x.kind == ChangeKind.MODIFIED
    assert x.previous_sha256 and x.observed_sha256 and x.previous_sha256 != x.observed_sha256


def test_results_are_deterministically_ordered():
    a = snapshot()
    b = snapshot(extra=b'<e:ComplexType Name="Z"/><e:ComplexType Name="A"/>')
    r = diff_observed(a, b)
    assert [x.qualified_name for x in r.changes] == [
        "Sample::ComplexType::A", "Sample::ComplexType::Z"
    ]


def test_canonicalizer_version_mismatch_is_refused():
    a = snapshot()
    b = replace(a, canonicalizer_version="edmx-structural-v2")
    with pytest.raises(ValueError, match="VERSION_MISMATCH"):
        diff_observed(a, b)


def test_unattributed_hash_change_requires_global_review():
    a = snapshot()
    b = replace(a, structural_sha256="f" * 64)
    result = diff_observed(a, b)
    assert result.unattributed_structural_change is True
    assert result.has_changes and result.changes == ()


def test_inconsistent_object_hash_change_is_refused():
    a = snapshot()
    b = replace(a, objects=(("Sample::EntityType::Person", "f" * 64),))
    with pytest.raises(ValueError, match="INCONSISTENT_FINGERPRINT"):
        diff_observed(a, b)


def test_duplicate_identity_is_refused():
    a = snapshot()
    b = replace(a, objects=a.objects + (a.objects[0],))
    with pytest.raises(ValueError, match="DUPLICATE_OBJECT_ID"):
        diff_observed(a, b)
