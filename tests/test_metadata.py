from business_ai_gateway.adapters.onec.metadata import parse_metadata


def test_metadata_extracts_entities_and_properties():
    xml = b"""<?xml version="1.0"?>
    <edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
      <edmx:DataServices>
          <Schema xmlns="http://schemas.microsoft.com/ado/2008/09/edm" Namespace="X">
          <EntityType Name="Catalog_Organizations">
            <Property Name="Ref_Key" Type="Edm.Guid"/>
            <Property Name="Description" Type="Edm.String"/>
          </EntityType>
          <EntityContainer Name="C">
            <EntitySet Name="Catalog_Organizations" EntityType="X.Catalog_Organizations"/>
          </EntityContainer>
        </Schema>
      </edmx:DataServices>
    </edmx:Edmx>"""
    index = parse_metadata(xml)
    entity = index.entities[0]
    assert entity.name == "Catalog_Organizations"
    assert entity.properties == ("Ref_Key", "Description")


def test_html_and_non_odata_xml_are_not_metadata():
    import pytest

    for body in (
        b"<html><body>Service unavailable</body></html>",
        b"<Edmx></Edmx>",
        b"<error>nope</error>",
    ):
        with pytest.raises(ValueError):
            parse_metadata(body)


def test_metadata_resolves_aliases_before_external_property_annotations():
    xml = b'''<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx"
        xmlns:edm="http://schemas.microsoft.com/ado/2008/09/edm">
      <edmx:DataServices>
        <edm:Schema Namespace="urn:finance" Alias="Fin">
          <edm:EntityType Name="PeriodState">
            <edm:Property Name="Closed" Type="Edm.Boolean" />
          </edm:EntityType>
          <edm:EntityContainer Name="C">
            <edm:EntitySet Name="PeriodStates" EntityType="Fin.PeriodState" />
          </edm:EntityContainer>
          <edm:Annotations Target="Fin.PeriodState/Closed">
            <edm:Annotation Term="Org.OData.Core.V1.Description" String="Period is closed" />
          </edm:Annotations>
        </edm:Schema>
      </edmx:DataServices>
    </edmx:Edmx>'''

    entity = parse_metadata(xml).entities[0]

    assert entity.entity_type == "Fin.PeriodState"
    assert entity.properties == ("Closed",)
    assert entity.property_descriptions == (("Closed", "Period is closed"),)


def test_metadata_rejects_ambiguous_alias_and_unqualified_type():
    import pytest

    ambiguous_alias = b'''<Edmx><DataServices>
      <Schema Namespace="urn:a" Alias="X"><EntityType Name="T"><Property Name="A" Type="Edm.String"/></EntityType></Schema>
      <Schema Namespace="urn:b" Alias="X"><EntityType Name="T"><Property Name="B" Type="Edm.String"/></EntityType></Schema>
      <Schema Namespace="urn:c"><EntityContainer Name="C"><EntitySet Name="Items" EntityType="X.T"/></EntityContainer></Schema>
    </DataServices></Edmx>'''
    with pytest.raises(ValueError, match="ambiguous metadata namespace alias"):
        parse_metadata(ambiguous_alias)

    ambiguous_type = b'''<Edmx><DataServices>
      <Schema Namespace="urn:a"><EntityType Name="T"><Property Name="A" Type="Edm.String"/></EntityType></Schema>
      <Schema Namespace="urn:b"><EntityType Name="T"><Property Name="B" Type="Edm.String"/></EntityType></Schema>
      <Schema Namespace="urn:c"><EntityContainer Name="C"><EntitySet Name="Items" EntityType="T"/></EntityContainer></Schema>
    </DataServices></Edmx>'''
    with pytest.raises(ValueError, match="ambiguous unqualified metadata entity type"):
        parse_metadata(ambiguous_type)
