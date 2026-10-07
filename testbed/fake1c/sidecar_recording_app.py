"""Recording wrapper in front of the TEST-ONLY fake OData sidecar (disposable E2E environment).

Like testbed/fake1c/app.py for Fake1C, every request that reaches the wrapper is logged in memory
and exposed read-only at ``GET /__ft__/requests?since=<seq>`` (same envelope as the Functional
Tester recorder: ``{"last_seq": int, "requests": [...]}``). For POST /v1/read the entry also keeps
the structural, non-secret request shape the E2E suites need to prove bounded and projected
upstream reads: operation, entity_set, numeric top/skip, the select FIELD NAMES and whether a
filter was present (never the filter text, never headers, never the bearer token).

The log is process-local and restarts with the process.
"""

import json
import os
import threading
import time

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from business_ai_gateway.testbed.fake_sidecar import create_sidecar_app

_LOCK = threading.Lock()
_REQUESTS: list[dict] = []
_SEQ = 0


def _shape(body: bytes) -> dict:
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    select = data.get("select")
    return {
        "operation": data.get("operation") if isinstance(data.get("operation"), str) else None,
        "entity_set": data.get("entity_set") if isinstance(data.get("entity_set"), str) else None,
        "top": data.get("top") if isinstance(data.get("top"), int) else None,
        "skip": data.get("skip") if isinstance(data.get("skip"), int) else None,
        "select": [s for s in select if isinstance(s, str)] if isinstance(select, list) else [],
        "has_filter": bool(data.get("filter")),
    }


def _record(scope, body: bytes) -> None:
    global _SEQ
    shape = _shape(body) if scope["method"] == "POST" else {}
    with _LOCK:
        _SEQ += 1
        _REQUESTS.append({"seq": _SEQ, "t": time.time(), "method": scope["method"],
                          "path": scope["path"], "query_keys": [], **shape})


async def _requests(request: Request):
    since = int(request.query_params.get("since", "0"))
    with _LOCK:
        items = [item for item in _REQUESTS if item["seq"] > since]
        last = _SEQ
    return JSONResponse({"last_seq": last, "requests": items})


_inner = create_sidecar_app(os.getenv("FAKE_SIDECAR_TOKEN") or None)
_outer = Starlette(routes=[Route("/__ft__/requests", _requests, methods=["GET"])])


async def app(scope, receive, send):
    if scope["type"] != "http":
        await _inner(scope, receive, send)
        return
    if scope["path"].startswith("/__ft__/"):
        await _outer(scope, receive, send)
        return
    chunks, more = [], True
    while more:  # buffer the (small) body, then replay it to the wrapped app
        message = await receive()
        if message["type"] != "http.request":
            break
        chunks.append(message.get("body", b""))
        more = message.get("more_body", False)
    body = b"".join(chunks)
    _record(scope, body)
    sent = False

    async def replay():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()

    await _inner(scope, replay, send)
