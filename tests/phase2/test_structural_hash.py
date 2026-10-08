"""Isolated tests for the Phase 2 OBSERVED metadata fingerprint helper."""
from xml.etree.ElementTree import ParseError

import pytest
from defusedxml.common import DefusedXmlException

from business_ai_gateway.phase2.structural_hash import fingerprint_edmx as _fingerprint_edmx


def fingerprint_edmx(xml, **kwargs):
    kwargs.setdefault("tenant_id", "t1")
    kwargs.setdefault("source_id", "s1")
    return _fingerprint_edmx(xml, **kwargs)

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


def _swap(xml, old, new):
    assert old in xml
    return xml.replace(old, new, 1)


def test_root_edmx_attribute_change_changes_structural_hash_without_object_change():
    a = fingerprint_edmx(model())
    b = fingerprint_edmx(_swap(model(), b'Version="1"', b'Version="4"'))
    assert a.objects == b.objects
    assert a.structural_sha256 != b.structural_sha256
    assert a.residual_sha256 != b.residual_sha256


def test_data_services_attribute_change_is_covered():
    base = model()
    a = fingerprint_edmx(base)
    b = fingerprint_edmx(_swap(base, b'<edmx:DataServices>',
                               b'<edmx:DataServices xmlns:m="urn:m" m:DataServiceVersion="3.0">'))
    assert a.objects == b.objects
    assert a.structural_sha256 != b.structural_sha256


def test_reference_element_is_covered():
    base = model()
    a = fingerprint_edmx(base)
    b = fingerprint_edmx(_swap(base, b'<edmx:DataServices>',
                               b'<edmx:Reference Uri="urn:other"/><edmx:DataServices>'))
    assert a.objects == b.objects
    assert a.structural_sha256 != b.structural_sha256
    assert a.residual_sha256 != b.residual_sha256


def test_unnamed_schema_child_is_covered():
    a = fingerprint_edmx(model())
    b = fingerprint_edmx(model(middle=b'<e:Annotations Target="Sample.Person"/>'))
    assert a.objects == b.objects
    assert a.structural_sha256 != b.structural_sha256
    assert a.residual_sha256 != b.residual_sha256


def test_schema_attribute_change_is_covered():
    base = model()
    a = fingerprint_edmx(base)
    b = fingerprint_edmx(_swap(base, b'Namespace="Sample"', b'Namespace="Sample" Alias="S"'))
    assert a.objects == b.objects
    assert a.structural_sha256 != b.structural_sha256


def test_named_object_change_leaves_residual_hash_unchanged():
    a = fingerprint_edmx(model())
    b = fingerprint_edmx(model().replace(b'MaxLength="10"', b'MaxLength="12"'))
    assert a.structural_sha256 != b.structural_sha256
    assert a.residual_sha256 == b.residual_sha256


def test_schema_and_reference_order_does_not_change_hash():
    two = (b'<edmx:Edmx xmlns:edmx="urn:edmx" xmlns:e="urn:edm"><edmx:DataServices>'
           b'<e:Schema Namespace="A"><e:EntityContainer Name="C"><e:EntitySet Name="S" EntityType="A.T"/>'
           b'</e:EntityContainer></e:Schema><e:Schema Namespace="B"><e:EntityType Name="T"/></e:Schema>'
           b'</edmx:DataServices></edmx:Edmx>')
    swapped = (b'<edmx:Edmx xmlns:edmx="urn:edmx" xmlns:e="urn:edm"><edmx:DataServices>'
               b'<e:Schema Namespace="B"><e:EntityType Name="T"/></e:Schema>'
               b'<e:Schema Namespace="A"><e:EntityContainer Name="C"><e:EntitySet Name="S" EntityType="A.T"/>'
               b'</e:EntityContainer></e:Schema></edmx:DataServices></edmx:Edmx>')
    assert fingerprint_edmx(two).structural_sha256 == fingerprint_edmx(swapped).structural_sha256


def test_deep_nesting_is_rejected_with_coded_error():
    deep = b'<e:X>' * 500 + b'</e:X>' * 500
    with pytest.raises(ValueError, match="EDMX_DEPTH_EXCEEDED"):
        fingerprint_edmx(model(middle=deep))


def test_malformed_xml_is_wrapped_in_coded_value_error():
    with pytest.raises(ValueError, match="EDMX_PARSE_ERROR") as info:
        fingerprint_edmx(b'<edmx:Edmx xmlns:edmx="urn:edmx"><unclosed>')
    assert not isinstance(info.value, ParseError)


def test_forbidden_entity_is_wrapped_in_coded_value_error():
    with pytest.raises(ValueError, match="EDMX_FORBIDDEN_XML"):
        fingerprint_edmx(b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>')


def test_object_key_separator_is_escaped_so_distinct_objects_do_not_collide():
    xml = (b'<edmx:Edmx xmlns:edmx="urn:edmx" xmlns:e="urn:edm"><edmx:DataServices>'
           b'<e:Schema Namespace="A"><e:EntityType Name="X::Y"/>'
           b'<e:EntityContainer Name="C"><e:EntitySet Name="S" EntityType="A.T"/></e:EntityContainer></e:Schema>'
           b'<e:Schema Namespace="A::EntityType"><e:X Name="Y"/></e:Schema>'
           b'</edmx:DataServices></edmx:Edmx>')
    result = fingerprint_edmx(xml)  # used to raise a false EDMX_DUPLICATE_IDENTITY
    names = [name for name, _ in result.objects]
    assert len(names) == len(set(names)) == 4
    assert "A%3A%3AEntityType::X::Y" in names
    assert "A::EntityType::X%3A%3AY" in names


def test_fingerprint_carries_scope_and_requires_it():
    f = fingerprint_edmx(model(), tenant_id="tenant-9", source_id="src-9")
    assert (f.tenant_id, f.source_id) == ("tenant-9", "src-9")
    for tenant, source in [("", "s"), ("t", ""), (None, "s"), ("t", None), (3, "s")]:
        with pytest.raises(ValueError, match="FINGERPRINT_SCOPE_INVALID"):
            fingerprint_edmx(model(), tenant_id=tenant, source_id=source)


DOC = b'<e:Documentation><e:Summary>Customer card</e:Summary></e:Documentation>'


def test_text_change_inside_documentation_changes_hash():
    a = fingerprint_edmx(model(middle=DOC))
    b = fingerprint_edmx(model(middle=DOC.replace(b'Customer card', b'Supplier card')))
    assert a.structural_sha256 != b.structural_sha256


def test_whitespace_padding_inside_text_element_does_not_change_hash():
    a = fingerprint_edmx(model(middle=DOC))
    padded = DOC.replace(b'Customer card', b'\n   Customer card \t\n')
    b = fingerprint_edmx(model(middle=padded))
    assert a.structural_sha256 == b.structural_sha256


def test_reordered_property_ref_changes_hash():
    two_props = (b'<e:Property Name="Code" Type="Edm.String"/>'
                 b'<e:Property Name="Date" Type="Edm.DateTime"/>')

    def keyed(first, second):
        return model(two_props).replace(
            b'<e:Key><e:PropertyRef Name="Code"/></e:Key>',
            b'<e:Key><e:PropertyRef Name="' + first + b'"/><e:PropertyRef Name="'
            + second + b'"/></e:Key>')

    a = fingerprint_edmx(keyed(b'Code', b'Date'))
    b = fingerprint_edmx(keyed(b'Date', b'Code'))
    assert a.structural_sha256 != b.structural_sha256
