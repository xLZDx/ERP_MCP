from business_ai_gateway.adapters.onec.metadata import parse_metadata


def test_metadata_extracts_entities_and_properties():
    xml = b"""<?xml version="1.0"?>
    <edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
      <edmx:DataServices>
        <Schema xmlns="http://schemas.microsoft.com/ado/2008/09/edm">
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
