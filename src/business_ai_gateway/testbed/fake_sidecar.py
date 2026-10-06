"""TEST-ONLY fake of the pinned OData sidecar protocol, backed by the Fake1C seed.

Implements the read-only POST v1/read and POST v1/capabilities/registers contract that
ODataSidecarClient expects, evaluating the filters the gateway builds against the in-process
Fake1C seed (no network egress, no 1C). It is a protocol double for L1 synthetic evidence only and
is never native 1C evidence. There is no write operation.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..adapters.onec.sidecar_client import UPSTREAM_SHA
from .fake1c import METADATA, VIRTUAL_TABLES, _rows, apply_query

REGISTER_KINDS = ("Accumulation", "Information", "Accounting")


def metadata_fingerprint() -> str:
    return hashlib.sha256(METADATA).hexdigest()


def _capability_profile(
    source_id: str, virtual_tables: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    fingerprint = metadata_fingerprint()
    registers = []
    tables = VIRTUAL_TABLES if virtual_tables is None else virtual_tables
    for entity_set, methods_available in sorted(tables.items()):
        kind = entity_set.split("Register_", 1)[0]
        methods: dict[str, Any] = {}
        for method in ("records", "recordsets"):
            methods[method] = {
                "available": True,
                "evidence": {
                    "kind": "metadata-entity-set",
                    "entity_set": entity_set,
                    "metadata_fingerprint": fingerprint,
                },
            }
        for method in methods_available:
            methods[method] = {
                "available": True,
                "evidence": {
                    "kind": "metadata-get-function-import",
                    "entity_set": entity_set,
                    "function_import": method,
                    "http_method": "GET",
                    "metadata_fingerprint": fingerprint,
                    "synthetic": True,
                },
            }
        registers.append({"entity_set": entity_set, "register_kind": kind, "methods": methods})
    return {
        "schema_version": 1,
        "source_id": source_id,
        "evidence_source": "live-metadata",
        "discovered_at": datetime.now(UTC).isoformat(),
        "metadata_fingerprint": fingerprint,
        "registers": registers,
    }


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code}}, status_code=status)


def _virtual_read(entity_set: str, method: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    from .fake1c import virtual_table_rows

    return virtual_table_rows(entity_set, method, args)


def create_sidecar_app(
    token: str | None = None, virtual_tables: dict[str, list[str]] | None = None
) -> Starlette:
    async def capabilities(request: Request):
        if token and request.headers.get("authorization") != f"Bearer {token}":
            return _error(401, "UNAUTHORIZED")
        body = await request.json()
        source_id = body.get("source_id")
        profile = _capability_profile(source_id, virtual_tables)
        return JSONResponse(
            _envelope(source_id, "register_capabilities", [], capability_profile=profile)
        )

    async def read(request: Request):
        if token and request.headers.get("authorization") != f"Bearer {token}":
            return _error(401, "UNAUTHORIZED")
        body = await request.json()
        operation = body.get("operation")
        source_id = body.get("source_id")
        entity_set = body.get("entity_set") or ""
        top = int(body.get("top", 100))
        try:
            if operation == "query":
                params: dict[str, Any] = {"$top": top, "$skip": int(body.get("skip", 0))}
                if body.get("filter"):
                    params["$filter"] = body["filter"]
                if body.get("orderby"):
                    params["$orderby"] = ",".join(body["orderby"])
                if body.get("select"):
                    params["$select"] = ",".join(body["select"])
                data = apply_query(_rows(entity_set), params)
            elif operation == "count":
                params = {"$filter": body["filter"]} if body.get("filter") else {}
                data = [{"count": len(apply_query(_rows(entity_set), params))}]
            elif operation == "register_read":
                data = _virtual_read(
                    body["register_set"], body["register_method"], body.get("register_args") or {}
                )[:top]
            else:
                return _error(400, "UNSUPPORTED_OPERATION")
        except KeyError:
            return _error(404, "UNKNOWN_ENTITY")
        except LookupError:
            return _error(422, "CAPABILITY_UNSUPPORTED")
        except ValueError:
            return _error(400, "INVALID_QUERY")
        return JSONResponse(_envelope(source_id, operation, data, top=top))

    return Starlette(
        routes=[
            Route("/v1/capabilities/registers", capabilities, methods=["POST"]),
            Route("/v1/read", read, methods=["POST"]),
        ]
    )


def _envelope(source_id, operation, data, *, capability_profile=None, top=None) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "source_id": source_id,
        "adapter": {
            "kind": "ODATA_JSON_V3",
            "version": "fake-sidecar",
            "upstream_sha": UPSTREAM_SHA,
        },
        "operation": operation,
        "data": [_jsonable(row) for row in data],
        "page": {
            "returned": len(data),
            "has_more": top is not None and len(data) == top,
            "truncated": False,
        },
    }
    if capability_profile is not None:
        envelope["capability_profile"] = capability_profile
    return envelope


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value
