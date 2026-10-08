"""Isolated tests for the Phase 2 OBSERVED metadata fingerprint helper."""
from xml.etree.ElementTree import ParseError

import pytest
from defusedxml.common import DefusedXmlException

from business_ai_gateway.phase2.structural_hash import fingerprint_edmx

PREFIX = b'<edmx:Edmx xmlns:edmx="urn:edmx" xmlns:e="urn:edm" Version="1"><edmx:DataServices><e:Schema Namespace="Sample">'
SUFFIX = b'</e:Schema></edmx:DataServices></edmx:Edmx>'


def model(fields=b'<e:Property Name="Code" Type="Edm.String" MaxLength="10"/>', middle=b''):
    return PREFIX + (b'<e:EntityType Name="Person"><e:Key><e:PropertyRef Name="Code"/></e:Key>'
                     + fields + b'</e:EntityType>' + middle
                     + b'<e:EntityContainer Name="Default"><e:EntitySet Name="People" EntityType="Sample.Person"/>'
                     + b'</e:EntityContainer>') + SUFFIX


def test_whitespace_does_not_change_structural_hash():
    a = model()
    b = a.replace(b'<e:Property Name=', b'\n  <e:Property  Name=')
    assert fingerprint_edmx(a).raw_sha256 != fingerprint_edmx(b).raw_sha256
    assert fingerprint_edmx(a).structural_sha256 == fingerprint_edmx(b).structural_sha256


def test_property_reordering_does_not_change_structural_hash():
    a = model(b'<e:Property Name="Code" Type="Edm.String"/><e:Property Name="Date" Type="Edm.DateTime"/>')
    b = model(b'<e:Property Name="Date" Type="Edm.DateTime"/><e:Property Name="Code" Type="Edm.String"/>')
    assert fingerprint_edmx(a).structural_sha256 == fingerprint_edmx(b).structural_sha256


def test_semantic_type_change_does_change_hash():
    before = model()
    after = model().replace(b'MaxLength="10"', b'MaxLength="12"')
    assert fingerprint_edmx(before).structural_sha256 != fingerprint_edmx(after).structural_sha256
    assert fingerprint_edmx(before).object_hashes()['Sample::EntityType::Person'] != fingerprint_edmx(after).object_hashes()['Sample::EntityType::Person']


def test_object_added_changes_hash_without_prior_object_change():
    a = fingerprint_edmx(model())
    b = fingerprint_edmx(model(middle=b'<e:ComplexType Name="Extra"><e:Property Name="X" Type="Edm.Int32"/></e:ComplexType>'))
    assert a.object_hashes()['Sample::EntityType::Person'] == b.object_hashes()['Sample::EntityType::Person']
    assert a.structural_sha256 != b.structural_sha256


@pytest.mark.parametrize('payload', [b'', b'<html/>', b'<edmx:Edmx xmlns:edmx="urn:edmx"/>', b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'])
def test_bad_edmx_fails_closed(payload):
    with pytest.raises((ValueError, ParseError, DefusedXmlException)):
        fingerprint_edmx(payload)


def test_reject_incomplete_entity_set():
    with pytest.raises(ValueError, match='EDMX_ENTITY_SET_ABSENT'):
        fingerprint_edmx(PREFIX+b'<e:EntityType Name="Person"/>'+SUFFIX)


def test_reject_duplicate_identity():
    with pytest.raises(ValueError, match='EDMX_DUPLICATE_IDENTITY'):
        fingerprint_edmx(model(middle=b'<e:EntityType Name="Person"/>'))
