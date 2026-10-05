from __future__ import annotations

import html

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


SEED = {
    "organizations": [
        {
            "Ref_Key": "00000000-0000-0000-0000-000000000001",
            "Code": "ORG1",
            "Description": "MCP TEST SRL",
        },
        {
            "Ref_Key": "00000000-0000-0000-0000-000000000002",
            "Code": "ORG2",
            "Description": "MCP TEST TWO SRL",
        },
    ],
    "counterparties": [
        {
            "Ref_Key": "10000000-0000-0000-0000-000000000001",
            "Code": "C001",
            "Description": "Customer Alpha",
        },
        {
            "Ref_Key": "10000000-0000-0000-0000-000000000002",
            "Code": "S001",
            "Description": "Supplier Beta",
        },
    ],
    "sales": [
        {
            "Ref_Key": "20000000-0000-0000-0000-000000000001",
            "Number": "SALE-001",
            "Posted": True,
            "Amount": 1200.0,
        },
        {
            "Ref_Key": "20000000-0000-0000-0000-000000000002",
            "Number": "SALE-002",
            "Posted": False,
            "Amount": 500.0,
        },
    ],
}

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


def _rows(entity: str):
    mapping = {
        "Catalog_Organizations": SEED["organizations"],
        "Catalog_Counterparties": SEED["counterparties"],
        "Document_Sales": SEED["sales"],
    }
    if entity not in mapping:
        raise KeyError(entity)
    return mapping[entity]


def _atom(rows) -> bytes:
    atom = "http://www.w3.org/2005/Atom"
    metadata_ns = "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"
    data_ns = "http://schemas.microsoft.com/ado/2007/08/dataservices"
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<feed xmlns="{atom}" xmlns:m="{metadata_ns}" xmlns:d="{data_ns}">',
    ]
    for row in rows:
        parts.append("<entry><content><m:properties>")
        for key, value in row.items():
            if value is None:
                parts.append(f"<d:{key} m:null=\"true\" />")
            else:
                text = str(value).lower() if isinstance(value, bool) else str(value)
                parts.append(f"<d:{key}>{html.escape(text)}</d:{key}>")
        parts.append("</m:properties></content></entry>")
    parts.append("</feed>")
    return "".join(parts).encode("utf-8")


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
