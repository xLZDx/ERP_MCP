"""Fake1C ASGI entry point for the disposable E2E environment (recording wrapper).

Every request that reaches the wrapper is appended to an in-memory list so that E2E suites can
prove (a) that the gateway only ever sent GET/HEAD to 1C and (b) that denied calls produced no
upstream traffic. Only the method, path, user agent, a boolean "had credentials" flag and the
numeric ``$top``/``$skip`` values are kept: never header values or bodies, so credentials cannot
leak into the evidence. The list is exposed read-only at ``GET /__ft__/requests?since=<seq>``
(same shape as the Functional Tester recorder: ``{"last_seq": int, "requests": [...]}``).

The wrapper does not change what Fake1C answers. The log is process-local: it restarts with the
process (outage tests take a fresh mark after restarting Fake1C).
"""

import os
import threading
import time
from urllib.parse import unquote

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from business_ai_gateway.testbed.fake1c import create_app

_LOCK = threading.Lock()
_REQUESTS: list[dict] = []
_SEQ = 0
_NUMERIC_PARAMS = ("$top", "$skip")


def _record(scope) -> None:
    global _SEQ
    query = (scope.get("query_string") or b"").decode("latin-1")
    pairs = [[unquote(x) for x in part.split("=", 1)] for part in query.split("&") if part]
    keys = sorted({pair[0] for pair in pairs})
    numeric = {
        pair[0]: int(pair[1])
        for pair in pairs
        if len(pair) == 2 and pair[0] in _NUMERIC_PARAMS and pair[1].lstrip("-").isdigit()
    }
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
    with _LOCK:
        _SEQ += 1
        _REQUESTS.append({
            "seq": _SEQ, "t": time.time(), "method": scope["method"], "path": scope["path"],
            "query_keys": keys, "numeric_params": numeric,
            "user_agent": headers.get("user-agent", ""),
            "had_authorization": "authorization" in headers,
        })


async def _requests(request: Request):
    since = int(request.query_params.get("since", "0"))
    with _LOCK:
        items = [item for item in _REQUESTS if item["seq"] > since]
        last = _SEQ
    return JSONResponse({"last_seq": last, "requests": items})


_inner = create_app(os.getenv("FAKE1C_PROFILE", "json"))
_outer = Starlette(routes=[Route("/__ft__/requests", _requests, methods=["GET"])])


async def app(scope, receive, send):
    if scope["type"] == "http" and scope["path"].startswith("/__ft__/"):
        await _outer(scope, receive, send)
        return
    if scope["type"] == "http":
        _record(scope)
    await _inner(scope, receive, send)
