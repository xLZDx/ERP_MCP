from __future__ import annotations

import json
import os
import pathlib
import xml.etree.ElementTree as ET

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


FIXTURE_PATH = pathlib.Path(__file__).with_name("fixtures") / "seed.json"

METADATA = b"""<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema xmlns="http://schemas.microsoft.com/ado/2008/09/edm" Namespace="Fake1C">
      <EntityType Name="Catalog_Organizations">
        <Property Name="Ref_Key" Type="Edm.Guid"/>
        <Property Name="Code" Type="Edm.String"/>
        <Property Name="Description" Type="Edm.String"/>
        <NavigationProperty Name="Owner" Relationship="Fake1C.Owner"/>
      </EntityType>
      <EntityType Name="Catalog_Counterparties">
        <Property Name="Ref_Key" Type="Edm.Guid"/>
        <Property Name="Code" Type="Edm.String"/>
        <Property Name="Description" Type="Edm.String"/>
      </EntityType>
      <EntityType Name="Document_Sales">
        <Property Name="Ref_Key" Type="Edm.Guid"/>
        <Property Name="Number" Type="Edm.String"/>
        <Property Name="Posted" Type="Edm.Boolean"/>
        <Property Name="Amount" Type="Edm.Decimal"/>
      </EntityType>
      <EntityContainer Name="Container">
        <EntitySet Name="Catalog_Organizations" EntityType="Fake1C.Catalog_Organizations"/>
        <EntitySet Name="Catalog_Counterparties" EntityType="Fake1C.Catalog_Counterparties"/>
        <EntitySet Name="Document_Sales" EntityType="Fake1C.Document_Sales"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>"""


def _seed():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _rows(entity: str):
    seed = _seed()
    mapping = {
        "Catalog_Organizations": seed["organizations"],
        "Catalog_Counterparties": seed["counterparties"],
        "Document_Sales": seed["sales"],
    }
    if entity not in mapping:
        raise KeyError(entity)
    return mapping[entity]


def _atom(rows) -> bytes:
    atom = "http://www.w3.org/2005/Atom"
    m = "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
    d = "http://schemas.microsoft.com/ado/2007/08/dataservices"
    ET.register_namespace("", atom)
    ET.register_namespace("m", m)
    ET.register_namespace("d", d)
    feed = ET.Element(f"{{{atom}}}feed")
    for row in rows:
        entry = ET.SubElement(feed, f"{{{atom}}}entry")
        content = ET.SubElement(entry, f"{{{atom}}}content")
        props = ET.SubElement(content, f"{{{m}}}properties")
        for key, value in row.items():
            element = ET.SubElement(props, f"{{{d}}}{key}")
            if value is None:
                element.set(f"{{{m}}}null", "true")
            else:
                element.text = str(value).lower() if isinstance(value, bool) else str(value)
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)


def create_app(profile: str = "json") -> Starlette:
    if profile not in {"json", "atom"}:
        raise ValueError("profile must be json or atom")

    async def metadata(_: Request):
        return Response(METADATA, media_type="application/xml")

    async def entity(request: Request):
        name = request.path_params["entity"]
        try:
            rows = _rows(name)
        except KeyError:
            return JSONResponse({"error": "unknown entity"}, status_code=404)

        top = int(request.query_params.get("$top", len(rows)))
        rows = rows[: max(0, top)]
        accept = request.headers.get("accept", "")

        if profile == "atom":
            if "json" in accept:
                return Response(status_code=406)
            return Response(_atom(rows), media_type="application/atom+xml")

        if "atom" in accept:
            return Response(_atom(rows), media_type="application/atom+xml")

        return JSONResponse({"d": {"results": rows}})

    return Starlette(
        routes=[
            Route("/odata/standard.odata/$metadata", metadata, methods=["GET", "HEAD"]),
            Route("/odata/standard.odata/{entity}", entity, methods=["GET"]),
        ]
    )


app = create_app(os.getenv("FAKE1C_PROFILE", "json"))
